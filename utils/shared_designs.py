"""Share a design: one link and QR code that opens exactly what a customer made.

A shared design keeps the style, color, artwork, placement and size of the print, but never anything personal:
no name or number on the back, no group store, no size or quantity (each person picks their own). Everyone who
opens the link can see the artwork, so the share button says so. Each order that comes through a link is counted
on the creator's account.
"""
from __future__ import annotations

import secrets

from models import Order, OrderItem, Product, SharedDesign, db

# What a shared line keeps. Anything else on a cart line is left behind.
KEEP = ('product_id', 'color', 'design_id', 'design_url', 'placement', 'back_design_url', 'proof_front_url',
        'proof_image', 'print_width', 'print_height', 'transfer_production', 'position_x', 'position_y', 'rotation')


def clean_line(line):
    """(shareable line, reason). Exactly one of them is None."""
    if not isinstance(line, dict) or not line.get('product_id'):
        return None, 'That item could not be found.'
    if line.get('catalog_section') or line.get('uniform_kit'):
        return None, 'This item is shared with its store link instead.'     # group store designs ARE shareable: KEEP leaves the store off
    if not (line.get('design_id') or line.get('design_url')):
        return None, 'Add your artwork first, then share it.'
    out = {k: line.get(k) for k in KEEP if line.get(k) is not None}
    tp = out.get('transfer_production')
    if isinstance(tp, dict):
        tp = dict(tp)
        tp['back'] = None                                  # a name or number on the back stays with the person who made it
        out['transfer_production'] = tp
    out['back_design_kind'] = 'image' if out.get('back_design_url') else None
    out['quantity'] = 1
    return out, None


def share_line(line, user=None):
    """Make (or find) the share link for ``line``. Returns (SharedDesign, message)."""
    clean, reason = clean_line(line)
    if reason:
        return None, reason
    same = None
    if user is not None:
        same = next((s for s in SharedDesign.query.filter_by(user_id=user.id).all()
                     if s.is_active and all(s.line.get(k) == clean.get(k) for k in
                                            ('product_id', 'color', 'design_id', 'design_url', 'placement', 'back_design_url'))), None)
    if same is not None:
        return same, None
    product = db.session.get(Product, clean['product_id'])
    share = SharedDesign(token=secrets.token_urlsafe(9), user_id=user.id if user is not None else None, line=clean,
                         title=(product.name if product else 'Custom shirt')[:200])
    db.session.add(share)
    db.session.commit()
    return share, None


def get_active(token):
    share = SharedDesign.query.filter_by(token=token).first()
    return share if share is not None and share.is_active else None


def line_for(share, size, quantity=1):
    """A cart line for this shared design in ``size``, priced from today's price list, and why it cannot be ordered."""
    from utils.reorder import reprice_line, why_not_orderable
    line = dict(share.line)
    line['size'] = size
    line['quantity'] = max(1, min(int(quantity or 1), 100))
    reason = why_not_orderable(line)
    if reason:
        return None, reason
    reprice_line(line)
    line['shared_design_id'] = share.id
    return line, None


def sizes_with_prices(share):
    """[(size, unit price)] for the sizes still offered, or ([], reason)."""
    import json
    product = db.session.get(Product, share.line.get('product_id') or 0)
    if product is None or not product.is_active:
        return [], 'we no longer carry this style'
    try:
        sizes = json.loads(product.available_sizes) if product.available_sizes else []
    except (TypeError, ValueError):
        sizes = []
    out = []
    for size in sizes:
        line, _reason = line_for(share, size)
        if line:
            out.append((size, line['unit_price']))
    if not out:
        _line, reason = line_for(share, sizes[0] if sizes else 'M')
        return [], reason or 'this item is not available right now'
    return out, None


def results(share):
    """(orders, pieces) that came through this link and were paid."""
    rows = (db.session.query(OrderItem.order_id, OrderItem.quantity).join(Order, Order.id == OrderItem.order_id)
            .filter(OrderItem.shared_design_id == share.id, Order.payment_status == 'paid').all())
    return len({r[0] for r in rows}), sum(int(r[1] or 0) for r in rows)
