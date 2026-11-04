"""One friendly "you left something in your cart" email to a signed-in shopper.

Only carts that belong to an account are saved (guests have no email we can use). A reminder goes out when the
cart has sat untouched for a day, at most once per cart (changing the cart starts it over), never to someone who
has ordered since, and never to someone who unsubscribed. Every email has a one-tap unsubscribe link.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

from models import Order, Product, User, db

FLAG_KEY = 'cart_reminders'
WAIT_HOURS = 24
GIVE_UP_DAYS = 7
SALT = 'cart-reminders'


def _serializer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt=SALT)


def unsubscribe_url(user):
    base = (current_app.config.get('ADMIN_BASE_URL') or 'https://purposefullymadekc.com').rstrip('/')
    return f'{base}/unsubscribe/cart/{_serializer().dumps(user.id)}'


def user_from_token(token):
    try:
        uid = _serializer().loads(token)
    except BadSignature:
        return None
    return db.session.get(User, uid) if isinstance(uid, int) else None


def _lines(user):
    try:
        cart = json.loads(user.cart_json or '[]')
    except (TypeError, ValueError):
        return []
    return [i for i in cart if isinstance(i, dict) and i.get('product_id')] if isinstance(cart, list) else []


def due_users(now=None):
    now = now or datetime.utcnow()
    newest, oldest = now - timedelta(hours=WAIT_HOURS), now - timedelta(days=GIVE_UP_DAYS)
    rows = (User.query.filter(User.cart_json.isnot(None), User.cart_json != '', User.cart_json != '[]',
                              User.cart_updated_at <= newest, User.cart_updated_at >= oldest,
                              db.or_(User.cart_reminders_off.is_(None), User.cart_reminders_off.is_(False)),
                              db.or_(User.cart_reminder_sent_at.is_(None), User.cart_reminder_sent_at < User.cart_updated_at))
            .all())
    out = []
    for u in rows:
        if not (u.email or '').strip() or not _lines(u):
            continue
        if Order.query.filter(Order.user_id == u.id, Order.created_at >= u.cart_updated_at).first():
            continue
        out.append(u)
    return out


def _claim(user):
    claimed = (User.query.filter(User.id == user.id,
                                 db.or_(User.cart_reminder_sent_at.is_(None), User.cart_reminder_sent_at < User.cart_updated_at))
               .update({User.cart_reminder_sent_at: datetime.utcnow()}, synchronize_session=False))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    return bool(claimed)


def send_reminder(user):
    from utils.sponsor_emails import _send
    names = {p.id: p.name for p in Product.query.filter(Product.id.in_([i['product_id'] for i in _lines(user)])).all()}
    details = []
    for item in _lines(user)[:4]:
        label = names.get(item.get('product_id')) or 'Your item'
        bits = [b for b in (item.get('color'), item.get('size')) if b]
        qty = item.get('quantity') or 1
        details.append((label, ', '.join(bits) + f' x {qty}' if bits else f'x {qty}'))
    base = (current_app.config.get('ADMIN_BASE_URL') or 'https://purposefullymadekc.com').rstrip('/')
    first = (user.first_name or '').strip() or 'there'
    return _send(user.email.strip(), 'You left something in your cart', 'Still thinking it over?',
                 [f'Hi {first}, your cart is saved and waiting. Everything is just how you left it, sizes and colors included.'],
                 button={'label': 'Back to my cart', 'url': f'{base}/cart'}, details=details,
                 note='Questions about sizing or a design? Just reply to this email.',
                 footer_link={'label': 'Stop cart reminder emails', 'url': unsubscribe_url(user)})


def send_due(now=None):
    """Send every reminder that is due. Returns how many went out. Never raises."""
    try:
        from utils.site_settings import get_flag
        if not get_flag(FLAG_KEY, True):
            return 0
        sent = 0
        for user in due_users(now):
            if _claim(user) and send_reminder(user):
                sent += 1
        return sent
    except Exception:
        current_app.logger.exception('cart reminder run failed')
        return 0
