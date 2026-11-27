"""Design proof approval. Optional per order.

The shop sends a proof: the customer gets a private link, sees the design on the shirt, and taps Approve or asks for
changes. While a proof is waiting the order shows "Waiting on approval" and cannot be moved to pressing. One reminder
goes out after 2 days. Each round is kept, so the order page shows the whole conversation.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from flask import current_app

from models import Order, OrderProof, db

REMINDER_AFTER_DAYS = 2
HOLD_STAGES = ('ready_to_press', 'pressed', 'packaged_ready')       # an order waiting on a proof stays before pressing
LABELS = {'waiting': 'Waiting on approval', 'approved': 'Approved', 'changes': 'Changes requested', 'replaced': 'Replaced by a newer proof'}


def _base_url():
    return (current_app.config.get('ADMIN_BASE_URL') or 'https://purposefullymadekc.com').rstrip('/')


def proof_url(proof):
    return f'{_base_url()}/proof/{proof.token}'


def by_token(token):
    if not token:
        return None
    return OrderProof.query.filter_by(token=token).first()


def latest(order_id):
    return OrderProof.query.filter_by(order_id=order_id).order_by(OrderProof.id.desc()).first()


def history(order_id):
    return OrderProof.query.filter_by(order_id=order_id).order_by(OrderProof.id.desc()).all()


def waiting_order_ids():
    """The orders with a proof out right now, so a board can mark them with one query."""
    return {oid for (oid,) in db.session.query(OrderProof.order_id).filter(OrderProof.status == 'waiting').all()}


def waiting_proofs():
    return (OrderProof.query.join(Order, Order.id == OrderProof.order_id)
            .filter(OrderProof.status == 'waiting', Order.status != 'cancelled')
            .order_by(OrderProof.sent_at).all())


def changes_proofs():
    """Proofs where the customer asked for changes and no newer proof has been sent."""
    rows = (OrderProof.query.join(Order, Order.id == OrderProof.order_id)
            .filter(OrderProof.status == 'changes', Order.status != 'cancelled').order_by(OrderProof.responded_at).all())
    return [p for p in rows if latest(p.order_id).id == p.id]


def is_waiting(order):
    p = latest(order.id) if order is not None and order.id else None
    return bool(p and p.status == 'waiting')


def blocked_reason(order, stage):
    """Why an order may not move to this stage yet, or None. Pressing waits for an approved proof."""
    if stage in HOLD_STAGES and is_waiting(order):
        return (f'Order {order.order_number} is waiting on the customer to approve the proof. '
                f'Open the order and choose "Approve for them" if they said yes another way.')
    return None


# ---- sending ----------------------------------------------------------------------------------------

def _first_name(order):
    return (order.first_name or '').strip() or 'there'


def _email_proof(order, proof, reminder=False):
    from utils.sponsor_emails import _send
    if '@' not in (order.email or ''):
        return False
    if reminder:
        subject = f'A reminder: please look at your design for order {order.order_number}'
        paragraphs = [f'Hi {_first_name(order)},',
                      'We are holding your order until you have looked at your design. It only takes a minute, and we start making it as soon as you approve.']
    else:
        subject = f'Please approve your design for order {order.order_number}'
        paragraphs = [f'Hi {_first_name(order)},',
                      'Your design is ready for a quick look. Please check the spelling, the colors and where it sits on the shirt, then tap Approve. If anything should change, tell us and we will fix it.']
        if proof.message:
            paragraphs.append(proof.message)
    return _send(order.email, subject, 'Your design is ready to approve', paragraphs,
                 button={'label': 'Look at my design', 'url': proof_url(proof)},
                 details=[('Order', order.order_number)])


def send_proof(order, message=''):
    """Send a new proof. Any proof still waiting is replaced. Raises ValueError with a plain reason if it cannot go out."""
    if order.status in ('cancelled',):
        raise ValueError('That order is cancelled.')
    if '@' not in (order.email or ''):
        raise ValueError('This order has no email address to send a proof to.')
    for old in OrderProof.query.filter_by(order_id=order.id, status='waiting').all():
        old.status = 'replaced'
    proof = OrderProof(order_id=order.id, token=secrets.token_urlsafe(24), status='waiting',
                       message=(message or '').strip()[:500] or None, sent_at=datetime.utcnow())
    db.session.add(proof)
    db.session.commit()
    _email_proof(order, proof)
    return proof


def resend(proof):
    """Email the same link again (the customer lost it)."""
    if proof.status != 'waiting':
        raise ValueError('That proof is no longer waiting.')
    return _email_proof(proof.order, proof)


# ---- the customer's answer --------------------------------------------------------------------------

def _tell_shop(order, proof, title, text):
    try:
        from utils.admin_notifications import create_notification
        create_notification(kind='proof', title=title, preview=text, body=text, from_name=order.full_name or '',
                            from_email=order.email or '', url=f'/admin/orders/{order.id}', related_id=order.id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('proof notification failed')


def approve(proof, by='customer'):
    """Approved. Pressing can start. Safe to call twice."""
    if proof.status == 'approved':
        return proof
    if proof.status != 'waiting':
        raise ValueError('This proof was replaced by a newer one. Please use the newest link.')
    proof.status, proof.approved_by, proof.responded_at = 'approved', by, datetime.utcnow()
    db.session.commit()
    if by == 'customer':
        _tell_shop(proof.order, proof, f'Design approved: order {proof.order.order_number}',
                   f'{proof.order.full_name} approved the design. It can go to the press.')
    return proof


def request_changes(proof, note):
    note = (note or '').strip()
    if not note:
        raise ValueError('Please tell us what to change.')
    if proof.status != 'waiting':
        raise ValueError('This proof was already answered or replaced.')
    proof.status, proof.response_note, proof.responded_at = 'changes', note[:2000], datetime.utcnow()
    db.session.commit()
    _tell_shop(proof.order, proof, f'Changes asked for: order {proof.order.order_number}',
               f'{proof.order.full_name} asked for changes: {note[:300]}')
    return proof


# ---- reminder ---------------------------------------------------------------------------------------

def run_reminders(now=None):
    """One reminder per proof, after 2 days of silence. Returns how many went out."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=REMINDER_AFTER_DAYS)
    sent = 0
    for proof in waiting_proofs():
        if proof.reminder_sent_at or not proof.sent_at or proof.sent_at > cutoff:
            continue
        if _email_proof(proof.order, proof, reminder=True):
            proof.reminder_sent_at = now
            db.session.commit()
            sent += 1
    return sent
