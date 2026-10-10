"""A captured PayPal payment must always become an order or reach the admin."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from models import db, Order, PaymentCapture, AdminNotification
from tests.test_checkout import _fill_cart, _cash_payload, TAX_RATE

ONE_ITEM = round(30.00 + round(30.00 * TAX_RATE, 2), 2)


def _order_json(amount, order_id='EC-1', name=('Meghan', 'Bogert'), email='megs@example.com'):
    return {
        'id': order_id,
        'status': 'COMPLETED',
        'payer': {'name': {'given_name': name[0], 'surname': name[1]}, 'email_address': email},
        'purchase_units': [{
            'shipping': {'name': {'full_name': ' '.join(name)}, 'address': {
                'address_line_1': '1 Main St', 'admin_area_2': 'Kearney',
                'admin_area_1': 'MO', 'postal_code': '64060'}},
            'payments': {'captures': [{'status': 'COMPLETED', 'amount': {'value': f'{amount:.2f}'}}]},
        }],
    }


def _capture(client, order_id='EC-1', amount=ONE_ITEM, **extra):
    body = dict(_cash_payload(payment_method='paypal', payment_id=order_id), order_id=order_id)
    body.update(extra)
    with patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
         patch('requests.post') as post:
        post.return_value = SimpleNamespace(status_code=200, json=lambda: _order_json(amount, order_id))
        return client.post('/checkout/paypal/capture-order', json=body)


def _forget_session_capture(client):
    with client.session_transaction() as sess:
        sess.pop('paypal_captured_amounts', None)


def test_capture_is_saved_to_the_database_with_cart_and_customer(client, seed, app):
    _fill_cart(client, seed)
    assert _capture(client).get_json()['success'] is True
    with app.app_context():
        cap = PaymentCapture.query.filter_by(provider_ref='EC-1').one()
        assert cap.amount == ONE_ITEM
        assert cap.payer_email == 'megs@example.com'
        assert '"email": "buyer@example.com"' in cap.customer_json
        assert str(seed['tee_id']) in cap.cart_json


def test_order_saves_even_when_the_session_lost_the_capture(client, seed, app):
    _fill_cart(client, seed)
    _capture(client)
    _forget_session_capture(client)  # e.g. cookie too big / dropped by the browser
    body = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1')).get_json()
    assert body['success'] is True
    with app.app_context():
        order = Order.query.filter_by(order_number=body['order_number']).one()
        assert order.payment_status == 'paid'
        assert PaymentCapture.query.filter_by(provider_ref='EC-1').one().order_id == order.id


def test_order_saves_by_asking_paypal_when_nothing_was_recorded(client, seed, app):
    _fill_cart(client, seed)
    with patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
         patch('requests.get') as get:
        get.return_value = SimpleNamespace(status_code=200, json=lambda: _order_json(ONE_ITEM, 'EC-API'))
        body = client.post('/checkout/complete', json=_cash_payload(
            payment_method='paypal', payment_id='EC-API')).get_json()
    assert body['success'] is True


def test_same_paypal_payment_never_makes_two_orders(client, seed, app):
    _fill_cart(client, seed)
    _capture(client)
    first = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1')).get_json()
    second = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1', checkout_token='another')).get_json()
    assert second['order_number'] == first['order_number']
    with app.app_context():
        assert Order.query.count() == 1


def test_order_saves_from_the_saved_cart_if_the_browser_cart_is_gone(client, seed, app):
    _fill_cart(client, seed)
    _capture(client)
    with client.session_transaction() as sess:
        sess['cart'] = []
        sess.pop('paypal_captured_amounts', None)
    body = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1')).get_json()
    assert body['success'] is True


def test_paid_but_unsaved_order_alerts_admin_and_tells_customer(client, seed, app, outbox):
    _fill_cart(client, seed)
    _capture(client)
    body = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1', first_name='')).get_json()
    assert body['success'] is False
    assert body['payment_received'] is True
    assert 'Please do not pay again' in body['error']
    with app.app_context():
        note = AdminNotification.query.filter_by(kind='payment').one()
        assert 'did not save' in note.title
        assert PaymentCapture.query.one().alert_sent_at is not None
    assert any('Paid order needs attention' in m.subject for m in outbox)
    # A retry that fails again does not send a second alert.
    client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1', first_name=''))
    with app.app_context():
        assert AdminNotification.query.filter_by(kind='payment').count() == 1


def test_sweep_alerts_on_payments_left_without_an_order(client, seed, app):
    from utils.payment_safety import sweep_unsaved_payments
    _fill_cart(client, seed)
    _capture(client)
    with app.app_context():
        cap = PaymentCapture.query.one()
        cap.created_at = datetime.utcnow() - timedelta(minutes=30)
        db.session.commit()
        assert sweep_unsaved_payments() == 1
        assert sweep_unsaved_payments() == 0


def test_admin_can_look_up_a_payment_and_create_the_order(admin_client, app, seed):
    with patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
         patch('requests.get') as get:
        def fake_get(url, **kw):
            if '/v2/checkout/orders/TXN-1' in url:
                return SimpleNamespace(status_code=404, json=lambda: {}, text='')
            if '/v2/payments/captures/TXN-1' in url:
                return SimpleNamespace(status_code=200, json=lambda: {
                    'supplementary_data': {'related_ids': {'order_id': 'EC-LOST'}}})
            return SimpleNamespace(status_code=200, json=lambda: _order_json(ONE_ITEM, 'EC-LOST'))
        get.side_effect = fake_get
        admin_client.post('/admin/orders/unsaved-payments/lookup', data={'paypal_ref': 'TXN-1'})

    with app.app_context():
        cap = PaymentCapture.query.filter_by(provider_ref='EC-LOST').one()
        cap_id = cap.id
        from models import Product
        style = db.session.get(Product, seed['tee_id']).style_number
    page = admin_client.get('/admin/orders/unsaved-payments').get_data(as_text=True)
    assert 'Meghan Bogert' in page

    admin_client.post(f'/admin/orders/unsaved-payments/{cap_id}/add-item', data={
        'style_number': style, 'color': 'Black', 'size': 'M', 'quantity': '1', 'unit_price': '30.00',
    })
    resp = admin_client.post(f'/admin/orders/unsaved-payments/{cap_id}/create', data={
        'first_name': 'Meghan', 'last_name': 'Bogert', 'email': 'megs@example.com',
        'fulfillment': 'pickup',
    })
    assert resp.status_code in (301, 302)
    with app.app_context():
        order = Order.query.filter_by(paypal_order_id='EC-LOST').one()
        assert order.payment_status == 'paid'
        assert order.full_name == 'Meghan Bogert'
        assert order.items.count() == 1
        assert PaymentCapture.query.filter_by(provider_ref='EC-LOST').one().order_id == order.id


def test_page_shows_cart_previews_saved_before_a_guest_payment(admin_client, app):
    import os, time
    from pathlib import Path
    with app.app_context():
        cap = PaymentCapture(provider='paypal', provider_ref='EC-GUEST', amount=ONE_ITEM,
                             payer_name='Guest Buyer', created_at=datetime.utcnow())
        db.session.add(cap)
        db.session.commit()
        proofs = Path(app.root_path) / 'static' / 'uploads' / 'proofs'
    proofs.mkdir(parents=True, exist_ok=True)
    name = f'proof_front_{int(time.time()) - 600}.png'
    path = proofs / name
    path.write_bytes(b'\x89PNG\r\n')
    os.utime(path, (time.time() - 600, time.time() - 600))
    try:
        page = admin_client.get('/admin/orders/unsaved-payments').get_data(as_text=True)
        assert 'Shopping activity in the 2 hours before this payment' in page
        assert name in page
    finally:
        path.unlink()


def test_admin_can_copy_a_sibling_order_to_rebuild_a_lost_cart(admin_client, client, app, seed):
    # A normal paid order to copy from.
    _fill_cart(client, seed)
    _capture(client, order_id='EC-SIB')
    sib = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-SIB')).get_json()
    assert sib['success'] is True
    with app.app_context():
        cap = PaymentCapture(provider='paypal', provider_ref='EC-LOST2', amount=ONE_ITEM,
                             payer_name='Meghan Bogert', payer_email='megs@example.com',
                             created_at=datetime.utcnow())
        db.session.add(cap)
        db.session.commit()
        cap_id = cap.id
        src = Order.query.filter_by(order_number=sib['order_number']).one()
        src_item = src.items.first()
    admin_client.post(f'/admin/orders/unsaved-payments/{cap_id}/copy-from-order',
                      data={'order_number': sib['order_number']})
    admin_client.post(f'/admin/orders/unsaved-payments/{cap_id}/create',
                      data={'first_name': 'Meghan', 'last_name': 'Bogert',
                            'email': 'megs@example.com', 'fulfillment': 'pickup'})
    with app.app_context():
        order = Order.query.filter_by(paypal_order_id='EC-LOST2').one()
        item = order.items.first()
        src_item = db.session.merge(src_item)
        assert (item.product_id, item.size, item.color, item.design_id, item.placement) == \
               (src_item.product_id, src_item.size, src_item.color, src_item.design_id, src_item.placement)
        assert order.total == src.total
