"""Handing an order over at pickup: one tap marks it picked up and, for a cash order, records the cash on the books."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from models import Order, db
from utils.production_stages import DONE_STATUSES, apply_stage


def cash_due(order) -> bool:
    return (order.payment_method or '') == 'cash' and (order.payment_status or '') != 'paid'


def is_pickup(order) -> bool:
    return (order.fulfillment_method or 'pickup') != 'shipping'


def ready_for_pickup():
    """Pickup orders that are packed and waiting, oldest first."""
    return (Order.query.filter(or_(Order.status == 'ready', Order.production_stage == 'packaged_ready'))
            .filter(~Order.status.in_(DONE_STATUSES))
            .filter(or_(Order.fulfillment_method == 'pickup', Order.fulfillment_method.is_(None)))
            .order_by(Order.created_at).all())


def find(query):
    """Open pickup orders matching an order number, a name, an email or a phone number."""
    q = (query or '').strip()
    if not q:
        return []
    like = f'%{q}%'
    return (Order.query.filter(~Order.status.in_(DONE_STATUSES))
            .filter(or_(Order.fulfillment_method == 'pickup', Order.fulfillment_method.is_(None)))
            .filter(or_(Order.order_number.ilike(like), Order.first_name.ilike(like), Order.last_name.ilike(like),
                        Order.email.ilike(like), Order.phone.ilike(like)))
            .order_by(Order.created_at.desc()).limit(20).all())


def hand_over(order):
    """Mark an order picked up. Returns (ok, message). A cash order is marked paid at the same moment."""
    if (order.status or '') in DONE_STATUSES:
        return False, f'{order.order_number} was already handed over.'
    if not is_pickup(order):
        return False, f'{order.order_number} is a shipping order, so it is not handed over at pickup.'
    if (order.payment_status or '') not in ('paid',) and not cash_due(order):
        return False, f'{order.order_number} has not been paid yet, so it was not handed over.'
    collected = None
    if cash_due(order):
        order.payment_status = 'paid'
        order.paid_at = datetime.utcnow()
        order.amount_paid = float(order.total or 0)
        collected = float(order.total or 0)
    apply_stage(order, 'picked_up')
    db.session.commit()
    try:
        from utils import ledger
        ledger.sync_all(force=True)
    except Exception:
        pass
    try:
        from utils.customer_emails import notify_in_background
        notify_in_background([order.id], 'picked_up')
    except Exception:
        pass
    if collected is not None:
        return True, f'{order.order_number} handed over. ${collected:,.2f} cash is on your books.'
    return True, f'{order.order_number} handed over.'
