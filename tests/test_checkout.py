"""Checkout: totals, payment verification, duplicate protection, webhooks.

Stripe is stubbed throughout — no network call and no real charge.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models import db, Order, OrderItem, Product
from routes.checkout import calculate_totals, reprice_cart

TAX_RATE = 0.095
SHIPPING = 11.00


# ── Totals ────────────────────────────────────────────────────────────────────

def test_pickup_totals_have_no_shipping(app, seed):
    cart = [{'product_id': seed['tee_id'], 'quantity': 2, 'unit_price': 30.00}]
    with app.test_request_context():
        totals = calculate_totals(cart, 'pickup')
    assert totals['subtotal'] == 60.00
    assert totals['shipping_cost'] == 0
    assert totals['tax'] == round(60.00 * TAX_RATE, 2)
    assert totals['total'] == round(60.00 + totals['tax'], 2)


def test_shipping_totals_add_flat_rate(app, seed):
    cart = [{'product_id': seed['tee_id'], 'quantity': 1, 'unit_price': 30.00}]
    with app.test_request_context():
        totals = calculate_totals(cart, 'shipping')
    assert totals['shipping_cost'] == SHIPPING
    # Shipping is deliberately not taxed.
    assert totals['tax'] == round(30.00 * TAX_RATE, 2)
    assert totals['total'] == round(30.00 + SHIPPING + totals['tax'], 2)


def test_totals_across_multiple_lines(app, seed):
    cart = [
        {'product_id': seed['tee_id'], 'quantity': 3, 'unit_price': 30.00},
        {'product_id': seed['hoodie_id'], 'quantity': 2, 'unit_price': 45.00},
    ]
    with app.test_request_context():
        totals = calculate_totals(cart, 'pickup')
    assert totals['subtotal'] == 180.00
    assert totals['total'] == round(180.00 + round(180.00 * TAX_RATE, 2), 2)


def test_totals_survive_a_junk_quantity(app, seed):
    """A malformed session must not raise a 500 on the checkout page."""
    cart = [{'product_id': seed['tee_id'], 'quantity': None, 'unit_price': 30.00}]
    with app.test_request_context():
        totals = calculate_totals(cart, 'pickup')
    assert totals['subtotal'] == 0


# ── Repricing ─────────────────────────────────────────────────────────────────

def test_reprice_corrects_a_tampered_session(app, seed):
    cart = [{
        'product_id': seed['tee_id'], 'quantity': 1, 'unit_price': 0.01,
        'size': 'M', 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    }]
    with app.test_request_context():
        corrections = reprice_cart(cart, persist=False)
    assert len(corrections) == 1
    assert cart[0]['unit_price'] == 30.00


def test_reprice_leaves_a_correct_cart_alone(app, seed):
    cart = [{
        'product_id': seed['tee_id'], 'quantity': 1, 'unit_price': 30.00,
        'size': 'M', 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    }]
    with app.test_request_context():
        assert reprice_cart(cart, persist=False) == []


def test_reprice_picks_up_a_price_change(app, seed):
    """An item added before the owner raised the price is corrected, not honoured."""
    cart = [{
        'product_id': seed['tee_id'], 'quantity': 1, 'unit_price': 30.00,
        'size': 'M', 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    }]
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        tee.base_price = 35.00
        db.session.commit()
    with app.test_request_context():
        reprice_cart(cart, persist=False)
    assert cart[0]['unit_price'] == 35.00


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fill_cart(client, seed, qty=1, size='M', *, app=None, allow_cash=False):
    if allow_cash:
        assert app is not None
        _enable_cash_for_group(client, seed, app)
    resp = client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': size, 'color': 'Black',
        'quantity': qty, 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    })
    assert resp.status_code == 200
    return resp


def _enable_cash_for_group(client, seed, app):
    """Cash is only allowed on group orders when the organizer opts in."""
    from models import Collection, db
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.allow_cash_pickup = True
        db.session.commit()
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']


def _cash_payload(**over):
    payload = {
        'payment_method': 'cash',
        'shipping_method': 'pickup',
        'email': 'buyer@example.com',
        'first_name': 'Casey',
        'last_name': 'Customer',
        'phone': '816-555-0100',
        'checkout_token': 'tok-test-0001',
    }
    payload.update(over)
    return payload


def _stripe_intent(amount_cents, status='succeeded', intent_id='pi_test_123'):
    return SimpleNamespace(id=intent_id, amount=amount_cents, status=status)


# ── Cash orders ───────────────────────────────────────────────────────────────

def test_cash_order_is_created_as_pending(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    resp = client.post('/checkout/complete', json=_cash_payload())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True

    with app.app_context():
        order = Order.query.filter_by(order_number=body['order_number']).one()
        assert order.payment_status == 'pending'
        assert order.payment_method == 'cash'
        assert order.paid_at is None
        assert order.total == round(30.00 + round(30.00 * TAX_RATE, 2), 2)


def test_order_totals_match_the_line_items(client, seed, app):
    _fill_cart(client, seed, qty=3, app=app, allow_cash=True)
    body = client.post('/checkout/complete', json=_cash_payload()).get_json()
    with app.app_context():
        order = Order.query.filter_by(order_number=body['order_number']).one()
        items = order.items.all()
        assert sum(i.subtotal for i in items) == order.subtotal
        assert items[0].quantity * items[0].unit_price == items[0].subtotal
        assert order.total == round(order.subtotal + order.tax + order.shipping_cost, 2)


def test_cart_is_cleared_after_a_successful_order(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    client.post('/checkout/complete', json=_cash_payload())
    with client.session_transaction() as sess:
        assert sess['cart'] == []


def test_checkout_rejects_an_empty_cart(client, seed):
    resp = client.post('/checkout/complete', json=_cash_payload())
    assert resp.status_code == 400
    assert resp.get_json()['error_code'] == 'CART_EMPTY'


def test_cash_rejected_without_group_organizer_opt_in(client, seed):
    _fill_cart(client, seed)  # no allow_cash
    resp = client.post('/checkout/complete', json=_cash_payload())
    assert resp.status_code == 400
    assert resp.get_json()['error_code'] == 'CASH_NOT_ALLOWED'


def test_checkout_requires_an_email(client, seed):
    _fill_cart(client, seed)
    resp = client.post('/checkout/complete', json=_cash_payload(email=''))
    assert resp.get_json()['error_code'] == 'EMAIL_REQUIRED'


def test_checkout_requires_a_name(client, seed):
    _fill_cart(client, seed)
    resp = client.post('/checkout/complete', json=_cash_payload(first_name=''))
    assert resp.get_json()['error_code'] == 'NAME_REQUIRED'


def test_shipping_requires_a_full_address(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    resp = client.post('/checkout/complete', json=_cash_payload(
        shipping_method='shipping', shipping_info={'street': '123 Main'},
    ))
    assert resp.get_json()['error_code'] == 'SHIPPING_ADDRESS_REQUIRED'


def test_no_order_is_created_when_validation_fails(client, seed, app):
    _fill_cart(client, seed)
    client.post('/checkout/complete', json=_cash_payload(email=''))
    with app.app_context():
        assert Order.query.count() == 0


# ── Card orders ───────────────────────────────────────────────────────────────

def test_card_order_is_marked_paid(client, seed, app):
    _fill_cart(client, seed)
    expected = round(30.00 + round(30.00 * TAX_RATE, 2), 2)
    with patch('stripe.PaymentIntent.retrieve',
               return_value=_stripe_intent(int(round(expected * 100)))):
        resp = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_test_123',
        ))
    body = resp.get_json()
    assert body['success'] is True
    with app.app_context():
        order = Order.query.filter_by(order_number=body['order_number']).one()
        assert order.payment_status == 'paid'
        assert order.payment_intent_id == 'pi_test_123'
        assert order.paid_at is not None


def test_card_order_rejected_when_stripe_amount_is_lower(client, seed, app):
    """The core price-integrity check: paying less than the cart is refused."""
    _fill_cart(client, seed)
    with patch('stripe.PaymentIntent.retrieve', return_value=_stripe_intent(1)):
        resp = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_test_low',
        ))
    assert resp.get_json()['error_code'] == 'PAYMENT_AMOUNT_MISMATCH'
    with app.app_context():
        assert Order.query.count() == 0


def test_card_order_rejected_when_payment_not_complete(client, seed, app):
    _fill_cart(client, seed)
    expected = round(30.00 + round(30.00 * TAX_RATE, 2), 2)
    with patch('stripe.PaymentIntent.retrieve', return_value=_stripe_intent(
            int(round(expected * 100)), status='requires_payment_method')):
        resp = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_test_fail',
        ))
    assert resp.get_json()['error_code'] == 'PAYMENT_NOT_COMPLETE'
    with app.app_context():
        assert Order.query.count() == 0


def test_declined_payment_creates_no_order(client, seed, app):
    _fill_cart(client, seed)
    with patch('stripe.PaymentIntent.retrieve', side_effect=Exception('card_declined')):
        resp = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_declined',
        ))
    assert resp.get_json()['error_code'] == 'PAYMENT_LOOKUP_FAILED'
    with app.app_context():
        assert Order.query.count() == 0


def test_stripe_method_without_payment_id_is_refused(client, seed):
    _fill_cart(client, seed)
    resp = client.post('/checkout/complete', json=_cash_payload(
        payment_method='stripe', payment_id=None,
    ))
    assert resp.get_json()['error_code'] == 'PAYMENT_ID_REQUIRED'


def test_unknown_payment_method_is_refused(client, seed):
    _fill_cart(client, seed)
    resp = client.post('/checkout/complete', json=_cash_payload(payment_method='bitcoin'))
    assert resp.get_json()['error_code'] == 'PAYMENT_METHOD_INVALID'


# ── Duplicate submits ─────────────────────────────────────────────────────────

def test_repeat_submit_returns_the_same_order(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    first = client.post('/checkout/complete', json=_cash_payload()).get_json()

    _fill_cart(client, seed, app=app, allow_cash=True)
    second = client.post('/checkout/complete', json=_cash_payload()).get_json()

    assert second['success'] is True
    assert second['order_number'] == first['order_number']
    assert second.get('replayed') is True
    with app.app_context():
        assert Order.query.count() == 1


def test_two_different_tokens_create_two_orders(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    client.post('/checkout/complete', json=_cash_payload(checkout_token='tok-a'))
    _fill_cart(client, seed, app=app, allow_cash=True)
    client.post('/checkout/complete', json=_cash_payload(checkout_token='tok-b'))
    with app.app_context():
        assert Order.query.count() == 2


def test_checkout_token_is_unique_in_the_database(client, seed, app):
    """The constraint behind the duplicate guard actually exists."""
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        db.session.add(Order(
            order_number='DUP-1', email='a@example.com',
            subtotal=1.0, total=1.0, checkout_token='same-token',
        ))
        db.session.commit()
        db.session.add(Order(
            order_number='DUP-2', email='b@example.com',
            subtotal=1.0, total=1.0, checkout_token='same-token',
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_many_null_checkout_tokens_are_allowed(app, seed):
    """Admin-created orders have no token; the unique constraint must permit that."""
    with app.app_context():
        for n in range(3):
            db.session.add(Order(
                order_number=f'NULLTOK-{n}', email='a@example.com',
                subtotal=1.0, total=1.0, checkout_token=None,
            ))
        db.session.commit()
        assert Order.query.filter_by(checkout_token=None).count() == 3


# ── Confirmation page access ──────────────────────────────────────────────────

def test_buyer_can_see_their_confirmation(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    body = client.post('/checkout/complete', json=_cash_payload()).get_json()
    resp = client.get(f"/checkout/confirmation/{body['order_number']}")
    assert resp.status_code == 200


def test_a_stranger_cannot_see_someone_elses_confirmation(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    body = client.post('/checkout/complete', json=_cash_payload()).get_json()
    order_number = body['order_number']

    with app.test_client() as snooper:
        resp = snooper.get(f'/checkout/confirmation/{order_number}')
        assert resp.status_code == 404


def test_confirmation_for_an_unknown_order_is_404(client, seed):
    assert client.get('/checkout/confirmation/PMKC-DOES-NOT-EXIST').status_code == 404


# ── Webhook ───────────────────────────────────────────────────────────────────

def _webhook(client, event):
    return client.post(
        '/checkout/stripe-webhook',
        data=json.dumps(event),
        content_type='application/json',
        headers={'Stripe-Signature': 'test-signature'},
    )


def test_webhook_rejects_a_bad_signature(client, seed):
    import stripe as stripe_mod
    with patch('stripe.Webhook.construct_event',
               side_effect=stripe_mod.error.SignatureVerificationError('bad', 'sig')):
        resp = _webhook(client, {'type': 'payment_intent.succeeded'})
    assert resp.status_code == 400


def test_webhook_rejects_a_malformed_payload(client, seed):
    with patch('stripe.Webhook.construct_event', side_effect=ValueError('nope')):
        resp = _webhook(client, {'type': 'payment_intent.succeeded'})
    assert resp.status_code == 400


def test_webhook_marks_a_pending_order_paid(client, seed, app):
    with app.app_context():
        order = Order(
            order_number='WEBHOOK-1', email='a@example.com', subtotal=10.0,
            total=10.0, payment_method='stripe', payment_status='pending',
            status='new', payment_intent_id='pi_hook_1',
        )
        db.session.add(order)
        db.session.commit()

    event = {'type': 'payment_intent.succeeded',
             'data': {'object': {'id': 'pi_hook_1', 'amount': 1000}}}
    with patch('stripe.Webhook.construct_event', return_value=event):
        resp = _webhook(client, event)
    assert resp.status_code == 200

    with app.app_context():
        order = Order.query.filter_by(order_number='WEBHOOK-1').one()
        assert order.payment_status == 'paid'
        assert order.paid_at is not None


def test_webhook_redelivery_is_idempotent(client, seed, app):
    """Stripe retries webhooks; a second delivery must not double anything."""
    with app.app_context():
        db.session.add(Order(
            order_number='WEBHOOK-2', email='a@example.com', subtotal=10.0,
            total=10.0, payment_method='stripe', payment_status='pending',
            status='new', payment_intent_id='pi_hook_2',
        ))
        db.session.commit()

    event = {'type': 'payment_intent.succeeded',
             'data': {'object': {'id': 'pi_hook_2', 'amount': 1000}}}
    with patch('stripe.Webhook.construct_event', return_value=event):
        _webhook(client, event)
        with app.app_context():
            first_paid_at = Order.query.filter_by(order_number='WEBHOOK-2').one().paid_at
        _webhook(client, event)

    with app.app_context():
        order = Order.query.filter_by(order_number='WEBHOOK-2').one()
        assert order.paid_at == first_paid_at
        assert Order.query.filter_by(order_number='WEBHOOK-2').count() == 1


def test_webhook_reports_an_orphaned_payment(client, seed):
    """A payment with no matching order is flagged rather than silently dropped."""
    event = {'type': 'payment_intent.succeeded',
             'data': {'object': {'id': 'pi_orphan', 'amount': 5000}}}
    with patch('stripe.Webhook.construct_event', return_value=event):
        resp = _webhook(client, event)
    assert resp.status_code == 200
    assert resp.get_json()['orphaned'] is True


def test_webhook_marks_a_failed_payment(client, seed, app):
    with app.app_context():
        db.session.add(Order(
            order_number='WEBHOOK-3', email='a@example.com', subtotal=10.0,
            total=10.0, payment_method='stripe', payment_status='pending',
            status='new', payment_intent_id='pi_hook_3',
        ))
        db.session.commit()

    event = {'type': 'payment_intent.payment_failed',
             'data': {'object': {'id': 'pi_hook_3'}}}
    with patch('stripe.Webhook.construct_event', return_value=event):
        _webhook(client, event)

    with app.app_context():
        assert Order.query.filter_by(order_number='WEBHOOK-3').one().payment_status == 'failed'


def test_webhook_ignores_unrelated_events(client, seed):
    event = {'type': 'customer.created', 'data': {'object': {'id': 'cus_1'}}}
    with patch('stripe.Webhook.construct_event', return_value=event):
        resp = _webhook(client, event)
    assert resp.get_json()['ignored'] == 'customer.created'
