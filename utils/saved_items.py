"""Save for later: put a cart item aside with everything about it, and bring it back with one tap.

A signed-in shopper's saved items live on their account (so they follow them to another device). A guest's live in
their browser session and move to the account when they sign in. A saved item is the whole cart line: size, color,
artwork, placement, back name and number, proofs and the store it came from.
"""
from __future__ import annotations

import secrets

from flask import session
from flask_login import current_user

from models import Product, SavedCartItem, db

SESSION_KEY = 'saved_for_later'
MAX_SAVED = 50


def _signed_in():
    return bool(current_user and getattr(current_user, 'is_authenticated', False))


def _session_list():
    return [e for e in (session.get(SESSION_KEY) or []) if isinstance(e, dict) and e.get('token') and e.get('line')]


def _rows():
    return SavedCartItem.query.filter_by(user_id=current_user.id).order_by(SavedCartItem.created_at.desc(), SavedCartItem.id.desc()).all()


def saved_entries():
    """[{'token', 'line'}] newest first, for whoever is browsing."""
    if _signed_in():
        return [{'token': r.token, 'line': r.line} for r in _rows()]
    return list(reversed(_session_list()))


def saved_count():
    return len(saved_entries())


def saved_for_page():
    """Saved items ready to show: the line, its product and the picture, newest first. Items whose style is gone are skipped."""
    from utils.order_artwork import existing_image_url, mockup_urls
    out = []
    for entry in saved_entries():
        line = entry['line']
        product = db.session.get(Product, line.get('product_id') or 0)
        if product is None:
            continue
        proof = existing_image_url(line.get('proof_front_url') or line.get('proof_image'))
        front, _back = mockup_urls(product, line.get('color'))
        try:
            total = float(line.get('unit_price') or 0) * int(line.get('quantity') or 1)
        except (TypeError, ValueError):
            total = 0.0
        meta = line.get('back_design_meta') or {}
        out.append({'token': entry['token'], 'line': line, 'product': product, 'image': proof or front,
                    'total': total, 'back_text': ' '.join(x for x in (meta.get('name'), meta.get('number')) if x),
                    'has_design': bool(line.get('design_url') or line.get('design_id'))})
    return out


def save_line(cart, index):
    """Take line ``index`` out of ``cart`` (changed in place) and keep it. Returns (ok, message)."""
    if index < 0 or index >= len(cart) or not isinstance(cart[index], dict):
        return False, 'That item is no longer in your cart.'
    if saved_count() >= MAX_SAVED:
        return False, f'You can keep up to {MAX_SAVED} items saved. Remove one first.'
    line = dict(cart.pop(index))
    token = secrets.token_hex(8)
    if _signed_in():
        db.session.add(SavedCartItem(user_id=current_user.id, token=token, product_id=line.get('product_id'), line=line))
        db.session.commit()
    else:
        saved = _session_list()
        saved.append({'token': token, 'line': line})
        session[SESSION_KEY] = saved
        session.modified = True
    return True, 'Saved for later.'


def _forget(token):
    if _signed_in():
        row = SavedCartItem.query.filter_by(user_id=current_user.id, token=token).first()
        if row is not None:
            db.session.delete(row)
            db.session.commit()
    else:
        session[SESSION_KEY] = [e for e in _session_list() if e['token'] != token]
        session.modified = True


def remove_saved(token):
    _forget(token)
    return True, 'Removed.'


def move_to_cart(token, cart):
    """Put a saved item back in ``cart`` (changed in place), at today's price. Returns (ok, message, note)."""
    from utils.reorder import merge_lines, reprice_line, why_not_orderable
    entry = next((e for e in saved_entries() if e['token'] == token), None)
    if entry is None:
        return False, 'That saved item was not found.', None
    line = dict(entry['line'])
    reason = why_not_orderable(line)
    if reason:
        return False, f'This item cannot be ordered right now: {reason}.', None
    reprice_line(line)
    _added, note = merge_lines(cart, [line])
    _forget(token)
    return True, 'Moved back to your cart.', note


def adopt_guest_saved(user, guest_saved):
    """After sign-in, bring a guest's saved items onto the account."""
    existing = SavedCartItem.query.filter_by(user_id=user.id).count()
    for entry in (guest_saved or []):
        if not isinstance(entry, dict) or not entry.get('line') or existing >= MAX_SAVED:
            continue
        db.session.add(SavedCartItem(user_id=user.id, token=entry.get('token') or secrets.token_hex(8),
                                     product_id=entry['line'].get('product_id'), line=entry['line']))
        existing += 1
    db.session.commit()
