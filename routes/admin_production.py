"""Admin Production Center: the master sheet, transfers, blank apparel list, receipts and packing slips, invoices, labels, and the bulk, DTF and logo sheets.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
import csv
import json
from datetime import datetime
from io import BytesIO, StringIO

from flask import render_template, request, redirect, url_for, flash, current_app, send_file, Response
from models import db, Collection, Order
from utils import sales_tax

from routes.admin import (  # noqa: E402
    _collect_order_productions, _collect_press_shirts, _sort_press_shirts, _transfer_csv_response,
    admin_bp, admin_required,
)


# ===== PRODUCTION CENTER =====

def _master_art_files(orders):
    """Every print picture on the Production Master page, each with its size code, print size and file name."""
    from utils.print_sizes import production_from_order_item
    from utils.production_images import code_for, file_name
    from utils.back_logo_size import back_logo_dims
    from utils.dtf_orders import _back_logo_name
    from utils.size_codes import size_order
    files = []
    seen_fronts = {}
    seen_backs = {}
    from utils.order_artwork import preload_order_items, items_of
    preload_order_items(orders)
    for order in orders:
        for item in items_of(order):
            prod = production_from_order_item(item, customer_name=order.full_name) or {}
            code = code_for(item)
            qty = int(item.quantity or 1)
            front = prod.get('front')
            if front:
                key = (item.design_id, item.placement or '', round(front.get('width') or 0, 2), round(front.get('height') or 0, 2))
                rec = seen_fronts.get(key)
                if rec is None:
                    rec = {'order': order, 'item': item, 'side': 'front', 'codes': set(), 'qty': 0, 'width': front.get('width'),
                           'height': front.get('height'), 'label': front.get('design_name') or (item.design_file_name or '').split('?')[0].rsplit('/', 1)[-1] or 'logo',
                           'order_number': 'weekly'}
                    rec['key'] = key
                    seen_fronts[key] = rec
                    files.append(rec)
                rec['codes'].add(code)
                rec['qty'] += qty
            back = prod.get('back')
            if back:
                if back.get('kind') == 'image':
                    dims = back_logo_dims(item)
                    width, height = dims['width'], dims['height']
                    label = 'back-' + (_back_logo_name(item).replace('Back design: ', '') or 'design')
                    from utils.order_artwork import back_print_url as _back_url
                    same = (_back_url(item), code, round(width or 0, 2), round(height or 0, 2))
                    if same in seen_backs:                       # the same back picture at the same size: one file, one total
                        seen_backs[same]['qty'] += qty
                        seen_backs[same]['order_number'] = 'weekly'
                        continue
                    rec = {'order': order, 'item': item, 'side': 'back', 'codes': {code}, 'qty': qty, 'width': width,
                           'height': height, 'label': label, 'order_number': order.order_number}
                    seen_backs[same] = rec
                    files.append(rec)
                    continue
                elif back.get('name') or back.get('number'):
                    width, height = back.get('combined_width'), back.get('combined_height')
                    label = 'back-' + ' '.join(p for p in (back.get('name'), str(back.get('number') or '')) if p)
                else:
                    continue
                files.append({'order': order, 'item': item, 'side': 'back', 'codes': {code}, 'qty': qty, 'width': width,
                              'height': height, 'label': label, 'order_number': order.order_number})
    for rec in files:
        codes = sorted(rec['codes'], key=size_order)
        rec['name'] = file_name('+'.join(c for c in codes if c) or 'NA', rec['width'], rec['height'], rec['label'], rec['qty'],
                                rec['order_number'])
    return files


@admin_bp.route('/production/master/images.zip')
@admin_required
def production_master_zip():
    """All the print pictures from the Production Master page in one ZIP, named by size."""
    from utils.ops_flow import ops_order_query_for
    from utils.production_images import zip_bytes
    query, stages, collection_id = ops_order_query_for(['order_received'])
    orders = query.order_by(Order.created_at).all()
    entries = [(f['order'], f['item'], f['side'], f['name']) for f in _master_art_files(orders)]
    if not entries:
        flash('There are no print pictures to save yet.', 'info')
        return redirect(url_for('admin.production_master'))
    data, added, missing = zip_bytes(entries, request.host_url)
    if not added:
        flash('None of the pictures could be read. Open the page and save them one at a time.', 'error')
        return redirect(url_for('admin.production_master'))
    return send_file(BytesIO(data), mimetype='application/zip', as_attachment=True,
                     download_name=f'print-files_{datetime.now().strftime("%Y%m%d")}.zip')


@admin_bp.route('/production/master')
@admin_required
def production_master():
    """Master copy: blanks + designs for orders just received or waiting on supplies."""
    from utils.ops_flow import ops_order_query_for
    from utils.production_stages import orders_for_stages
    # New orders only: anything waiting on supplies was already ordered from the vendors.
    query, stages, collection_id = ops_order_query_for(['order_received'])
    orders = query.order_by(Order.created_at).all()
    waiting_query = orders_for_stages(['waiting_supplies'])
    if collection_id:
        from utils.group_orders import filter_orders_to_collection
        waiting_query = filter_orders_to_collection(waiting_query, collection_id)
    waiting_count = waiting_query.count()

    # Blank apparel totals
    apparel_totals = {}
    from utils.order_artwork import preload_order_items, items_of
    preload_order_items(orders)
    for order in orders:
        for item in items_of(order):
            section = (
                f'{(item.uniform_kit or "Player").title()} Uniform'
                if item.catalog_section == 'uniform'
                else (
                    'Family & Fan Wear'
                    if item.catalog_section == 'fan'
                    else 'Standard Apparel'
                )
            )
            key = (section, item.style_number, item.product_name, item.color, item.size)
            if key not in apparel_totals:
                apparel_totals[key] = {
                    'section': section,
                    'style_number': item.style_number,
                    'product_name': item.product_name,
                    'color': item.color,
                    'size': item.size,
                    'quantity': 0
                }
            apparel_totals[key]['quantity'] += item.quantity

    apparel_list = sorted(
        apparel_totals.values(),
        key=lambda x: (x['section'], x['style_number'], x['color'], x['size']),
    )

    # Design/logo totals (grouped by design, placement, print size)
    from utils.print_sizes import production_from_order_item
    from utils.order_artwork import back_print_url
    from utils.size_codes import size_code
    from utils.back_logo_size import back_logo_dims
    from utils.dtf_orders import _back_logo_name
    design_groups = {}
    personal_list = []
    merged_images = {}
    from utils.order_artwork import preload_order_items, items_of
    preload_order_items(orders)
    for order in orders:
        for item in items_of(order):
            prod = production_from_order_item(item, customer_name=order.full_name)
            code = size_code(item.size, getattr(item, 'product', None))
            front = (prod or {}).get('front')
            if front:
                pw = front.get('width')
                ph = front.get('height')
                key = (item.design_id, item.placement or '', round(pw or 0, 2), round(ph or 0, 2))
                if key not in design_groups:
                    design_groups[key] = {
                        'design': item.design,
                        'design_name': front.get('design_name'),
                        'placement': item.placement or '-',
                        'print_width': pw,
                        'print_height': ph,
                        'quantity': 0,
                        'sizes': {},
                    }
                design_groups[key]['quantity'] += item.quantity
                design_groups[key]['sizes'][code] = design_groups[key]['sizes'].get(code, 0) + item.quantity
            back = (prod or {}).get('back')
            if back:
                back = dict(back)
                back['print_url'] = back_print_url(item)
                back['order_id'] = order.id
                back['item_id'] = item.id
                back['size_code'] = code
                back['order_number'] = order.order_number
                if back.get('kind') == 'image':
                    dims = back_logo_dims(item)               # the width AND height to order
                    back.update({'logo_name': _back_logo_name(item).replace('Back design: ', '') or 'Back design',
                                 'logo_width_display': dims['width_display'], 'logo_height_display': dims['height_display'],
                                 'logo_exceeds': dims['exceeds_safe_area']})
                    # The same back picture at the same shirt size and print size is one file, ordered once with the total.
                    same = (back.get('print_url') or '', code, dims['width_display'], dims['height_display'])
                    if same in merged_images:
                        merged_images[same]['quantity'] = (merged_images[same].get('quantity') or 0) + (back.get('quantity') or 0)
                        merged_images[same]['order_number'] = 'weekly'
                        continue
                    merged_images[same] = back
                personal_list.append(back)

    design_list = sorted(design_groups.values(), key=lambda x: (getattr(x['design'], 'filename', '') or x.get('design_name') or '', x['placement']))
    from utils.size_codes import breakdown
    for group in design_list:
        group['sizes_text'] = breakdown(group['sizes'])

    master_files = _master_art_files(orders)
    art_files = [{'name': f['name'], 'url': url_for('admin.save_item_artwork', order_id=f['order'].id, item_id=f['item'].id,
                                                    side=f['side'], inline=1, name=f['name'])} for f in master_files]
    by_key = {f['key']: f for f in master_files if f.get('key')}
    for key, group in design_groups.items():                 # each logo card shows, and downloads under, its sized file name
        match = by_key.get(key)
        if match:
            group['file_name'] = match['name']
            group['file_url'] = url_for('admin.save_item_artwork', order_id=match['order'].id, item_id=match['item'].id,
                                        side='front', name=match['name'])
            group['preview_url'] = url_for('admin.save_item_artwork', order_id=match['order'].id, item_id=match['item'].id,
                                           side='front', name=match['name'], inline=1)
    for row in personal_list:                                 # and so does each name / back picture
        if row.get('order_id') and row.get('item_id'):
            from utils.production_images import file_name as _file_name
            if row.get('kind') == 'image':
                label = 'back-' + (row.get('logo_name') or 'design')
                width, height = row.get('logo_width_display'), row.get('logo_height_display')
            else:
                label = 'back-' + ' '.join(p for p in (row.get('name'), str(row.get('number') or '')) if p)
                width, height = row.get('combined_width'), row.get('combined_height')
            row['file_name'] = _file_name(row.get('size_code'), width, height, label, row.get('quantity'), row.get('order_number'))
            row['preview_url'] = url_for('admin.save_item_artwork', order_id=row['order_id'], item_id=row['item_id'], side='back',
                                         name=row['file_name'], inline=1)
    collections = Collection.query.all()

    return render_template('admin/production_master.html',
                         art_files=art_files,
                         waiting_count=waiting_count,
                         orders=orders,
                         apparel_list=apparel_list,
                         design_list=design_list,
                         personal_list=personal_list,
                         collections=collections,
                         selected_status=stages,
                         selected_collection=collection_id)


@admin_bp.route('/production/transfers')
@admin_required
def transfer_production():
    """Printable / filterable press sheet across selected orders."""
    from utils.ops_flow import ops_order_query, current_collection, ops_url
    from utils.production_stages import orders_for_stages

    # On-screen press sheet: Ready to Press + Pressed (hand to the presser).
    query, stages, collection_id = ops_order_query(['ready_to_press', 'pressed'])
    group_by = request.args.get('group', 'label')

    if request.args.get('format') == 'csv':
        # CSV is for transfer sizing — include every open order that still needs
        # a press (new orders included). The page filter of Ready to Press alone
        # left first orders as an empty header-only download.
        csv_stages = [
            'order_received', 'waiting_supplies', 'ready_to_press', 'pressed',
        ]
        csv_query = orders_for_stages(csv_stages)
        cid = request.args.get('collection') or current_collection() or None
        if cid:
            from utils.group_orders import filter_orders_to_collection
            csv_query = filter_orders_to_collection(csv_query, cid)
        csv_orders = csv_query.order_by(Order.created_at).all()
        from utils.print_sizes import group_production_rows
        rows = group_production_rows(
            _collect_order_productions(csv_orders), group_by=group_by,
        )
        if not rows:
            flash(
                'No transfer rows yet. Orders need shirts with a design or name/number '
                'before a press CSV can be built.',
                'info',
            )
            return redirect(ops_url(
                'admin.transfer_production',
                stage=stages,
                group=group_by,
                collection=cid,
            ))
        return _transfer_csv_response(
            rows, f'transfers_{datetime.now().strftime("%Y%m%d")}.csv',
        )

    orders = query.order_by(Order.created_at).all()
    shirts = _sort_press_shirts(_collect_press_shirts(orders), group_by=group_by)
    collections = Collection.query.all()
    return render_template(
        'admin/transfer_production.html',
        title='Transfer Production Summary',
        order=None,
        shirts=shirts,
        group_by=group_by,
        orders=orders,
        collections=collections,
        selected_status=stages,
        selected_collection=collection_id,
        printable=True,
    )


@admin_bp.route('/production/master/move-to-production', methods=['POST'])
@admin_required
def production_master_move():
    """Two quick moves. 'ordered': these new orders are bought, so they wait on supplies.
    'arrived': the boxes are in, so the waiting orders are ready to press."""
    from utils.ops_flow import ops_order_query_for, ops_url
    from utils.production_stages import apply_stage
    which = request.form.get('which') if request.form.get('which') in ('ordered', 'arrived') else 'ordered'
    source, target = (['order_received'], 'waiting_supplies') if which == 'ordered' else (['waiting_supplies'], 'ready_to_press')
    query, _stages, collection_id = ops_order_query_for(source)
    cid = request.form.get('collection') or collection_id
    if cid:
        from utils.group_orders import filter_orders_to_collection
        query = filter_orders_to_collection(query, cid)

    from utils.proofs import blocked_reason
    count = 0
    for order in query.all():
        if blocked_reason(order, target):
            continue                                  # still waiting on the customer's proof approval
        apply_stage(order, target)
        count += 1

    try:
        db.session.commit()
        if which == 'ordered':
            flash(f'Moved {count} order(s) to Waiting on Supplies. They will stay off the weekly lists now.' if count
                  else 'There were no new orders to move.', 'success' if count else 'info')
        else:
            flash(f'Moved {count} order(s) to Ready to Press. Next up: press sheets.' if count
                  else 'No orders were waiting on supplies.', 'success' if count else 'info')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('production_master_move commit failed: %s', e)
        flash('Could not move orders. Please try again.', 'error')
    if which == 'ordered':
        return redirect(ops_url('admin.production_master', stage=['order_received'], collection=cid))
    return redirect(ops_url('admin.transfer_production', stage=['ready_to_press'], collection=cid))


@admin_bp.route('/production/blank-apparel-list')
@admin_required
def blank_apparel_list():
    """Weekly blank shopping list — nothing is purchased until you check out at S&S/SanMar."""
    from utils.ops_flow import ops_order_query_for
    from utils.blank_orders import build_blank_shopping_list
    # New orders only: anything waiting on supplies was already ordered from the vendors.
    query, _stages, collection_id = ops_order_query_for(['order_received'])
    orders = query.all()
    shopping = build_blank_shopping_list(orders)

    if request.args.get('format') == 'csv':
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=['vendor', 'brand', 'style_number', 'product_name', 'color', 'size', 'quantity'],
        )
        writer.writeheader()
        writer.writerows(shopping['flat'])
        response = BytesIO(output.getvalue().encode('utf-8'))
        return send_file(
            response,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'blank_apparel_list_{datetime.now().strftime("%Y%m%d")}.csv',
        )

    if request.args.get('format') in ('xlsx', 'excel'):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = 'Blank shopping list'
        headers = ['vendor', 'brand', 'style_number', 'product_name', 'color', 'size', 'quantity']
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in shopping['flat']:
            ws.append([row.get(h, '') for h in headers])

        # Size columns to fit content so free Excel / Excel Online opens readable
        for col_idx, header in enumerate(headers, start=1):
            letter = get_column_letter(col_idx)
            max_len = len(header)
            for cell in ws[letter]:
                val = '' if cell.value is None else str(cell.value)
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 48)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'blank_apparel_list_{datetime.now().strftime("%Y%m%d")}.xlsx',
        )

    collections = Collection.query.all()
    return render_template(
        'admin/blank_apparel_list.html',
        vendors=shopping['vendors'],
        all_copy=shopping['all_copy'],
        total_quantity=shopping['total_quantity'],
        total_cost=shopping['total_cost'],
        style_count=shopping['style_count'],
        order_count=len(orders),
        collections=collections,
    )


@admin_bp.route('/orders/<int:order_id>/receipt')
@admin_required
def order_receipt(order_id):
    """A printable receipt (or invoice, when a balance is due) with the business details and logo.

    Optional ?company=, ?attn=, ?po=, ?note= and ?kind=receipt|invoice fill in the
    "Billed to" block, so a company that needs one can get it in seconds.
    """
    from utils.business_info import BUSINESS, PAYMENT_METHODS
    from utils.receipts import doc_from_order
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_receipt.html', doc=doc_from_order(order, request.args), business=BUSINESS,
                           payment_methods=PAYMENT_METHODS, order=order, invoice=None)


@admin_bp.route('/orders/<int:order_id>/packing-slip')
@admin_required
def order_packing_slip(order_id):
    """The slip that goes in the box. Prices stay off when the customer asked for that (a gift)."""
    from utils.business_info import BUSINESS
    order = Order.query.get_or_404(order_id)
    return render_template('admin/packing_slip.html', order=order, business=BUSINESS,
                           show_prices=not order.gift_hide_prices)


@admin_bp.route('/orders/<int:order_id>/gift-card')
@admin_required
def order_gift_card(order_id):
    """A small card with the gift message, ready to print and tuck in the box."""
    from utils.business_info import BUSINESS
    from flask import abort
    order = Order.query.get_or_404(order_id)
    if not order.is_gift:
        abort(404)
    return render_template('admin/gift_card.html', order=order, business=BUSINESS)


# -- Hand-made invoices and receipts (orders taken directly, any brand) --------

def _invoice_fields(inv=None):
    """Form values for the invoice page: the saved invoice, or sensible blanks."""
    from utils.receipts import parse_items
    from datetime import datetime as _dt
    if inv is None:
        return {'customer_name': '', 'company': '', 'attn': '', 'po': '', 'email': '', 'phone': '', 'address': '',
                'note': '', 'lines': [], 'tax_rate': '%g' % sales_tax.rate_percent(), 'shipping': '', 'discount': '', 'amount_paid': '',
                'payment_method': '', 'kind': 'auto', 'issued': _dt.now().strftime('%Y-%m-%d')}
    fmt = lambda v: ('%g' % v) if v else ''
    issued = (inv.issued_at or inv.created_at or _dt.now()).strftime('%Y-%m-%d')
    return {'customer_name': inv.customer_name or '', 'company': inv.company or '', 'attn': inv.attn or '',
            'po': inv.po or '', 'email': inv.email or '', 'phone': inv.phone or '', 'address': inv.address or '',
            'note': inv.note or '', 'lines': parse_items(inv.items_json), 'tax_rate': '%g' % (inv.tax_rate or 0),
            'shipping': fmt(inv.shipping), 'discount': fmt(inv.discount), 'amount_paid': fmt(inv.amount_paid),
            'payment_method': inv.payment_method or '', 'kind': inv.kind or 'auto', 'issued': issued}


def _read_invoice_form(form):
    """(values, error) from a submitted invoice form."""
    from utils.receipts import parse_items

    def num(name):
        try:
            return max(float((form.get(name) or '').strip() or 0), 0.0)
        except ValueError:
            return 0.0
    values = {
        'customer_name': (form.get('customer_name') or '').strip()[:200],
        'company': (form.get('company') or '').strip()[:200],
        'attn': (form.get('attn') or '').strip()[:200],
        'po': (form.get('po') or '').strip()[:80],
        'email': (form.get('email') or '').strip()[:200],
        'phone': (form.get('phone') or '').strip()[:40],
        'address': (form.get('address') or '').strip()[:400],
        'note': (form.get('note') or '').strip()[:400],
        'lines': parse_items(form.get('items_json') or '[]'),
        'tax_rate': min(num('tax_rate'), 30.0), 'shipping': num('shipping'), 'discount': num('discount'),
        'amount_paid': num('amount_paid'),
        'payment_method': (form.get('payment_method') or '').strip()[:40],
        'kind': form.get('kind') if form.get('kind') in ('invoice', 'receipt') else 'auto',
        'issued': (form.get('issued') or '').strip(),
    }
    if not values['customer_name']:
        return values, 'Please add a name for the invoice.'
    if not values['lines']:
        return values, 'Please add at least one item with a quantity and a description.'
    return values, None


def _save_invoice(inv, v):
    from datetime import datetime as _dt
    inv.customer_name, inv.company, inv.attn, inv.po = v['customer_name'], v['company'], v['attn'], v['po']
    inv.email, inv.phone, inv.address, inv.note = v['email'], v['phone'], v['address'], v['note']
    inv.items_json = json.dumps(v['lines'])
    inv.tax_rate, inv.shipping, inv.discount = v['tax_rate'], v['shipping'], v['discount']
    inv.amount_paid, inv.payment_method, inv.kind = v['amount_paid'], v['payment_method'], v['kind']
    if (inv.amount_paid or 0) > 0 and not inv.paid_at:
        inv.paid_at = _dt.utcnow()                      # the day money first came in, for the cash-basis books
    try:
        inv.issued_at = _dt.strptime(v['issued'], '%Y-%m-%d')
    except ValueError:
        inv.issued_at = inv.issued_at or _dt.utcnow()


@admin_bp.route('/invoices')
@admin_required
def invoices():
    from models import ManualInvoice
    from utils.receipts import doc_from_invoice
    rows = [{'inv': inv, 'doc': doc_from_invoice(inv)}
            for inv in ManualInvoice.query.order_by(ManualInvoice.created_at.desc(), ManualInvoice.id.desc()).all()]
    return render_template('admin/invoices.html', rows=rows)


@admin_bp.route('/invoices/new', methods=['GET', 'POST'])
@admin_required
def invoice_new():
    from models import ManualInvoice
    from sqlalchemy.exc import IntegrityError
    from utils.receipts import next_invoice_number
    from datetime import datetime as _dt
    if request.method == 'POST':
        values, error = _read_invoice_form(request.form)
        if error:
            return render_template('admin/invoice_form.html', inv=None, f={**_invoice_fields(), **values}, error=error)
        for _attempt in range(3):        # two quick saves could pick the same number
            inv = ManualInvoice(number=next_invoice_number(db.session, ManualInvoice, _dt.now().year))
            _save_invoice(inv, values)
            db.session.add(inv)
            try:
                db.session.commit()
                break
            except IntegrityError:
                db.session.rollback()
        else:
            flash('Could not save the invoice. Please try again.', 'error')
            return redirect(url_for('admin.invoice_new'))
        return redirect(url_for('admin.invoice_view', invoice_id=inv.id))
    return render_template('admin/invoice_form.html', inv=None, f=_invoice_fields(), error=None)


@admin_bp.route('/invoices/<int:invoice_id>')
@admin_required
def invoice_view(invoice_id):
    from models import ManualInvoice
    from utils.business_info import BUSINESS, PAYMENT_METHODS
    from utils.receipts import doc_from_invoice
    inv = ManualInvoice.query.get_or_404(invoice_id)
    from utils.invoice_pay import pay_url, sms_href
    link = pay_url(inv) if inv.pay_token else None
    if not inv.review_token:                       # every invoice gets its own review link
        import secrets
        inv.review_token = secrets.token_urlsafe(24)
        db.session.commit()
    review_link = url_for('main.review_invoice', token=inv.review_token, _external=True)
    return render_template('admin/order_receipt.html', doc=doc_from_invoice(inv), business=BUSINESS,
                           payment_methods=PAYMENT_METHODS, invoice=inv, order=None,
                           pay_link=link, sms_link=sms_href(inv) if link and inv.phone else None,
                           review_link=review_link)


@admin_bp.route('/invoices/<int:invoice_id>/pdf')
@admin_required
def invoice_pdf(invoice_id):
    """One-page PDF of the invoice, or of the receipt once it is paid. Prints on a single sheet."""
    from models import ManualInvoice
    from utils.invoice_pay import receipt_pdf_bytes
    inv = ManualInvoice.query.get_or_404(invoice_id)
    return Response(receipt_pdf_bytes(inv), mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{inv.number}.pdf"'})


@admin_bp.route('/invoices/<int:invoice_id>/pay-link', methods=['POST'])
@admin_required
def invoice_pay_link(invoice_id):
    """Turn the customer's pay-online link on, or off (it stops working at once)."""
    from models import ManualInvoice
    from utils.invoice_pay import ensure_token, turn_off
    inv = ManualInvoice.query.get_or_404(invoice_id)
    if request.form.get('action') == 'off':
        turn_off(inv)
        flash('The pay link is turned off. The old link no longer works.', 'success')
    else:
        ensure_token(inv)
        flash('Pay link is ready. You can email it, text it, or show the QR code.', 'success')
    return redirect(url_for('admin.invoice_view', invoice_id=inv.id))


@admin_bp.route('/invoices/<int:invoice_id>/send', methods=['POST'])
@admin_required
def invoice_send(invoice_id):
    """Email the customer the invoice with a Pay button."""
    from datetime import datetime as _dt
    from models import ManualInvoice
    from utils import invoice_emails
    from utils.invoice_pay import ensure_token
    inv = ManualInvoice.query.get_or_404(invoice_id)
    if not (inv.email or '').strip() or '@' not in inv.email:
        flash('Add the customer\'s email to this invoice first (Edit), then send it.', 'error')
        return redirect(url_for('admin.invoice_view', invoice_id=inv.id))
    ensure_token(inv)
    if invoice_emails.send_invoice(inv):
        inv.pay_link_sent_at = _dt.utcnow()
        db.session.commit()
        flash(f'Invoice emailed to {inv.email}.', 'success')
    else:
        flash('The email could not be sent. Please check your email settings, or copy the link and text it.', 'error')
    return redirect(url_for('admin.invoice_view', invoice_id=inv.id))


@admin_bp.route('/invoices/<int:invoice_id>/edit', methods=['GET', 'POST'])
@admin_required
def invoice_edit(invoice_id):
    from models import ManualInvoice
    inv = ManualInvoice.query.get_or_404(invoice_id)
    if request.method == 'POST':
        values, error = _read_invoice_form(request.form)
        if error:
            return render_template('admin/invoice_form.html', inv=inv, f={**_invoice_fields(inv), **values}, error=error)
        _save_invoice(inv, values)
        db.session.commit()
        from utils.bulk_orders import sync_order_from_invoice
        sync_order_from_invoice(inv)      # a bulk order follows what its invoice says is paid
        return redirect(url_for('admin.invoice_view', invoice_id=inv.id))
    return render_template('admin/invoice_form.html', inv=inv, f=_invoice_fields(inv), error=None)


@admin_bp.route('/invoices/<int:invoice_id>/delete', methods=['POST'])
@admin_required
def invoice_delete(invoice_id):
    from models import ManualInvoice
    inv = ManualInvoice.query.get_or_404(invoice_id)
    number = inv.number
    db.session.delete(inv)
    db.session.commit()
    flash(f'{number} deleted.', 'success')
    return redirect(url_for('admin.invoices'))


@admin_bp.route('/orders/print-labels')
@admin_required
def print_labels():
    """Generate printable order labels for sticker paper (3 columns × 10 rows = 30 per sheet)"""
    from utils.production_stages import STAGES, orders_for_stages
    collection_id = request.args.get('collection')
    order_id = request.args.get('order_id', type=int)
    # Most of the time you print labels for everything that is ready to press; pick other stages when you need them.
    stage_filter = request.args.getlist('stage') or ['ready_to_press']

    if order_id:
        query = Order.query.filter_by(id=order_id)
    else:
        query = orders_for_stages(stage_filter)
        if collection_id:
            from utils.group_orders import filter_orders_to_collection
            query = filter_orders_to_collection(query, collection_id)

    from utils.ops_flow import packing_sort_key

    def _logo_label(item):
        design = getattr(item, 'design', None)
        title = (getattr(design, 'title', None) or '').strip() if design else ''
        if title:
            return title
        raw = (item.design_file_name or '').strip()
        if not raw:
            return ''
        raw = raw.replace('\\', '/').split('/')[-1]
        if '.' in raw:
            raw = raw.rsplit('.', 1)[0]
        return raw.replace('_', ' ').replace('-', ' ').strip()

    def _label_items(order):
        rows = []
        for item in order.items.all():
            product = getattr(item, 'product', None)
            brand = (getattr(product, 'brand', None) or '').strip() if product else ''
            rows.append({
                'qty': item.quantity or 1,
                'size': (item.size or '').strip(),
                'color': (item.color or '').strip(),
                'brand': brand,
                'style': (item.style_number or '').strip(),
                'logo': _logo_label(item),
            })
        return rows

    orders = sorted(query.all(), key=packing_sort_key)
    for order in orders:
        order.label_items = _label_items(order)
    collections = Collection.query.all()

    return render_template('admin/print_labels.html',
                         orders=orders,
                         collections=collections,
                         selected_status=stage_filter,
                         selected_collection=collection_id,
                         stages=STAGES)


@admin_bp.route('/production/bulk-sheet')
@admin_required
def production_bulk_sheet():
    """Bulk production sheet for orders ready to press or already pressed."""
    from utils.print_sizes import get_print_width_for_size
    from utils.ops_flow import ops_order_query

    query, _stages, _collection_id = ops_order_query(['ready_to_press', 'pressed'])
    orders = query.order_by(Order.created_at).all()
    
    # Group by design + placement, aggregate by (size, print_width) so youth vs adult are separate
    groups = {}
    from utils.order_artwork import preload_order_items, items_of
    preload_order_items(orders)
    for order in orders:
        for item in items_of(order):
            if not item.design_id:
                continue
            key = (item.design_id, item.placement or '')
            if key not in groups:
                groups[key] = {
                    'design': item.design,
                    'placement': item.placement or '-',
                    'size_qty': {},  # (size, print_width) -> qty
                    'items': [],
                    'total_qty': 0
                }
            size = item.size or 'One Size'
            pw = get_print_width_for_size(size, item.product) or item.print_width
            size_key = (size, pw)
            groups[key]['size_qty'][size_key] = groups[key]['size_qty'].get(size_key, 0) + item.quantity
            groups[key]['items'].append(item)
            groups[key]['total_qty'] += item.quantity
    
    bulk_list = list(groups.values())
    
    return render_template('admin/production_bulk_sheet.html',
                         bulk_list=bulk_list,
                         get_print_width=get_print_width_for_size)


@admin_bp.route('/production/dtf-batch-sheets')
@admin_required
def dtf_batch_sheets():
    """Weekly DTF shopping list — nothing is purchased until you check out on the DTF site."""
    from utils.ops_flow import ops_order_query_for
    from utils.dtf_orders import build_dtf_shopping_list
    # New orders only: anything waiting on supplies was already ordered from the vendors.
    query, _stages, collection_id = ops_order_query_for(['order_received'])
    orders = query.order_by(Order.created_at).all()
    shopping = build_dtf_shopping_list(orders)

    if request.args.get('format') == 'csv':
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=['kind', 'design_or_name', 'placement', 'order_by', 'size_in', 'height_in', 'quantity', 'sizes', 'order_number'],
        )
        writer.writeheader()
        writer.writerows(shopping['csv_rows'])
        return send_file(
            BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'dtf_shopping_list_{datetime.now().strftime("%Y%m%d")}.csv',
        )

    if request.args.get('format') in ('xlsx', 'excel'):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter

        headers = [
            'kind', 'design_or_name', 'placement', 'order_by',
            'size_in', 'height_in', 'quantity', 'sizes', 'order_number',
        ]
        wb = Workbook()
        ws = wb.active
        ws.title = 'DTF shopping list'
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in shopping['csv_rows']:
            ws.append([row.get(h, '') for h in headers])

        for col_idx, header in enumerate(headers, start=1):
            letter = get_column_letter(col_idx)
            max_len = len(header)
            for cell in ws[letter]:
                val = '' if cell.value is None else str(cell.value)
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 48)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'dtf_shopping_list_{datetime.now().strftime("%Y%m%d")}.xlsx',
        )

    collections = Collection.query.all()
    return render_template(
        'admin/dtf_batch_sheets.html',
        logos=shopping['logos'],
        personal=shopping['personal'],
        all_copy=shopping['all_copy'],
        logo_copy=shopping['logo_copy'],
        personal_copy=shopping['personal_copy'],
        logo_count=shopping['logo_count'],
        personal_count=shopping['personal_count'],
        logo_qty=shopping['logo_qty'],
        personal_qty=shopping['personal_qty'],
        order_count=shopping['order_count'],
        has_items=shopping['has_items'],
        collections=collections,
    )


@admin_bp.route('/production/logo-chart')
@admin_required
def logo_chart():
    """Printable master logo chart: 1, 1a, 1b for each group order."""
    from utils.ops_flow import ops_order_query
    from utils.logo_codes import back_logo_tiles, design_sides, extra_design_ids_from_orders, logo_families

    query, stages, collection_id = ops_order_query(
        ['order_received', 'waiting_supplies', 'ready_to_press', 'pressed']
    )
    orders = query.order_by(Order.created_at).all()
    all_collections = Collection.query.order_by(Collection.name).all()

    if collection_id:
        try:
            cid = int(collection_id)
        except (TypeError, ValueError):
            cid = None
        chosen = [c for c in all_collections if c.id == cid]
    else:
        cids = {order.collection_id for order in orders if order.collection_id}
        chosen = [c for c in all_collections if c.id in cids] if cids else [
            c for c in all_collections if c.allowed_design_ids
        ]

    charts = []
    for collection in chosen:
        extra = extra_design_ids_from_orders(orders, collection.id)
        families = logo_families(collection, extra)
        sides = design_sides(orders, collection.id)
        for family in families:
            for variant in family['variants']:
                variant['side'] = sides.get(variant['design_id'], 'front')
        back_tiles = back_logo_tiles(collection, orders)
        if families or back_tiles:
            charts.append({
                'collection': collection,
                'families': families,
                'back_tiles': back_tiles,
                'logo_count': sum(len(family['variants']) for family in families),
                'main_count': len(families),
            })

    return render_template(
        'admin/logo_chart.html',
        title='Logo chart',
        charts=charts,
        collections=all_collections,
        selected_status=stages,
        selected_collection=collection_id,
        printable=True,
    )
