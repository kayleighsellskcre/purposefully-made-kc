"""Creators earn store credit (default 2%) when an order through their link is picked up or shipped."""
from datetime import datetime

from models import CreditEntry, Order, OrderItem, SharedDesign, User, db
from tests.conftest import CUSTOMER_EMAIL
from tests.test_save_for_later import _line, _set_cart, _signed_in
from tests.test_share_design import _share
from utils import creator_credit as CC
from utils.production_stages import apply_stage


def _order(app, seed, email='friend@example.com', user_id=None, number='PMKC-CC1'):
    with app.app_context():
        share = SharedDesign.query.one()
        order = Order(order_number=number, email=email, user_id=user_id, first_name='F', last_name='F', subtotal=100.0, total=108.0,
                      payment_status='paid', status='paid', payment_method='stripe', fulfillment_method='pickup',
                      paid_at=datetime.utcnow())
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black',
                                 quantity=2, unit_price=50.0, subtotal=100.0, shared_design_id=share.id))
        db.session.commit()
        return order.id


def _creator_id(app):
    with app.app_context():
        return User.query.filter_by(email=CUSTOMER_EMAIL).first().id


def test_credit_is_earned_once_when_picked_up_not_before(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    _share(_signed_in(app))
    oid = _order(app, seed)
    with app.app_context():
        assert CC.balance(_creator_id(app)) == 0.0
        order = db.session.get(Order, oid)
        apply_stage(order, 'picked_up')
        db.session.commit()
        assert CC.balance(_creator_id(app)) == 2.0          # 2% of $100, not of tax or shipping
        apply_stage(db.session.get(Order, oid), 'picked_up')
        db.session.commit()
        assert CC.balance(_creator_id(app)) == 2.0          # never twice
        assert CreditEntry.query.count() == 1


def test_nothing_is_earned_on_your_own_order_and_a_refund_takes_it_back(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    _share(_signed_in(app))
    uid = _creator_id(app)
    own = _order(app, seed, email=CUSTOMER_EMAIL, user_id=uid, number='PMKC-CC2')
    with app.app_context():
        assert CC.earn_for_order(db.session.get(Order, own)) == 0
    oid = _order(app, seed, number='PMKC-CC3')
    with app.app_context():
        order = db.session.get(Order, oid)
        CC.earn_for_order(order)
        db.session.commit()
        assert CC.balance(uid) == 2.0
        order.is_refunded = True
        CC.reverse_for_order(order)
        CC.reverse_for_order(order)
        db.session.commit()
        assert CC.balance(uid) == 0.0


def test_balance_shows_on_the_shared_designs_page_and_the_rate_can_be_changed(app, seed):
    from utils.site_settings import set_setting
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    _share(shopper)
    oid = _order(app, seed)
    with app.app_context():
        set_setting(CC.RATE_KEY, '1.5')
        CC.earn_for_order(db.session.get(Order, oid))
        db.session.commit()
    html = shopper.get('/account/shared-designs').get_data(as_text=True)
    assert '$1.50' in html and 'never expires' in html and '1.5% of the shirt price' in html


def test_owner_changes_the_percent_in_site_settings(app, seed):
    from tests.conftest import ADMIN_EMAIL, PASSWORD
    admin = app.test_client()
    admin.post('/auth/login', data={'email': ADMIN_EMAIL, 'password': PASSWORD})
    page = admin.get('/admin/operations/site-settings').get_data(as_text=True)
    assert 'Store credit for shared designs' in page
    admin.post('/admin/operations/site-settings', data={'section': 'credit', 'credit_percent': '1.5'})
    admin.post('/admin/operations/site-settings', data={'section': 'credit', 'credit_percent': '99'})   # refused
    with app.app_context():
        assert CC.rate_percent() == 1.5


def _give_credit(app, amount, user_id=None):
    with app.app_context():
        db.session.add(CreditEntry(user_id=user_id or _creator_id(app), amount=amount, kind='earned', note='test'))
        db.session.commit()


def test_credit_is_a_discount_that_lowers_the_tax_and_always_leaves_a_dollar(app, seed):
    from routes.checkout import calculate_totals
    uid = _creator_id(app)
    _give_credit(app, 10.0)
    cart = [{'product_id': seed['tee_id'], 'quantity': 2, 'unit_price': 30.00}]
    with app.test_request_context():
        t = calculate_totals(cart, 'pickup', credit_user_id=uid)
        assert t['credit_applied'] == 10.0 and t['gross_subtotal'] == 60.0 and t['subtotal'] == 50.0
        assert t['tax'] == round(50.0 * 0.095, 2) and t['total'] == round(50.0 + t['tax'], 2)
        small = calculate_totals([{'product_id': seed['tee_id'], 'quantity': 1, 'unit_price': 5.00}], 'pickup', credit_user_id=uid)
        assert small['credit_applied'] == 4.0 and small['subtotal'] == 1.0
        assert calculate_totals(cart, 'pickup')['credit_applied'] == 0.0           # guests never get any


def test_a_paid_order_spends_the_credit_once_and_a_refund_gives_it_back(app, seed):
    uid = _creator_id(app)
    _give_credit(app, 10.0)
    with app.app_context():
        order = Order(order_number='PMKC-CC9', email=CUSTOMER_EMAIL, user_id=uid, first_name='C', last_name='C', subtotal=50.0,
                      total=54.75, credit_applied=10.0, payment_status='paid', status='paid', payment_method='stripe')
        db.session.add(order)
        db.session.flush()
        assert CC.spend_for_order(order) == 10.0 and CC.spend_for_order(order) == 0.0
        db.session.commit()
        assert CC.balance(uid) == 0.0
        order.is_refunded = True
        CC.reverse_for_order(order)
        CC.reverse_for_order(order)
        db.session.commit()
        assert CC.balance(uid) == 10.0


def test_turning_automatic_use_off_saves_the_credit(app, seed):
    from routes.checkout import calculate_totals
    uid = _creator_id(app)
    _give_credit(app, 10.0)
    shopper = _signed_in(app)
    shopper.post('/account/store-credit/toggle')
    with app.test_request_context():
        assert calculate_totals([{'product_id': seed['tee_id'], 'quantity': 2, 'unit_price': 30.00}], 'pickup',
                                credit_user_id=uid)['credit_applied'] == 0.0
    assert 'Automatic use is off' in shopper.get('/account/shared-designs').get_data(as_text=True)
