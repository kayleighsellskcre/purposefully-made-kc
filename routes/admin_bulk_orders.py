"""Admin: Enter an order. One table for a whole group's names, sizes and numbers.

The order lands in New Orders (Awaiting Payment) and an invoice with a card pay link is made for it.
See utils/bulk_orders.py for how the two stay in step.
"""
import json

from flask import flash, jsonify, redirect, render_template, request, url_for

from models import BulkOrderDraft, Collection, Design, Product, db
from routes.admin import admin_bp, admin_required
from utils import bulk_orders as B
from utils import sales_tax
from utils.cloud_storage import image_url
from utils.fonts import GROUP_ORDER_FONTS


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
    error, draft, draft_id = None, None, request.values.get('draft_id', type=int)
    if request.method == 'POST':
        draft = request.form.get('order_json') or ''
        if request.form.get('action') == 'draft':
            saved = _save_draft(draft_id, draft)
            flash('Draft saved. Pick it up again from "Saved drafts" on this page.', 'success')
            return redirect(url_for('admin.bulk_order_new', draft=saved.id))
        try:
            order, invoices = B.create_bulk_order(B.clean_payload(draft))
            if draft_id:
                BulkOrderDraft.query.filter_by(id=draft_id).delete()
                db.session.commit()
            if len(invoices) == 1:
                flash(f'Order {order.order_number} is in New Orders, marked Awaiting Payment. '
                      f'Invoice {invoices[0].number} is ready: send it from here.', 'success')
                return redirect(url_for('admin.invoice_view', invoice_id=invoices[0].id))
            flash(f'Order {order.order_number} is in New Orders, marked Awaiting Payment. '
                  f'{len(invoices)} invoices were made, one for each person. Open each to send it.', 'success')
            return redirect(url_for('admin.order_detail', order_id=order.id))
        except B.BulkOrderError as exc:
            db.session.rollback()
            error = str(exc)
    elif request.args.get('draft', type=int):
        saved = db.session.get(BulkOrderDraft, request.args.get('draft', type=int))
        if saved:
            draft, draft_id = saved.payload_json, saved.id
    designs = (Design.query.order_by(Design.id.desc()).limit(300).all())
    groups = Collection.query.order_by(Collection.id.desc()).limit(200).all()
    drafts = BulkOrderDraft.query.order_by(BulkOrderDraft.updated_at.desc()).limit(20).all()
    return render_template(
        'admin/bulk_order.html', catalog=_catalog(), error=error, draft=draft, draft_id=draft_id, drafts=drafts,
        designs=[{'id': d.id, 'title': d.title or d.original_filename or d.filename, 'url': image_url(d.file_path)} for d in designs],
        collections=[{'id': c.id, 'name': c.name} for c in groups],
        fonts=[{'value': v, 'label': l} for v, l in GROUP_ORDER_FONTS],
        tax_percent='%g' % sales_tax.rate_percent())


def _save_draft(draft_id, raw):
    """Keep a half-typed order. No checks: a draft is allowed to be unfinished."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        data = {}
    cust = data.get('customer') or {}
    title = (str(cust.get('company') or '').strip() or str(cust.get('name') or '').strip() or 'Untitled order')[:200]
    row = db.session.get(BulkOrderDraft, draft_id) if draft_id else None
    if row is None:
        row = BulkOrderDraft()
        db.session.add(row)
    row.title, row.payload_json = title, json.dumps(data)[:300000]
    db.session.commit()
    return row


@admin_bp.route('/orders/enter/drafts/<int:draft_id>/delete', methods=['POST'])
@admin_required
def bulk_order_draft_delete(draft_id):
    BulkOrderDraft.query.filter_by(id=draft_id).delete()
    db.session.commit()
    flash('Draft deleted.', 'success')
    return redirect(url_for('admin.bulk_order_new'))


@admin_bp.route('/orders/enter/mockup')
@admin_required
def bulk_order_mockup():
    """The shirt photos (front and back) for an item and color, so the form can show a live mockup."""
    from utils.order_artwork import mockup_urls
    product = db.session.get(Product, request.args.get('product_id', type=int) or 0)
    front, back = mockup_urls(product, request.args.get('color') or None) if product else (None, None)
    return jsonify({'front': front, 'back': back})


@admin_bp.route('/orders/enter/token')
@admin_required
def bulk_order_token():
    """A fresh form token. A long order can take more than the hour a token lasts, and the page asks for a new one."""
    from flask_wtf.csrf import generate_csrf
    return jsonify({'token': generate_csrf()})


@admin_bp.route('/orders/enter/parse', methods=['POST'])
@admin_required
def bulk_order_parse():
    """Turn pasted spreadsheet text into rows (the page fills its table with them)."""
    text = (request.get_json(silent=True) or {}).get('text') or request.form.get('text') or ''
    return jsonify({'rows': B.parse_paste(text)})
