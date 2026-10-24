"""Money events from Stripe and PayPal: refunds (partial too) and payouts to the bank.

Stripe tells us by webhook (charge.refunded, payout.*). PayPal is asked once a night about recent orders, since a
refund there can happen on any day. Every function is safe to run twice with the same data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import current_app

from models import ManualInvoice, Order, Payout, db
from utils import ledger as L


def _utc_naive(unix_seconds):
    if not unix_seconds:
        return datetime.utcnow()
    return datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc).replace(tzinfo=None)


def _apply_refund(row, refunded_cents, when, fully):
    """Raise the recorded refund on an order or invoice. Never lowers it (a refund cannot be un-refunded here)."""
    refunded_cents = int(refunded_cents or 0)
    changed = False
    if refunded_cents > int(row.refunded_cents or 0):
        row.refunded_cents = refunded_cents
        row.refunded_at = when
        changed = True
    if fully and isinstance(row, Order) and not row.is_refunded:
        row.is_refunded = True
        changed = True
    return changed


def apply_stripe_charge_refund(charge, event_time=None):
    """A charge.refunded event: find the order or invoice behind the charge and record how much came back."""
    intent_id = charge.get('payment_intent')
    refunded = int(charge.get('amount_refunded') or 0)
    amount = int(charge.get('amount') or 0)
    if not intent_id or refunded <= 0:
        return 'nothing to record'
    when = _utc_naive(event_time)
    fully = amount > 0 and refunded >= amount
    order = Order.query.filter_by(payment_intent_id=intent_id).first()
    if order is not None:
        changed = _apply_refund(order, refunded, when, fully)
        note = f'Stripe refund of ${refunded / 100:,.2f} recorded'
        if changed and not order.refund_notes:
            order.refund_notes = note
        db.session.commit()
        L.sync_all(force=True)
        return f'order {order.order_number}'
    invoice = (ManualInvoice.query.filter_by(card_paid_intent_id=intent_id).first()
               or ManualInvoice.query.filter_by(payment_intent_id=intent_id).first())
    if invoice is not None:
        _apply_refund(invoice, refunded, when, fully)
        db.session.commit()
        L.sync_all(force=True)
        return f'invoice {invoice.number}'
    current_app.logger.warning('stripe refund for intent %s matches no order or invoice', intent_id)
    return 'no match'


def record_stripe_payout(payout, event_type=None):
    """A payout.* event: keep one row per payout, and put a transfer entry in the ledger once it has been paid."""
    provider_id = payout.get('id')
    if not provider_id:
        return None
    status = payout.get('status') or ('paid' if event_type == 'payout.paid' else 'pending')
    cents = int(payout.get('amount') or 0)
    arrival = _utc_naive(payout.get('arrival_date'))
    row = Payout.query.filter_by(provider_id=provider_id).first()
    if row is None:
        row = Payout(provider='stripe', provider_id=provider_id, amount_cents=cents)
        db.session.add(row)
    row.amount_cents, row.status = cents, status
    row.currency = payout.get('currency') or 'usd'
    row.arrival_date = L.kc_day(arrival)
    db.session.flush()
    current = {k: v for k, v in L._current_sums().items() if k[0] == f'payout:{provider_id}'}
    L.sync_source(f'payout:{provider_id}', {L.PAYOUT: cents} if status == 'paid' else {}, when=arrival, current=current,
                  pay_source='stripe', note=f'Stripe payout {provider_id}')
    db.session.commit()
    return row


# ---- PayPal: ask once a night about recent orders -----------------------------------------------

def _paypal_refunds(order):
    """(total refunded in cents, time of the latest refund) from PayPal's order record, or None if it cannot be read."""
    import requests
    from routes.checkout import _get_paypal_access_token, _paypal_base_url
    app = current_app._get_current_object()
    token = _get_paypal_access_token(app)
    if not token or not order.paypal_order_id:
        return None
    resp = requests.get(f'{_paypal_base_url(app)}/v2/checkout/orders/{order.paypal_order_id}',
                        headers={'Authorization': f'Bearer {token}'}, timeout=10)
    if resp.status_code != 200:
        return None
    total, latest = 0, None
    for unit in resp.json().get('purchase_units') or []:
        for refund in ((unit.get('payments') or {}).get('refunds') or []):
            if (refund.get('status') or '').upper() not in ('COMPLETED', 'PENDING'):
                continue
            total += L.to_cents((refund.get('amount') or {}).get('value'))
            stamp = refund.get('create_time') or refund.get('update_time')
            if stamp:
                try:
                    when = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
                    latest = when if latest is None or when > latest else latest
                except ValueError:
                    pass
    return total, latest


def check_paypal_refunds(limit=40, days=180):
    """Ask PayPal about the least recently checked PayPal orders from the last six months. Returns how many changed."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    orders = (Order.query.filter(Order.payment_method == 'paypal', Order.payment_status.in_(['paid', 'refunded']),
                                 Order.paypal_order_id.isnot(None), Order.created_at >= cutoff)
              .order_by(Order.refund_checked_at.isnot(None), Order.refund_checked_at).limit(limit).all())
    changed = 0
    for order in orders:
        order.refund_checked_at = datetime.utcnow()
        try:
            found = _paypal_refunds(order)
        except Exception as exc:
            current_app.logger.warning('paypal refund lookup failed for %s: %s', order.order_number, exc)
            found = None
        if found and found[0] > 0:
            total, when = found
            fully = total >= L.to_cents(order.total)
            if _apply_refund(order, total, when or datetime.utcnow(), fully):
                changed += 1
    db.session.commit()
    return changed


def fetch_real_fees(limit=40):
    """Ask Stripe and PayPal now for the real fee on card orders that still use an estimate. Returns how many were found."""
    from utils.payment_fees import refresh_processing_fee, true_profit
    orders = (Order.query.filter(Order.payment_status == 'paid', Order.payment_method.in_(['stripe', 'paypal']),
                                 db.or_(Order.processing_fee_is_actual.is_(False), Order.processing_fee_is_actual.is_(None)))
              .order_by(Order.created_at.desc()).limit(limit).all())
    found = 0
    for order in orders:
        order.fee_checked_at = None                      # a person asked, so skip the six hour wait
        try:
            refresh_processing_fee(order, allow_network=True)
            if order.processing_fee_is_actual:
                found += 1
            profit = true_profit(order)
            if profit is not None:
                order.profit = profit
            db.session.commit()
        except Exception:
            db.session.rollback()
    L.sync_all(force=True)
    return found
