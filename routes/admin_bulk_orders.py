"""Admin: Enter an order. One table for a whole group's names, sizes and numbers.

The order lands in New Orders (Awaiting Payment) and an invoice with a card pay link is made for it.
See utils/bulk_orders.py for how the two stay in step.
"""
import json

from flask import flash, jsonify, redirect, render_template, request, url_for

from models import Collection, Design, Product, db
from routes.admin import admin_bp, admin_required
from utils import bulk_orders as B
from utils import sales_tax


def _list(raw):
    try:
        out = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        return []
    names = []
    for entry in out if isinstance(out, list) else []:
        text = entry.get('name') if isinstance(entry, dict) else entry
        if text:
            names.append(str(text))
    return names


def _catalog():
    rows = []
    for p in Product.query.filter(Product.is_active.isnot(False)).order_by(Product.name).all():
        rows.append({'id': p.id, 'name': f'{p.name} ({p.style_number})', 'price': float(p.base_price or 0),
                     'colors': _list(p.available_colors), 'sizes': _list(p.available_sizes)})
    return rows


@admin_bp.route('/orders/enter', methods=['GET', 'POST'])
@admin_required
def bulk_order_new():
    """Enter an order for a customer, or a whole group, in one table."""
    error, draft = None, None
    if request.method == 'POST':
        draft = request.form.get('order_json') or ''
        try:
            order, invoice = B.create_bulk_order(B.clean_payload(draft))
            flash(f'Order {order.order_number} is in New Orders, marked Awaiting Payment. '
                  f'Invoice {invoice.number} is ready: send it from here.', 'success')
            return redirect(url_for('admin.invoice_view', invoice_id=invoice.id))
        except B.BulkOrderError as exc:
            db.session.rollback()
            error = str(exc)
    designs = (Design.query.order_by(Design.id.desc()).limit(300).all())
    groups = Collection.query.order_by(Collection.id.desc()).limit(200).all()
    return render_template(
        'admin/bulk_order.html', catalog=_catalog(), error=error, draft=draft,
        designs=[{'id': d.id, 'title': d.title or d.original_filename or d.filename} for d in designs],
        collections=[{'id': c.id, 'name': c.name} for c in groups],
        tax_percent='%g' % sales_tax.rate_percent())


@admin_bp.route('/orders/enter/parse', methods=['POST'])
@admin_required
def bulk_order_parse():
    """Turn pasted spreadsheet text into rows (the page fills its table with them)."""
    text = (request.get_json(silent=True) or {}).get('text') or request.form.get('text') or ''
    return jsonify({'rows': B.parse_paste(text)})
