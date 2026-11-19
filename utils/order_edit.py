"""Change the shirts on an order after it was entered: style, color, size, name, number, font, text color, logo place.

Quantities and prices are NOT changed here (the money stays exactly as invoiced); change those on the invoice.
"""
from __future__ import annotations

import json

# Saved print pictures that depend on the name, number, font or color. Dropped when those change, so they are drawn again.
_STALE_KEYS = ('name_png_url', 'number_png_url', 'production_png_url', 'production_approved', 'aspect_w', 'aspect_h',
               'file_url', 'url')
PLACEMENTS = ('center_chest', 'left_chest', 'right_chest')


def apply_shirt_edits(order, rows, font=None, text_color=None, placement=None):
    """rows: [{item_id, product_id, color, size, name, number}]. Returns how many shirts changed."""
    from models import Product, db
    from utils.order_artwork import items_of
    by_id = {i.id: i for i in items_of(order)}
    changed = 0
    for row in rows:
        item = by_id.get(row.get('item_id'))
        if item is None:
            continue
        before = (item.product_id, item.color, item.size, item.placement, item.back_design_meta)
        product = db.session.get(Product, row['product_id']) if row.get('product_id') else None
        if product and product.id != item.product_id:
            item.product_id, item.product_name, item.style_number = product.id, product.name, product.style_number
        if row.get('color'):
            item.color = row['color'][:100]
        if row.get('size'):
            item.size = row['size'][:20]
        if placement in PLACEMENTS and (item.placement in PLACEMENTS or not item.placement):
            item.placement = placement
        meta = dict(item.back_design_details or {})
        name, number = (row.get('name') or '').strip()[:60], (row.get('number') or '').strip()[:10]
        new_font = (font or meta.get('font') or '')[:60]
        new_color = (text_color or meta.get('text_color') or '')[:20]
        if name or number:
            if ((meta.get('name') or '') != name or str(meta.get('number') or '') != number
                    or (meta.get('font') or '') != new_font or (meta.get('text_color') or '') != new_color):
                for k in _STALE_KEYS:
                    meta.pop(k, None)
            meta.update({'name': name, 'number': number, 'font': new_font, 'text_color': new_color,
                         'font_weight': 'bold', 'font_style': 'normal', 'layout_version': 2})
            item.back_design_meta = json.dumps(meta)
        elif meta.get('name') or meta.get('number'):
            for k in ('name', 'number') + _STALE_KEYS:
                meta.pop(k, None)
            item.back_design_meta = json.dumps(meta) if meta else None
        after = (item.product_id, item.color, item.size, item.placement, item.back_design_meta)
        if after != before:
            item.transfer_production = None          # sizes are worked out again from the new style, size and name
            changed += 1
    db.session.commit()
    return changed


def sync_invoice_lines(order):
    """Reword the invoice lines to match the shirts, only when the money would not change. Returns True if reworded."""
    from collections import OrderedDict
    from models import ManualInvoice, Product, db
    from utils.order_artwork import items_of
    invoices = ManualInvoice.query.filter_by(order_id=order.id).all()
    if not invoices:
        return False
    items = items_of(order)
    ids = {i.product_id for i in items}
    products = {p.id: p for p in Product.query.filter(Product.id.in_(ids)).all()} if ids else {}
    reworded = False
    for inv in invoices:
        mine = items if len(invoices) == 1 else [i for i in items if (i.notes or '') == f'For {inv.customer_name}']
        if not mine:
            continue
        lines = OrderedDict()
        for i in mine:
            p = products.get(i.product_id)
            key = (i.product_id, i.color, i.size, float(i.unit_price or 0))
            line = lines.setdefault(key, {
                'description': f"{(p.name if p else i.product_name)} ({(p.style_number if p else i.style_number)})"
                               + (f", {i.color}" if i.color else '') + f", {i.size}",
                'qty': 0, 'unit': float(i.unit_price or 0)})
            line['qty'] += int(i.quantity or 1)
        try:
            old = json.loads(inv.items_json or '[]')
        except ValueError:
            continue

        def money(rows):
            return round(sum(float(r.get('qty') or 0) * float(r.get('unit', r.get('price', 0)) or 0) for r in rows), 2)
        new = list(lines.values())
        if money(old) == money(new):
            inv.items_json = json.dumps(new)
            reworded = True
    db.session.commit()
    return reworded
