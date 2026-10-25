"""The pickup desk: hand an order over, record cash, QR on the bag label."""
import threading
from datetime import datetime

import pytest

from models import LedgerEntry, Order, OrderItem, db
from utils import ledger as L
from utils import pickup as P


def _in_db(app, fn):
    out = {}

    def run():
        with app.app_context():
            try:
                out['value'] = fn()
            except Exception as exc:          # pragma: no cover
                out['error'] = exc
    t = threading.Thread(target=run)
    t.start()
    t.join()
    if 'error' in out:
        raise out['error']
    return out.get('value')


def _order(number, **kw):
    defaults = dict(email='a@example.com', first_name='Amy', last_name='Lee', subtotal=50.0, shipping_cost=0.0, tax=0.0, total=50.0,
                    payment_status='paid', status='ready', production_stage='packaged_ready', payment_method='stripe',
                    fulfillment_method='pickup', paid_at=datetime(2026, 10, 20, 15, 0))
    defaults.update(kw)
    o = Order(order_number=number, **defaults)
    db.session.add(o)
    db.session.commit()
    return o


@pytest.fixture(autouse=True)
def _unthrottled():
    L._LAST_SYNC['at'] = 0.0
    yield
    L._LAST_SYNC['at'] = 0.0


def test_a_paid_order_is_handed_over(app, seed):
    def go():
        o = _order('PAID1')
        ok, message = P.hand_over(o)
        assert ok and 'handed over' in message and o.status == 'picked_up' and o.completed_at is not None
        again_ok, again = P.hand_over(o)
        assert not again_ok and 'already' in again
    _in_db(app, go)


def test_a_cash_order_is_paid_and_booked_when_handed_over(app, seed):
    def go():
        o = _order('CASH1', payment_method='cash', payment_status='pending', paid_at=None, status='ready', total=40.0, subtotal=40.0)
        assert P.cash_due(o)
        ok, message = P.hand_over(o)
        assert ok and '$40.00 cash' in message
        assert o.payment_status == 'paid' and o.paid_at is not None and o.amount_paid == 40.0
        sales = db.session.query(db.func.sum(LedgerEntry.amount_cents)).filter(LedgerEntry.order_id == o.id, LedgerEntry.entry_type == L.SALE).scalar()
        assert sales == 4000
    _in_db(app, go)


def test_unpaid_and_shipping_orders_are_refused(app, seed):
    def go():
        unpaid = _order('UNPAID1', payment_status='pending', payment_method='stripe', paid_at=None)
        shipping = _order('SHIP1', fulfillment_method='shipping')
        for o in (unpaid, shipping):
            ok, _msg = P.hand_over(o)
            assert not ok and o.status == 'ready'
    _in_db(app, go)


def test_waiting_list_and_search(app, seed):
    def go():
        _order('WAIT1')
        _order('WAIT2', first_name='Zed', last_name='Zimmer')
        _order('SHIP2', fulfillment_method='shipping')
        _order('DONE1', status='picked_up', production_stage='completed')
        assert sorted(o.order_number for o in P.ready_for_pickup()) == ['WAIT1', 'WAIT2']
        assert [o.order_number for o in P.find('zimmer')] == ['WAIT2']
        assert P.find('') == [] and P.find('SHIP2') == [] and P.find('DONE1') == []
    _in_db(app, go)


def test_pages_for_admin(admin_client, app, seed):
    def make():
        o = _order('PAGE1')
        db.session.add(OrderItem(order_id=o.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black', quantity=2, unit_price=25.0, subtotal=50.0))
        db.session.commit()
        return o.id
    oid = _in_db(app, make)
    desk = admin_client.get('/admin/pickup')
    assert desk.status_code == 200 and b'PAGE1' in desk.data
    page = admin_client.get(f'/admin/pickup/{oid}')
    assert page.status_code == 200 and b'Paid in full' in page.data and b'Hand over' in page.data
    qr = admin_client.get(f'/admin/orders/{oid}/pickup-qr.png')
    assert qr.status_code == 200 and qr.data.startswith(b'\x89PNG')
    done = admin_client.post(f'/admin/pickup/{oid}', follow_redirects=True)
    assert b'handed over' in done.data
    assert admin_client.get(f'/admin/pickup/{oid}').data.count(b'Already handed over') == 1


def test_labels_can_carry_the_qr(admin_client, app):
    def make():
        return _order('LBL1', status='paid', production_stage='ready_to_press').id
    oid = _in_db(app, make)
    without = admin_client.get('/admin/orders/print-labels?stage=ready_to_press')
    with_qr = admin_client.get('/admin/orders/print-labels?stage=ready_to_press&qr=1')
    assert without.status_code == with_qr.status_code == 200
    assert b'pickup-qr.png' not in without.data and f'/admin/orders/{oid}/pickup-qr.png'.encode() in with_qr.data


def test_pickup_pages_closed_to_guests(guest):
    for path in ('/admin/pickup', '/admin/pickup/1', '/admin/orders/1/pickup-qr.png'):
        assert guest.get(path).status_code in (301, 302, 303, 401, 403, 404)
