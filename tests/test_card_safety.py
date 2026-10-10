"""A charged card (or Apple Pay / Google Pay) must always become an order."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from models import db, Order, PaymentCapture, AdminNotification
from tests.test_checkout import _fill_cart, _cash_payload, TAX_RATE

ONE_ITEM = round(30.00 + round(30.00 * TAX_RATE, 2), 2)
CENTS = int(round(ONE_ITEM * 100))


def _start_card_checkout(client, intent_id='pi_test_1'):
    """Checkout page loads (intent created), then Pay is tapped (/prepare)."""
    fake = SimpleNamespace(id=intent_id, client_secret=f'{intent_id}_secret_x')
    with patch('stripe.PaymentIntent.create', return_value=fake):
        assert client.post('/checkout/create-payment-intent', json={'shipping_method': 'pickup'}).status_code == 200
    payload = _cash_payload(payment_method='stripe', payment_id=None, checkout_token=f'tok-{intent_id}')
    assert client.post('/checkout/prepare', json=payload).get_json()['success'] is True


def _intent(status='succeeded', intent_id='pi_test_1', amount=CENTS):
    return {'id': intent_id, 'status': status, 'amount': amount, 'amount_received': amount}


def _age(app, minutes=5):
    with app.app_context():
        for cap in PaymentCapture.query.all():
            cap.created_at = datetime.utcnow() - timedelta(minutes=minutes)
            cap.checked_at = None  # time has passed since the last status check too
        db.session.commit()


def test_checkout_is_saved_before_the_card_is_charged(client, seed, app):
    _fill_cart(client, seed)
    _start_card_checkout(client)
    with app.app_context():
        cap = PaymentCapture.query.filter_by(provider_ref='pi_test_1').one()
        assert cap.provider == 'stripe'
        assert cap.amount is None  # not paid yet, so never shown as a paid order
        assert 'buyer@example.com' in cap.customer_json
        assert str(seed['tee_id']) in cap.cart_json


def test_card_charged_but_phone_never_finished_order_is_created(client, seed, app, outbox):
    from utils.payment_safety import sweep_unsaved_payments
    _fill_cart(client, seed)
    _start_card_checkout(client)
    _age(app)
    with app.app_context(), patch('stripe.PaymentIntent.retrieve', return_value=_intent()):
        sweep_unsaved_payments()
        order = Order.query.filter_by(payment_intent_id='pi_test_1').one()
        assert order.payment_status == 'paid'
        assert order.amount_paid == ONE_ITEM
        assert order.email == 'buyer@example.com'
        assert order.items.count() == 1
        assert AdminNotification.query.filter(AdminNotification.title.like('%saved automatically%')).count() == 1
    subjects = [m.subject for m in outbox]
    assert any('receipt' in s.lower() for s in subjects)
    assert any(s.startswith('New Order') for s in subjects)
    # If the phone does come back later, it gets the same order.
    with patch('stripe.PaymentIntent.retrieve', return_value=SimpleNamespace(**_intent())):
        body = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_test_1', checkout_token='tok-pi_test_1')).get_json()
    assert body['success'] is True
    with app.app_context():
        assert Order.query.count() == 1


def test_unpaid_card_attempt_never_becomes_an_order(client, seed, app):
    from utils.payment_safety import sweep_unsaved_payments
    _fill_cart(client, seed)
    _start_card_checkout(client)
    _age(app)
    with app.app_context(), patch('stripe.PaymentIntent.retrieve',
                                  return_value=_intent(status='requires_payment_method')):
        sweep_unsaved_payments()
        assert Order.query.count() == 0
        assert AdminNotification.query.filter_by(kind='payment').count() == 0
    _age(app, minutes=60 * 49)
    with app.app_context(), patch('stripe.PaymentIntent.retrieve',
                                  return_value=_intent(status='requires_payment_method')):
        sweep_unsaved_payments()
        assert PaymentCapture.query.one().resolved_at is not None


def _webhook(client, app, intent_id):
    event = {'type': 'payment_intent.succeeded', 'data': {'object': _intent(intent_id=intent_id)}}
    original = app.config.get('STRIPE_WEBHOOK_SECRET')
    app.config['STRIPE_WEBHOOK_SECRET'] = original or 'whsec_test'
    try:
        with patch('stripe.Webhook.construct_event', return_value=event):
            return client.post('/checkout/stripe-webhook', data='{}',
                               headers={'Stripe-Signature': 'x'}).get_json()
    finally:
        app.config['STRIPE_WEBHOOK_SECRET'] = original


def test_stripe_webhook_leaves_a_fresh_checkout_to_the_phone(client, seed, app):
    """Stripe's notice races the phone's own save; it must not make a second order."""
    _fill_cart(client, seed)
    _start_card_checkout(client, intent_id='pi_fresh')
    body = _webhook(client, app, 'pi_fresh')
    assert body.get('pending') is True
    with app.app_context():
        assert Order.query.count() == 0
        assert AdminNotification.query.filter_by(kind='payment').count() == 0
    with patch('stripe.PaymentIntent.retrieve', return_value=SimpleNamespace(**_intent(intent_id='pi_fresh'))):
        done = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_fresh', checkout_token='tok-pi_fresh')).get_json()
    assert done['success'] is True
    with app.app_context():
        assert Order.query.count() == 1


def test_stripe_webhook_creates_the_missing_order_after_the_grace_period(client, seed, app):
    _fill_cart(client, seed)
    _start_card_checkout(client, intent_id='pi_hook')
    _age(app)
    body = _webhook(client, app, 'pi_hook')
    assert body.get('recovered') is True
    with app.app_context():
        assert Order.query.filter_by(payment_intent_id='pi_hook').count() == 1


def test_sweep_skips_a_payment_the_phone_is_saving(client, seed, app):
    from utils.payment_safety import sweep_unsaved_payments, claim_for_checkout
    _fill_cart(client, seed)
    _start_card_checkout(client, intent_id='pi_busy')
    _age(app)
    with app.app_context():
        assert claim_for_checkout('pi_busy') is True  # the phone's save is in progress
        with patch('stripe.PaymentIntent.retrieve', return_value=_intent(intent_id='pi_busy')):
            sweep_unsaved_payments()
        assert Order.query.count() == 0


def test_abandoned_card_checkouts_are_not_rechecked_every_sweep(client, seed, app):
    from utils.payment_safety import sweep_unsaved_payments
    _fill_cart(client, seed)
    _start_card_checkout(client, intent_id='pi_old')
    _age(app, minutes=120)
    with app.app_context(), patch('stripe.PaymentIntent.retrieve',
                                  return_value=_intent(intent_id='pi_old', status='requires_payment_method')) as r:
        sweep_unsaved_payments()
        sweep_unsaved_payments()
        assert r.call_count == 1


def test_card_order_rejected_after_payment_is_saved_instead(client, seed, app):
    """Normal save step fails after the card is charged: save it anyway."""
    _fill_cart(client, seed)
    _start_card_checkout(client, intent_id='pi_late')
    with patch('stripe.PaymentIntent.retrieve',
               return_value=SimpleNamespace(**_intent(intent_id='pi_late', amount=CENTS + 100))):
        body = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_late', checkout_token='tok-pi_late')).get_json()
    assert body['success'] is True
    assert body.get('recovered') is True
    with app.app_context():
        order = Order.query.filter_by(payment_intent_id='pi_late').one()
        assert order.amount_paid == round((CENTS + 100) / 100, 2)
