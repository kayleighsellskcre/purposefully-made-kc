"""Order again: put a past order's items back in the cart, as they were made.

Each line keeps its size, color, artwork, placement, back print (name, number or image) and proofs. Prices are
worked out fresh from today's price list. A line that can no longer be ordered (a style we dropped, a store that
has closed, artwork that is gone) is left out and the customer is told which one and why.
"""
from __future__ import annotations

import json

from models import Design, Product, ProductColorVariant, db


def _json_list(raw):
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(raw):
    try:
        value = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _label(item):
    return item.product_name or (item.product.name if item.product else 'An item')


def _closed_store_reason(collection_id):
    """Why a group store line cannot be ordered again, or None."""
    from models import Collection
    from utils.group_orders import is_deadline_passed, is_not_yet_open
    store = db.session.get(Collection, collection_id)
    if store is None or not store.is_active:
        return 'that group store is no longer open'
    if is_deadline_passed(store):
        return f'ordering for {store.name} has closed'
    if is_not_yet_open(store):
        return f'{store.name} is not open for orders yet'
    return None


def _line_from(item):
    """(cart line, reason). Exactly one of them is None."""
    from utils.cloud_storage import image_url
    from utils.pricing import calculate_unit_price

    product = db.session.get(Product, item.product_id)
    if product is None or not product.is_active:
        return None, 'we no longer carry this style'
    sizes = _json_list(product.available_sizes)
    if sizes and item.size not in sizes:
        return None, f'size {item.size} is no longer offered'
    if item.color and ProductColorVariant.query.filter_by(product_id=product.id).count() \
            and not ProductColorVariant.query.filter_by(product_id=product.id, color_name=item.color).first():
        return None, f'{item.color} is no longer offered'

    collection_id = item.collection_id or None          # 0 marks a regular shop item inside a group order
    if collection_id:
        reason = _closed_store_reason(collection_id)
        if reason:
            return None, reason

    design = db.session.get(Design, item.design_id) if item.design_id else None
    if item.design_id and design is None:
        return None, 'the artwork is no longer on file'
    if design is None and item.design_file_name:
        return None, 'the uploaded artwork is no longer on file'
    design_url = image_url(design.file_path) if design else None

    back_meta = _json_dict(item.back_design_meta)
    back_url = (back_meta or {}).get('file_url') or None
    has_personalization = bool(back_meta and (back_meta.get('name') or back_meta.get('number')))
    has_back = bool(has_personalization or back_url)
    back_kind = 'personalization' if has_personalization else ('image' if back_url else None)
    is_blank = not (design or has_back)

    unit_price = calculate_unit_price(
        product, size=item.size, placement=item.placement, has_back_design=has_back,
        back_design_parts=(int(bool(back_meta.get('name'))) + int(bool(back_meta.get('number')))
                           if back_kind == 'personalization' else None),
        is_blank=is_blank, design_fee=float(getattr(design, 'design_fee', 0) or 0))

    return {
        'product_id': item.product_id,
        'size': item.size,
        'color': item.color,
        'quantity': item.quantity,
        'unit_price': unit_price,
        'is_blank': is_blank,
        'design_id': item.design_id,
        'design_url': design_url,
        'placement': item.placement,
        'back_design_url': back_url,
        'back_design_kind': back_kind,
        'back_design_meta': back_meta,
        'proof_front_url': item.proof_image,
        'proof_back_url': item.proof_back_image,
        'print_width': item.print_width,
        'print_height': item.print_height,
        'transfer_production': _json_dict(item.transfer_production),
        'position_x': item.position_x,
        'position_y': item.position_y,
        'rotation': item.rotation or 0,
        'proof_image': item.proof_image,
        'collection_id': collection_id,
        'catalog_section': item.catalog_section,
        'uniform_kit': item.uniform_kit,
    }, None


def _same_line(a, b):
    keys = ('product_id', 'size', 'color', 'design_id', 'placement', 'back_design_url', 'back_design_meta',
            'catalog_section', 'uniform_kit', 'collection_id')
    return all(a.get(k) == b.get(k) for k in keys)


def add_order_to_cart(order, cart):
    """Add the order's items to ``cart`` (a list, changed in place).

    Returns (lines added, [(item name, reason) left out], note). The note is set when items from another group
    had to come out of the cart, because one cart holds one group at a time.
    """
    lines, skipped = [], []
    for item in order.items:
        line, reason = _line_from(item)
        if line is None:
            skipped.append((_label(item), reason))
        else:
            lines.append(line)

    added, note = merge_lines(cart, lines)
    return added, skipped, note


def merge_lines(cart, lines):
    """Add ``lines`` to ``cart`` (a list, changed in place), joining identical lines.

    Returns (pieces added, note). The note is set when items from another group had to come out of the cart,
    because one cart holds one group at a time.
    """
    from utils.group_orders import cart_group_label, stores_share_an_org

    note = None
    new_ids = {line['collection_id'] for line in lines if line.get('collection_id')}
    if new_ids:
        def compatible(existing):
            cid = existing.get('collection_id') or None
            return cid is None or all(stores_share_an_org(cid, n) for n in new_ids)
        mixed = [i for i in cart if isinstance(i, dict) and not compatible(i)]
        if mixed:
            removed = cart_group_label(mixed, fallback='the other group')
            cart[:] = [i for i in cart if isinstance(i, dict) and compatible(i)]
            note = (f'Your {removed} items were taken out of the cart, because one cart can only hold '
                    'one group at a time.')

    added = 0
    for line in lines:
        existing = next((c for c in cart if isinstance(c, dict) and _same_line(c, line)), None)
        if existing:
            existing['quantity'] = int(existing.get('quantity') or 0) + int(line['quantity'] or 0)
        else:
            cart.append(line)
        added += int(line['quantity'] or 0)
    return added, note


def why_not_orderable(line):
    """Why a cart line can no longer be ordered (a sentence fragment), or None when it still can."""
    product = db.session.get(Product, line.get('product_id') or 0)
    if product is None or not product.is_active:
        return 'we no longer carry this style'
    sizes = _json_list(product.available_sizes)
    if sizes and line.get('size') not in sizes:
        return f"size {line.get('size')} is no longer offered"
    color = line.get('color')
    if color and ProductColorVariant.query.filter_by(product_id=product.id).count()             and not ProductColorVariant.query.filter_by(product_id=product.id, color_name=color).first():
        return f'{color} is no longer offered'
    if line.get('collection_id'):
        reason = _closed_store_reason(line['collection_id'])
        if reason:
            return reason
    if line.get('design_id') and db.session.get(Design, line['design_id']) is None:
        return 'the artwork is no longer on file'
    return None


def reprice_line(line):
    """Set the line's price from today's price list (changes ``line``)."""
    from utils.pricing import calculate_unit_price
    product = db.session.get(Product, line['product_id'])
    design = db.session.get(Design, line['design_id']) if line.get('design_id') else None
    meta = line.get('back_design_meta') or {}
    has_personalization = bool(meta.get('name') or meta.get('number'))
    has_back = bool(has_personalization or line.get('back_design_url'))
    line['unit_price'] = calculate_unit_price(
        product, size=line.get('size'), placement=line.get('placement'), has_back_design=has_back,
        back_design_parts=(int(bool(meta.get('name'))) + int(bool(meta.get('number')))
                           if line.get('back_design_kind') == 'personalization' else None),
        is_blank=not (design or line.get('design_url') or has_back),
        design_fee=float(getattr(design, 'design_fee', 0) or 0))
    return line
