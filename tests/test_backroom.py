"""The Backroom: only keyholders earn, the keyhole door takes a one-time key, and the owner hears about every share."""
from datetime import datetime

from models import KeyCode, Order, OrderItem, SharedDesign, User, db
from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL, PASSWORD
from tests.test_save_for_later import _line, _set_cart, _signed_in
from tests.test_share_design import _share
from utils import creator_credit as CC


def _paid_order_through_link(app, seed):
    with app.app_context():
        share = SharedDesign.query.one()
        order = Order(order_number='PMKC-BR1', email='friend@example.com', first_name='F', last_name='F', subtotal=100.0,
                      total=108.0, payment_status='paid', status='paid', payment_method='stripe', fulfillment_method='pickup',
                      paid_at=datetime.utcnow())
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black',
                                 quantity=2, unit_price=50.0, subtotal=100.0, shared_design_id=share.id))
        db.session.commit()
        return order.id


def _admin(app):
    c = app.test_client()
    c.post('/auth/login', data={'email': ADMIN_EMAIL, 'password': PASSWORD})
    return c


def test_someone_without_a_key_shares_and_orders_but_earns_nothing(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    _share(_signed_in(app))
    oid = _paid_order_through_link(app, seed)
    with app.app_context():
        assert CC.earn_for_order(db.session.get(Order, oid)) == 0
        User.query.filter_by(email=CUSTOMER_EMAIL).first().is_keyholder = True
        db.session.commit()
        assert CC.earn_for_order(db.session.get(Order, oid)) == 1


def test_the_door_takes_a_one_time_key(app, seed):
    admin = _admin(app)
    admin.post('/admin/backroom/code', data={'note': 'for Sam'})
    with app.app_context():
        code = KeyCode.query.one()
        typed = code.pretty.lower()
    shopper = _signed_in(app)
    assert b'Look what you found' in shopper.get('/backroom').data
    assert b'does not fit' in shopper.post('/backroom/unlock', data={'code': 'WRONG'}, follow_redirects=True).data
    page = shopper.post('/backroom/unlock', data={'code': typed}, follow_redirects=True)
    assert b'Welcome to The Backroom' in page.data
    with app.app_context():
        assert User.query.filter_by(email=CUSTOMER_EMAIL).first().is_keyholder is True
    assert app.test_client().get('/backroom').status_code == 200          # strangers see the door
    assert shopper.get('/backroom').status_code == 302                    # a keyholder walks straight in


def test_the_owner_gives_and_takes_back_keys(app, seed):
    admin = _admin(app)
    admin.post('/admin/backroom/grant', data={'email': CUSTOMER_EMAIL.upper()})
    with app.app_context():
        user = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        assert user.is_keyholder is True
        uid = user.id
    assert CUSTOMER_EMAIL.encode() in admin.get('/admin/backroom').data
    admin.post(f'/admin/backroom/revoke/{uid}')
    with app.app_context():
        assert User.query.filter_by(email=CUSTOMER_EMAIL).first().is_keyholder is False


def test_the_owner_is_emailed_when_a_design_is_shared(app, seed, monkeypatch):
    sent = []
    import utils.mailer as mailer
    monkeypatch.setattr(mailer, 'send', lambda app_, msg, description='email': sent.append(msg) or True)
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    _share(shopper)
    _share(shopper)                      # the same design again is not a new share
    assert len(sent) == 1
    assert 'Design shared' in sent[0].subject and CUSTOMER_EMAIL in sent[0].body and 'not a keyholder' in sent[0].body


def test_keyhole_is_in_the_footer_and_only_keyholders_see_the_backroom_name(app, seed):
    assert b'footer-keyhole' in app.test_client().get('/').data
    shopper = _signed_in(app)
    assert b'Shared Designs' in shopper.get('/account/shared-designs').data
    with app.app_context():
        User.query.filter_by(email=CUSTOMER_EMAIL).first().is_keyholder = True
        db.session.commit()
    assert b'The Backroom' in shopper.get('/account/shared-designs').data
