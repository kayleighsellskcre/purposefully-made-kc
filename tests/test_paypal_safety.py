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


def test_paypal_payment_creates_the_order_in_the_same_step(client, seed, app, outbox):
    """Meghan's case: the phone stops right after paying. The order must exist anyway."""
    _fill_cart(client, seed)
    body = _capture(client).get_json()
    assert body['success'] is True and body['order_number']
    with app.app_context():
        order = Order.query.filter_by(paypal_order_id='EC-1').one()
        assert order.payment_status == 'paid'
        assert order.email == 'buyer@example.com'
        assert order.items.count() == 1
    # Receipt to the customer and the New Order email to the shop.
    subjects = [m.subject for m in outbox]
    assert any('receipt' in s.lower() for s in subjects)
    assert any(s.startswith('New Order') for s in subjects)
    # The phone's own save request (if it ever arrives) just returns the same order.
    again = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1')).get_json()
    assert again['order_number'] == body['order_number']
    with app.app_context():
        assert Order.query.count() == 1


def test_sweep_creates_the_order_from_paypal_payer_details(client, seed, app, outbox):
    """Even if the capture arrived with no checkout form details at all."""
    from utils.payment_safety import sweep_unsaved_payments
    _fill_cart(client, seed)
    with patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
         patch('requests.post') as post:
        post.return_value = SimpleNamespace(status_code=200, json=lambda: _order_json(ONE_ITEM, 'EC-BARE'))
        assert client.post('/checkout/paypal/capture-order', json={'order_id': 'EC-BARE'}).get_json()['success']
    with app.app_context():
        assert Order.query.count() == 0
        cap = PaymentCapture.query.one()
        cap.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()
        sweep_unsaved_payments()
        order = Order.query.filter_by(paypal_order_id='EC-BARE').one()
        assert order.full_name == 'Meghan Bogert'
        assert order.email == 'megs@example.com'
        assert AdminNotification.query.filter(AdminNotification.title.like('%saved automatically%')).count() == 1
        assert sweep_unsaved_payments() == 0


def test_admin_is_alerted_only_when_an_order_cannot_be_built(client, seed, app, outbox):
    from utils.payment_safety import sweep_unsaved_payments
    with app.app_context():
        cap = PaymentCapture(provider='paypal', provider_ref='EC-NOCART', amount=ONE_ITEM,
                             payer_name='Pat Payer', payer_email='pat@example.com',
                             created_at=datetime.utcnow() - timedelta(minutes=5))
        db.session.add(cap)
        db.session.commit()
        sweep_unsaved_payments()
        note = AdminNotification.query.filter_by(kind='payment').one()
        assert 'did not save' in note.title
        assert sweep_unsaved_payments() == 0
    assert any('Paid order needs attention' in m.subject for m in outbox)


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


def _create_paypal_order(client, order_id='EC-APPR'):
    body = _cash_payload(payment_method='paypal', payment_id=None)
    with patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
         patch('requests.post') as post:
        post.return_value = SimpleNamespace(status_code=201, json=lambda: {'id': order_id})
        assert client.post('/checkout/paypal/create-order', json=body).get_json()['id'] == order_id


def test_paypal_checkout_is_saved_before_the_customer_approves(client, seed, app):
    _fill_cart(client, seed)
    _create_paypal_order(client)
    with app.app_context():
        cap = PaymentCapture.query.filter_by(provider_ref='EC-APPR').one()
        assert cap.amount is None
        assert 'buyer@example.com' in cap.customer_json


def test_approved_but_uncollected_paypal_payment_is_never_collected_automatically(
        client, admin_client, seed, app, outbox):
    """The customer tapped Pay Now, then their phone never came back. They may have
    paid again on a second try, so the site must NOT collect it on its own: it
    alerts the admin, who can collect it with one click."""
    from utils.payment_safety import sweep_unsaved_payments
    _fill_cart(client, seed)
    _create_paypal_order(client)
    with app.app_context():
        cap = PaymentCapture.query.one()
        cap.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()
        cap_id = cap.id
    approved = dict(_order_json(ONE_ITEM, 'EC-APPR'), status='APPROVED')
    approved['purchase_units'][0]['payments'] = {}
    with app.app_context(), \
         patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
         patch('requests.get', return_value=SimpleNamespace(status_code=200, json=lambda: approved)), \
         patch('requests.post') as post:
        sweep_unsaved_payments()
        sweep_unsaved_payments()
        assert not post.called  # no money collected by the site
        assert Order.query.count() == 0
        cap = db.session.get(PaymentCapture, cap_id)
        assert cap.awaiting_collection is True
        assert AdminNotification.query.filter(AdminNotification.title.like('%not collected%')).count() == 1
    assert any('approved but not collected' in m.subject for m in outbox)
    page = admin_client.get('/admin/orders/unsaved-payments').get_data(as_text=True)
    assert 'Collect payment and create order' in page

    with patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
         patch('requests.post', return_value=SimpleNamespace(
             status_code=201, json=lambda: _order_json(ONE_ITEM, 'EC-APPR'))) as post:
        admin_client.post(f'/admin/orders/unsaved-payments/{cap_id}/collect')
    assert post.call_args.kwargs['headers']['PayPal-Request-Id'] == 'pmkc-collect-EC-APPR'
    with app.app_context():
        order = Order.query.filter_by(paypal_order_id='EC-APPR').one()
        assert order.payment_status == 'paid'
        assert order.email == 'buyer@example.com'


def test_never_approved_paypal_checkout_is_left_alone(client, seed, app):
    from utils.payment_safety import sweep_unsaved_payments
    _fill_cart(client, seed)
    _create_paypal_order(client, 'EC-QUIT')
    with app.app_context():
        cap = PaymentCapture.query.one()
        cap.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()
        created = dict(_order_json(ONE_ITEM, 'EC-QUIT'), status='CREATED')
        created['purchase_units'][0]['payments'] = {}
        with patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
             patch('requests.get', return_value=SimpleNamespace(status_code=200, json=lambda: created)), \
             patch('requests.post') as post:
            sweep_unsaved_payments()
        assert not post.called
        assert Order.query.count() == 0
        assert AdminNotification.query.filter_by(kind='payment').count() == 0


# ── Audit fixes ──────────────────────────────────────────────────────────────

def test_database_refuses_two_orders_for_one_payment(app, seed):
    import pytest
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        for _ in range(2):
            db.session.add(Order(user_id=seed['customer_id'], first_name='A', last_name='B',
                                 email='a@example.com', subtotal=1, total=1,
                                 payment_method='paypal', paypal_order_id='EC-DUP'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_guest_who_paid_still_sees_their_receipt_on_a_retry(client, seed, app):
    """A lost response + retry (or the phone resuming after the sweep built the
    order) must land on the receipt, not a 404."""
    _fill_cart(client, seed)
    body = _capture(client).get_json()
    with client.session_transaction() as sess:
        sess.pop('checkout_success_order', None)
        sess.pop('checkout_success_token', None)
    again = client.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1')).get_json()
    assert again['order_number'] == body['order_number']
    assert client.get(again['redirect_url']).status_code == 200


def test_someone_else_cannot_open_a_receipt_with_just_the_payment_id(client, seed, app):
    _fill_cart(client, seed)
    body = _capture(client).get_json()
    other = app.test_client()
    resp = other.post('/checkout/complete', json=_cash_payload(
        payment_method='paypal', payment_id='EC-1', checkout_token='not-theirs')).get_json()
    assert resp['order_number'] == body['order_number']
    assert other.get(resp['redirect_url']).status_code == 404


def test_paypal_order_uses_the_cart_paypal_priced_if_the_cart_grew(client, seed, app):
    _fill_cart(client, seed)
    _create_paypal_order(client, 'EC-PRICED')          # PayPal priced one item
    _fill_cart(client, seed)                           # another item added after
    resp = _capture(client, order_id='EC-PRICED').get_json()
    assert resp['success'] is True
    with app.app_context():
        order = Order.query.filter_by(paypal_order_id='EC-PRICED').one()
        assert order.payment_status == 'paid'
        assert abs(order.total - ONE_ITEM) < 0.01


def test_admin_lookup_never_wipes_saved_checkout_details(admin_client, client, seed, app):
    from utils.payment_safety import record_paypal_capture
    _fill_cart(client, seed)
    _create_paypal_order(client, 'EC-KEEP')
    with app.app_context():
        record_paypal_capture('EC-KEEP', ONE_ITEM, order_json=_order_json(ONE_ITEM, 'EC-KEEP'),
                              customer={'first_name': 'Meghan', 'email': 'other@example.com',
                                        'shipping_method': 'pickup'})
        cap = PaymentCapture.query.filter_by(provider_ref='EC-KEEP').one()
        assert '816-555-0100' in cap.customer_json        # phone typed at checkout kept
        assert 'buyer@example.com' in cap.customer_json  # original email kept


def test_admin_page_escapes_shopper_text(admin_client, app, seed):
    from models import User
    with app.app_context():
        user = db.session.get(User, seed['customer_id'])
        user.cart_json = '[{"product_id": 1, "color": "<img src=x onerror=alert(1)>", "size": "M", "quantity": 1}]'
        user.cart_updated_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.add(PaymentCapture(provider='paypal', provider_ref='EC-XSS', amount=ONE_ITEM,
                                      payer_name='X Y', created_at=datetime.utcnow()))
        db.session.commit()
    page = admin_client.get('/admin/orders/unsaved-payments').get_data(as_text=True)
    assert '<img src=x onerror' not in page
    assert '&lt;img src=x onerror' in page
