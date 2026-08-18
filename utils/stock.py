"""Warehouse stock helpers for SanMar / S&S size-color inventory.

Empty or missing inventory is treated as out of stock so customers cannot
order a blank we have not confirmed is available.
"""
from __future__ import annotations

import json
import re

from utils.json_fields import parse_json_list, parse_json_object
from utils.sizes import _norm


def color_key(name) -> str:
    text = str(name or '').strip().lower().replace('grey', 'gray')
    return re.sub(r'[^a-z0-9]+', '', text)


def size_key(size) -> str:
    s = _norm(size)
    if not s:
        return ''
    aliases = {
        'XXS': '2XS',
        'XXL': '2XL',
        'XXXL': '3XL',
        'XXXXL': '4XL',
        '2X': '2XL',
        '3X': '3XL',
        '4X': '4XL',
        '5X': '5XL',
        '6X': '6XL',
    }
    if s in aliases:
        return aliases[s]
    m = re.match(r'^(\d+)X[LS]?$', s)
    if m:
        return f'{int(m.group(1))}XL'
    return s


def is_usable_inventory_payload(value) -> bool:
    data = value if isinstance(value, dict) else parse_json_object(value)
    return bool(data)


def _qty_int(value) -> int:
    try:
        qty = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, qty)


def keyed_qty_map(inventory) -> dict[str, int]:
    data = inventory if isinstance(inventory, dict) else parse_json_object(inventory)
    keyed = {}
    for raw_size, raw_qty in (data or {}).items():
        key = size_key(raw_size)
        if not key:
            continue
        keyed[key] = keyed.get(key, 0) + _qty_int(raw_qty)
    return keyed


def lookup_qty(inventory, size) -> int:
    keyed = keyed_qty_map(inventory)
    key = size_key(size)
    if not key:
        return 0
    return keyed.get(key, 0)


def inventory_for_display(inventory, shop_sizes) -> dict[str, int]:
    """Map warehouse qty onto the size labels shown in the shop.

    Empty/missing warehouse data stays empty so the UI does not mark every
    size out of stock before the first successful sync.
    """
    keyed = keyed_qty_map(inventory)
    if not keyed:
        return {}
    sizes = [str(s).strip() for s in (shop_sizes or []) if str(s).strip()]
    if not sizes:
        return {raw: _qty_int(qty) for raw, qty in (parse_json_object(inventory) or {}).items()}
    display = {}
    for label in sizes:
        key = size_key(label)
        display[label] = keyed.get(key, 0)
    return display


def find_color_variant(product, color_name):
    from models import ProductColorVariant

    variants = list(getattr(product, 'color_variants', None) or [])
    if not variants and getattr(product, 'id', None):
        variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
    want = color_key(color_name)
    if not want:
        return None
    for variant in variants:
        if color_key(variant.color_name) == want:
            return variant
    return None


def available_qty(product, color, size):
    """Return on-hand qty, or None when this color has not been warehouse-synced."""
    variant = find_color_variant(product, color)
    if not variant:
        return 0
    if not is_usable_inventory_payload(variant.size_inventory):
        return None
    shop_sizes = parse_json_list(getattr(product, 'available_sizes', None))
    display = inventory_for_display(variant.size_inventory, shop_sizes)
    if size in display:
        return _qty_int(display[size])
    return lookup_qty(variant.size_inventory, size)


def same_blank_sku(item, product_id, color, size) -> bool:
    if not isinstance(item, dict):
        return False
    try:
        item_pid = int(item.get('product_id'))
    except (TypeError, ValueError):
        return False
    return (
        item_pid == int(product_id)
        and color_key(item.get('color')) == color_key(color)
        and size_key(item.get('size')) == size_key(size)
    )


def cart_reserved_qty(cart, product_id, color, size, skip_index=None) -> int:
    total = 0
    for index, item in enumerate(cart or []):
        if skip_index is not None and index == skip_index:
            continue
        if not same_blank_sku(item, product_id, color, size):
            continue
        try:
            total += max(0, int(item.get('quantity') or 0))
        except (TypeError, ValueError):
            continue
    return total


def stock_error_message(product, color, size, available, requested) -> str:
    style = getattr(product, 'style_number', '') or 'this style'
    color_label = (color or 'that color').strip() or 'that color'
    size_label = (size or 'that size').strip() or 'that size'
    if available <= 0:
        return (
            f'{style} in {color_label} / {size_label} is out of stock. '
            'Please choose another color or size.'
        )
    return (
        f'Only {available} left in {style} {color_label} / {size_label}. '
        f'Please lower the quantity (you asked for {requested}).'
    )


def check_stock(product, color, size, requested, cart=None, skip_index=None):
    """Return (ok, error_message, available_after_cart)."""
    try:
        requested = int(requested)
    except (TypeError, ValueError):
        requested = 0
    if requested < 1:
        return False, 'Please choose a quantity of at least 1.', 0
    on_hand = available_qty(product, color, size)
    if on_hand is None:
        return True, None, None
    reserved = cart_reserved_qty(cart, product.id, color, size, skip_index=skip_index)
    remaining = max(0, on_hand - reserved)
    if requested > remaining:
        return False, stock_error_message(product, color, size, remaining, requested), remaining
    return True, None, remaining


def _write_variant_qty(variant, size, new_qty, shop_sizes):
    display = inventory_for_display(variant.size_inventory, shop_sizes)
    if size in display:
        display[size] = max(0, int(new_qty))
    else:
        display[size] = max(0, int(new_qty))
        keyed = keyed_qty_map(variant.size_inventory)
        keyed[size_key(size)] = max(0, int(new_qty))
        for label in shop_sizes or []:
            display.setdefault(label, keyed.get(size_key(label), 0))
    variant.size_inventory = json.dumps(display)


def aggregate_cart_blanks(cart):
    """{(product_id, color, size): quantity} using the first seen color/size labels."""
    grouped = {}
    labels = {}
    for item in cart or []:
        if not isinstance(item, dict):
            continue
        try:
            product_id = int(item.get('product_id'))
            qty = int(item.get('quantity') or 0)
        except (TypeError, ValueError):
            continue
        if qty < 1:
            continue
        color = item.get('color') or ''
        size = item.get('size') or ''
        key = (product_id, color_key(color), size_key(size))
        grouped[key] = grouped.get(key, 0) + qty
        labels.setdefault(key, (color, size))
    return grouped, labels


def reserve_cart_inventory(cart):
    """
    Lock matching color variants, confirm stock, and decrement.
    Must run inside the checkout DB transaction. Returns (ok, error).
    """
    from models import Product, ProductColorVariant

    grouped, labels = aggregate_cart_blanks(cart)
    for sku_key, qty in grouped.items():
        product_id, _ck, _sk = sku_key
        color, size = labels[sku_key]
        product = Product.query.get(product_id)
        if not product:
            return False, 'One of the items in your cart is no longer available.'
        variant = find_color_variant(product, color)
        if not variant:
            return False, stock_error_message(product, color, size, 0, qty)
        locked = (
            ProductColorVariant.query
            .filter_by(id=variant.id)
            .with_for_update()
            .first()
        )
        if not locked:
            return False, stock_error_message(product, color, size, 0, qty)
        if not is_usable_inventory_payload(locked.size_inventory):
            continue
        shop_sizes = parse_json_list(product.available_sizes)
        on_hand = lookup_qty(locked.size_inventory, size)
        if on_hand < qty:
            return False, stock_error_message(product, color, size, on_hand, qty)
        _write_variant_qty(locked, size, on_hand - qty, shop_sizes)
    return True, None
