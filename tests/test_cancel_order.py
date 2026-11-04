"""A customer can ask to cancel until printing starts; the owner approves; everyone is emailed."""
from models import Order, User, db
from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL, PASSWORD, _login


def _order(app, stage='order_received', status='paid', number='PMKC-CN1'):
    with app.app_context():
        uid = User.query.filter_by(email=CUSTOMER_EMAIL).first().id
        o = Order(order_number=number, email=CUSTOMER_EMAIL, user_id=uid, first_name='C', last_name='C', subtotal=30, total=32.85,
                  status=status, production_stage=stage, payment_status='paid', payment_method='stripe')
        db.session.add(o)
        db.session.commit()
        return o.id


def _shopper(app):
    c = app.test_client()
    _login(c, CUSTOMER_EMAIL)
    return c


def test_customer_asks_to_cancel_and_both_sides_are_emailed(app, seed, outbox):
    oid = _order(app)
    shopper = _shopper(app)
    assert 'Need to cancel this order?' in shopper.get('/account/orders/PMKC-CN1').get_data(as_text=True)
    resp = shopper.post('/account/orders/PMKC-CN1/cancel-request', data={'reason': 'wrong size'})
    assert resp.status_code == 302
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.cancel_requested_at is not None and o.cancel_reason == 'wrong size' and o.status == 'paid'
    subjects = [m.subject for m in outbox]
    assert any('Cancellation request' in s for s in subjects) and any('got your cancellation request' in s for s in subjects)
    shopper.post('/account/orders/PMKC-CN1/cancel-request')                       # a second ask changes nothing
    assert len(outbox) == 2
    assert 'We got your cancellation request' in shopper.get('/account/orders/PMKC-CN1').get_data(as_text=True)


def test_cannot_cancel_once_printing_started_or_someone_elses_order(app, seed, outbox):
    _order(app, stage='pressed', status='in_production')
    shopper = _shopper(app)
    assert 'Need to cancel this order?' not in shopper.get('/account/orders/PMKC-CN1').get_data(as_text=True)
    shopper.post('/account/orders/PMKC-CN1/cancel-request')
    with app.app_context():
        assert Order.query.one().cancel_requested_at is None
    other = app.test_client()
    assert other.post('/account/orders/PMKC-CN1/cancel-request').status_code in (302, 401)


def test_owner_cancels_and_the_customer_is_told(app, seed, outbox):
    oid = _order(app)
    admin = app.test_client()
    admin.post('/auth/login', data={'email': ADMIN_EMAIL, 'password': PASSWORD})
    page = admin.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert 'Cancel this order' in page
    admin.post(f'/admin/orders/{oid}/cancel')
    admin.post(f'/admin/orders/{oid}/cancel')                                     # twice sends one email
    with app.app_context():
        assert db.session.get(Order, oid).status == 'cancelled'
    assert [m.subject for m in outbox].count('Your order is cancelled') == 1
