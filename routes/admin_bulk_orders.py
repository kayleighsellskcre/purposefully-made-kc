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


@admin_bp.route('/orders/<int:order_id>/mockups.pdf')
@admin_required
def order_mockups_pdf(order_id):
    """A PDF of front and back mockups for every different shirt in the order, to download and send."""
    from io import BytesIO
    from flask import send_file
    from models import Order
    from utils.order_mockups import mockup_pdf
    order = Order.query.get_or_404(order_id)
    pdf = mockup_pdf(order)
    if not pdf:
        flash('There is no shirt picture to draw for this order yet.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order.id))
    return send_file(BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
                     download_name=f'Mockups-{order.order_number}.pdf')


@admin_bp.route('/orders/<int:order_id>/edit-shirts', methods=['GET', 'POST'])
@admin_required
def order_edit_shirts(order_id):
    """Change the style, color, size, names and numbers on an order that was already entered."""
    from models import ManualInvoice, Order
    from utils import order_edit as E
    from utils.order_artwork import items_of
    order = Order.query.get_or_404(order_id)
    items = items_of(order)
    if request.method == 'POST':
        rows = []
        f = request.form
        for i in items:
            try:
                pid = int(f.get(f'product_{i.id}') or i.product_id)
            except (TypeError, ValueError):
                pid = i.product_id
            rows.append({'item_id': i.id, 'product_id': pid, 'color': (f.get(f'color_{i.id}') or '').strip(),
                         'size': (f.get(f'size_{i.id}') or '').strip(),
                         'name': f.get(f'name_{i.id}') or '', 'number': f.get(f'number_{i.id}') or ''})
        changed = E.apply_shirt_edits(order, rows, font=(f.get('font') or '').strip() or None,
                                      text_color=(f.get('text_color') or '').strip() or None,
                                      placement=(f.get('placement') or '').strip() or None)
        reworded = E.sync_invoice_lines(order) if changed else False
        has_invoice = ManualInvoice.query.filter_by(order_id=order.id).count() > 0
        message = f'Saved. {changed} shirt{"" if changed == 1 else "s"} changed.'
        if reworded:
            message += ' The invoice wording now matches.'
        elif changed and has_invoice:
            message += ' The invoice was left as it is (its prices are not the same as the shirts), so check it.'
        flash(message, 'success')
        return redirect(url_for('admin.order_detail', order_id=order.id))
    first = next((i for i in items if i.back_design_details), None)
    meta = (first.back_design_details if first else None) or {}
    catalog = _catalog()
    return render_template(
        'admin/order_edit_shirts.html', order=order, items=items, catalog=catalog,
        catalog_map={str(c['id']): {'colors': c['colors'], 'sizes': c['sizes']} for c in catalog},
        fonts=[{'value': v, 'label': l} for v, l in GROUP_ORDER_FONTS], font=meta.get('font') or '',
        text_color=meta.get('text_color') or '#ffffff', placement=(items[0].placement if items else 'center_chest'),
        colors=[('#000000', 'Black'), ('#ffffff', 'White'), ('#1e3a8a', 'Navy'), ('#b91c1c', 'Red'), ('#d4a017', 'Gold'),
                ('#6b7280', 'Gray'), ('#166534', 'Green'), ('#6d28d9', 'Purple'), ('#ea580c', 'Orange')])
