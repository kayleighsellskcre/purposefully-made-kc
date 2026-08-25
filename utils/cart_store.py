"""Shared cart helpers — session for guests, DB-backed for logged-in users.

Logged-in shoppers keep one cart across phone and computer. Every save writes
to the user row; every read prefers that stored cart so both devices stay aligned.
"""
from __future__ import annotations

import json
from datetime import datetime

from flask import session
from flask_login import current_user


def _user_cart_identity(item: dict) -> tuple:
    return (
        item.get('product_id'),
        item.get('size'),
        item.get('color'),
        item.get('design_id'),
        item.get('placement'),
        item.get('back_design_url'),
        json.dumps(item.get('back_design_meta') or {}, sort_keys=True, default=str),
    )


def merge_carts(primary: list, secondary: list) -> list:
    """Merge two carts. Quantities for identical lines are added."""
    out = []
    index = {}
    for src in (primary or [], secondary or []):
        for raw in src:
            if not isinstance(raw, dict) or not raw.get('product_id'):
                continue
            item = dict(raw)
            key = _user_cart_identity(item)
            if key in index:
                try:
                    out[index[key]]['quantity'] = int(out[index[key]].get('quantity') or 0) + int(item.get('quantity') or 0)
                except (TypeError, ValueError):
                    pass
            else:
                index[key] = len(out)
                out.append(item)
    return out


def _read_user_cart(user) -> list:
    raw = getattr(user, 'cart_json', None) or ''
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_user_cart(user, cart: list) -> None:
    from models import db
    user.cart_json = json.dumps(cart or [])
    user.cart_updated_at = datetime.utcnow()
    db.session.add(user)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_cart() -> list:
    """Return the active cart. Authenticated users use the DB-backed cart."""
    owner = session.get('cart_owner_id')
    if current_user.is_authenticated:
        if owner != current_user.id:
            # Fresh login / switched account: load the account cart (do not keep
            # another user's session lines).
            cart = _read_user_cart(current_user)
            session['cart'] = cart
            session['cart_owner_id'] = current_user.id
            session.modified = True
            return cart
        # Prefer DB so the other device's latest save wins.
        db_cart = _read_user_cart(current_user)
        session['cart'] = db_cart
        session['cart_owner_id'] = current_user.id
        session.modified = True
        return db_cart

    if owner not in (None, 'guest'):
        session['cart'] = []
        session['cart_owner_id'] = 'guest'
        session.modified = True
    if 'cart' not in session:
        session['cart'] = []
        session['cart_owner_id'] = 'guest'
        session.modified = True
    return session['cart']


def save_cart(cart: list) -> None:
    """Persist cart to session, and to the user row when logged in."""
    cart = list(cart or [])
    session['cart'] = cart
    if current_user.is_authenticated:
        session['cart_owner_id'] = current_user.id
        _write_user_cart(current_user, cart)
    else:
        session['cart_owner_id'] = 'guest'
    session.modified = True


def clear_cart() -> None:
    save_cart([])


def cart_count(cart=None) -> int:
    cart = get_cart() if cart is None else cart
    total = 0
    for item in cart or []:
        if not isinstance(item, dict):
            continue
        try:
            total += int(item.get('quantity') or 0)
        except (TypeError, ValueError):
            continue
    return total


def cart_fingerprint(cart=None) -> str:
    """Stable fingerprint so devices can detect remote cart changes."""
    cart = get_cart() if cart is None else cart
    try:
        payload = json.dumps(cart or [], sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = str(cart)
    import hashlib
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def adopt_guest_cart_on_login(user, guest_cart: list | None) -> None:
    """After login, merge any guest-session lines into the account cart."""
    stored = _read_user_cart(user)
    merged = merge_carts(stored, guest_cart or [])
    _write_user_cart(user, merged)
    session['cart'] = merged
    session['cart_owner_id'] = user.id
    session.modified = True
