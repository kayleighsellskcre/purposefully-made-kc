"""Payment processing fees (Stripe / PayPal) and true profit per order.

True profit = what the customer paid
              - sales tax collected (owed to the state, not income)
              - processing fee (Stripe or PayPal's cut)
              - cost of goods (blanks + transfers)

The fee is pulled from Stripe or PayPal once and stored as actual. Until it can
be fetched, a standard-rate estimate is used and labeled as an estimate.
"""
from __future__ import annotations

from flask import current_app

# Standard US online rates, used only until the real fee can be fetched.
FEE_ESTIMATE_RATES = {
    'stripe': (0.029, 0.30),
    'paypal': (0.0349, 0.49),
}

PROCESSOR_LABELS = {
    'stripe': 'Stripe',
    'paypal': 'PayPal',
    'cash': 'Cash',
}


def _num(value, default=0.0):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def processor_label(order):
    method = (getattr(order, 'payment_method', None) or '').strip().lower()
    return PROCESSOR_LABELS.get(method, method.title() if method else 'Payment')


def charged_amount(order):
    """What actually went through the processor (amount_paid when set, else total)."""
    paid = getattr(order, 'amount_paid', None)
    if paid is not None:
        return _num(paid)
    return _num(getattr(order, 'total', None))


def estimate_fee(order):
    method = (getattr(order, 'payment_method', None) or '').strip().lower()
    rates = FEE_ESTIMATE_RATES.get(method)
    amount = charged_amount(order)
    if not rates or amount <= 0:
        return 0.0
    pct, fixed = rates
    return round(amount * pct + fixed, 2)


def _stripe_fee(order):
    intent_id = getattr(order, 'payment_intent_id', None)
    if not intent_id or not current_app.config.get('STRIPE_SECRET_KEY'):
        return None
    import stripe
    intent = stripe.PaymentIntent.retrieve(
        intent_id, expand=['latest_charge.balance_transaction'],
    )
    charge = getattr(intent, 'latest_charge', None)
    txn = getattr(charge, 'balance_transaction', None) if charge else None
    fee = getattr(txn, 'fee', None) if txn else None
    if fee is None:
        return None
    return round(int(fee) / 100.0, 2)


def _paypal_fee(order):
    paypal_id = getattr(order, 'paypal_order_id', None)
    if not paypal_id:
        return None
    import requests
    from routes.checkout import _get_paypal_access_token, _paypal_base_url
    app = current_app._get_current_object()
    token = _get_paypal_access_token(app)
    if not token:
        return None
    resp = requests.get(
        f'{_paypal_base_url(app)}/v2/checkout/orders/{paypal_id}',
        headers={'Authorization': f'Bearer {token}'},
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    total = 0.0
    found = False
    for unit in resp.json().get('purchase_units') or []:
        for capture in ((unit.get('payments') or {}).get('captures') or []):
            breakdown = capture.get('seller_receivable_breakdown') or {}
            fee = (breakdown.get('paypal_fee') or {}).get('value')
            if fee is not None:
                total += _num(fee)
                found = True
    return round(total, 2) if found else None


def fetch_actual_fee(order):
    """Ask Stripe or PayPal what they actually took. None when unavailable."""
    method = (getattr(order, 'payment_method', None) or '').strip().lower()
    try:
        if method == 'stripe':
            return _stripe_fee(order)
        if method == 'paypal':
            return _paypal_fee(order)
    except Exception as exc:  # network / API problems never break the admin page
        current_app.logger.warning('processing fee lookup failed for order %s: %s',
                                   getattr(order, 'id', None), exc)
    return None


def refresh_processing_fee(order, allow_network=True):
    """Fill order.processing_fee. Returns True when anything changed."""
    if getattr(order, 'processing_fee_is_actual', False):
        return False
    method = (getattr(order, 'payment_method', None) or '').strip().lower()
    if method not in FEE_ESTIMATE_RATES or charged_amount(order) <= 0:
        # Cash, family at-cost, admin-entered: nothing is taken out.
        changed = getattr(order, 'processing_fee', None) != 0.0
        order.processing_fee = 0.0
        order.processing_fee_is_actual = True
        return changed
    if allow_network:
        actual = fetch_actual_fee(order)
        if actual is not None:
            order.processing_fee = actual
            order.processing_fee_is_actual = True
            return True
    estimate = estimate_fee(order)
    if getattr(order, 'processing_fee', None) != estimate:
        order.processing_fee = estimate
        return True
    return False


def processing_fee_for(order):
    fee = getattr(order, 'processing_fee', None)
    return _num(fee) if fee is not None else estimate_fee(order)


def true_profit(order, cogs=None):
    """Customer paid - sales tax - processing fee - cost of goods."""
    if cogs is None:
        cogs = getattr(order, 'cost_of_goods', None)
    total = getattr(order, 'total', None)
    if cogs is None or total is None:
        return None
    return round(
        _num(total) - _num(getattr(order, 'tax', None)) - processing_fee_for(order) - _num(cogs),
        2,
    )


def profit_margin_pct(order, profit=None):
    """Profit as a share of what the shop actually earned (total minus tax)."""
    if profit is None:
        profit = true_profit(order)
    earned = _num(getattr(order, 'total', None)) - _num(getattr(order, 'tax', None))
    if profit is None or earned <= 0:
        return None
    return round(profit / earned * 100.0, 1)
