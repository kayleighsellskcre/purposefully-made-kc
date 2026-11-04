"""Store credit for people whose shared designs get orders.

A creator earns a small percent of the item price (never tax or shipping) on every order that came through their
link, once it is picked up or shipped. It is a ledger of CreditEntry rows: earned, taken back if the order is
refunded, and spent at checkout. Credit never expires. People who order through their own link earn nothing.
"""
from __future__ import annotations

from sqlalchemy import func

from models import CreditEntry, OrderItem, SharedDesign, db
from utils.site_settings import get_setting

RATE_KEY = 'creator_credit_percent'
DEFAULT_RATE = 2.0


def rate_percent():
    try:
        return max(0.0, min(float(get_setting(RATE_KEY, str(DEFAULT_RATE))), 50.0))
    except (TypeError, ValueError):
        return DEFAULT_RATE


def _sum(*conditions):
    total = db.session.query(func.coalesce(func.sum(CreditEntry.amount), 0.0)).filter(*conditions).scalar()
    return round(float(total or 0.0), 2)


def balance(user_id):
    return _sum(CreditEntry.user_id == user_id)


def first_earned(user_id):
    """The first credit this person earned from a shared design (for the one-time welcome), or None."""
    return (CreditEntry.query.filter_by(user_id=user_id, kind='earned')
            .order_by(CreditEntry.created_at, CreditEntry.id).first())


def earned_by_share(share_id):
    return _sum(CreditEntry.shared_design_id == share_id, CreditEntry.kind.in_(['earned', 'reversed']))


def _own_order(order, share):
    if share.user_id and order.user_id == share.user_id:
        return True
    from models import User
    owner = db.session.get(User, share.user_id) if share.user_id else None
    email = (order.email or '').strip().lower()
    return bool(email and owner and (owner.email or '').strip().lower() == email)


def credit_for(user_id, merchandise_subtotal):
    """Store credit to use on an order of this much merchandise: the whole balance, but always leaving $1 to pay.

    Zero when the customer turned automatic use off.
    """
    from models import User
    user = db.session.get(User, user_id) if user_id else None
    if user is None or user.use_credit is False:
        return 0.0
    return round(max(0.0, min(balance(user_id), float(merchandise_subtotal or 0.0) - 1.0)), 2)


def spend_for_order(order):
    """Write down the credit this order used (the amount is already on order.credit_applied). Safe to call twice."""
    amount = round(float(getattr(order, 'credit_applied', 0.0) or 0.0), 2)
    if amount <= 0 or not order.user_id:
        return 0.0
    if CreditEntry.query.filter_by(user_id=order.user_id, kind='spent', order_id=order.id).first():
        return 0.0
    db.session.add(CreditEntry(user_id=order.user_id, amount=-amount, kind='spent', order_id=order.id,
                               note=f'Used on order {order.order_number}'))
    db.session.flush()
    return amount


def earn_for_order(order):
    """Credit each creator for this order's shared-design items. Safe to call twice. Returns the number of credits added."""
    if order is None or order.payment_status != 'paid' or order.is_refunded:
        return 0
    rate = rate_percent()
    if rate <= 0:
        return 0
    by_share = {}
    for item in OrderItem.query.filter_by(order_id=order.id).filter(OrderItem.shared_design_id.isnot(None)).all():
        by_share[item.shared_design_id] = by_share.get(item.shared_design_id, 0.0) + float(item.subtotal or 0.0)
    added = 0
    for share_id, subtotal in by_share.items():
        share = db.session.get(SharedDesign, share_id)
        if share is None or not share.user_id or _own_order(order, share):
            continue
        if CreditEntry.query.filter_by(user_id=share.user_id, kind='earned', order_id=order.id, shared_design_id=share_id).first():
            continue
        amount = round(subtotal * rate / 100.0, 2)
        if amount <= 0:
            continue
        db.session.add(CreditEntry(user_id=share.user_id, amount=amount, kind='earned', order_id=order.id,
                                   shared_design_id=share_id, note=f'{rate:g}% of order {order.order_number}'))
        added += 1
    if added:
        db.session.flush()
    return added


def reverse_for_order(order):
    """Take back what this order earned (it was refunded). Safe to call twice."""
    taken = 0
    spent = CreditEntry.query.filter_by(order_id=order.id, kind='spent').first()
    if spent is not None and not CreditEntry.query.filter_by(order_id=order.id, kind='restored').first():
        # the credit this refunded order used goes back to the person who used it
        db.session.add(CreditEntry(user_id=spent.user_id, amount=-spent.amount, kind='restored', order_id=order.id,
                                   note=f'Refunded order {order.order_number}'))
        taken += 1
    for row in CreditEntry.query.filter_by(order_id=order.id, kind='earned').all():
        if CreditEntry.query.filter_by(user_id=row.user_id, kind='reversed', order_id=order.id,
                                       shared_design_id=row.shared_design_id).first():
            continue
        db.session.add(CreditEntry(user_id=row.user_id, amount=-row.amount, kind='reversed', order_id=order.id,
                                   shared_design_id=row.shared_design_id, note=f'Refunded order {order.order_number}'))
        taken += 1
    if taken:
        db.session.flush()
    return taken
