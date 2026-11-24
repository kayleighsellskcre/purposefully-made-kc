"""Admin Orders: the order list, order detail, status changes, artwork previews, exports and the press sheet helpers.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
import csv
import json
from datetime import datetime
from io import BytesIO, StringIO

from flask import render_template, request, redirect, url_for, flash, current_app, send_file
from flask_login import current_user
from sqlalchemy import or_
from models import db, Collection, Order, OrderItem

from routes.admin import _form_money, admin_bp, admin_required  # noqa: E402


# ===== ORDERS =====

@admin_bp.route('/orders')
@admin_required
def orders():
    """Manage orders - Master Order Log"""
    from datetime import datetime
    from utils.production_stages import DONE_STATUSES, normalize_stage_arg, orders_for_stage
    status = request.args.get('stage') or request.args.get('status')
    collection_id = request.args.get('collection')
    order_type = request.args.get('order_type')
    page = request.args.get('page', 1, type=int)

    if status is None or status == '':
        # Orders opens on the board. A stage or status in the link keeps the list (filtered).
        redirect_args = {}
        if collection_id:
            redirect_args['collection'] = collection_id
        if order_type:
            redirect_args['order_type'] = order_type
        return redirect(url_for('admin.production_workflow', **redirect_args))

    stage = normalize_stage_arg(status)
    if stage == 'all':
        query = Order.query.filter(~Order.status.in_(DONE_STATUSES))
    else:
        query = orders_for_stage(stage)
    if collection_id:
        from utils.group_orders import filter_orders_to_collection
        query = filter_orders_to_collection(query, collection_id)
    if order_type:
        if order_type == 'retail':
            query = query.filter(or_(Order.order_type == 'retail', Order.order_type == None))
        else:
            query = query.filter_by(order_type=order_type)
    
    q = (request.args.get('q') or '').strip()
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'   # a typed % or _ is plain text
        query = query.filter(or_(
            Order.order_number.ilike(like, escape='\\'), Order.first_name.ilike(like, escape='\\'), Order.last_name.ilike(like, escape='\\'),
            Order.email.ilike(like, escape='\\'), (Order.first_name + ' ' + Order.last_name).ilike(like, escape='\\'),
        ))
    sort = request.args.get('sort') or 'newest'
    if sort == 'due':
        # Soonest due date first; orders with no due date go last.
        query = query.order_by(Order.due_date.is_(None), Order.due_date, Order.created_at)
    elif sort == 'oldest':
        query = query.order_by(Order.created_at)
    else:
        sort = 'newest'
        query = query.order_by(Order.created_at.desc())
    orders = query.paginate(page=page, per_page=20, error_out=False)
    
    # How many orders wait in each stage (same group and type filters), like the board's column counts.
    from utils.production_stages import STAGES
    from utils.group_orders import filter_orders_to_collection
    stage_counts = {}
    for sid, _name, _desc in STAGES:
        count_query = orders_for_stage(sid)
        if collection_id:
            count_query = filter_orders_to_collection(count_query, collection_id)
        if order_type == 'retail':
            count_query = count_query.filter(or_(Order.order_type == 'retail', Order.order_type == None))
        elif order_type:
            count_query = count_query.filter_by(order_type=order_type)
        stage_counts[sid] = count_query.count()
    stage_counts['all'] = sum(stage_counts.values())

    collections = Collection.query.all()
    try:
        from models import PaymentCapture
        unsaved_payment_count = (
            PaymentCapture.query
            .filter(PaymentCapture.order_id.is_(None), PaymentCapture.resolved_at.is_(None),
                    db.or_(PaymentCapture.amount.isnot(None), PaymentCapture.awaiting_collection.is_(True)))
            .count()
        )
    except Exception:
        db.session.rollback()
        unsaved_payment_count = 0
    
    from utils.production_stages import item_counts_for
    from utils.order_artwork import preload_order_items
    preload_order_items(orders.items, deep=False)
    return render_template('admin/orders.html', 
                         orders=orders,
                         item_counts=item_counts_for(orders.items),
                         collections=collections,
                         unsaved_payment_count=unsaved_payment_count,
                         selected_status=stage,
                         selected_collection=collection_id,
                         selected_order_type=order_type,
                         selected_sort=sort,
                         selected_q=q,
                         stage_counts=stage_counts,
                         now=datetime.utcnow())


@admin_bp.route('/orders/completed')
@admin_required
def orders_completed():
    """All completed/shipped orders — organized by month and year (removed from workflow)"""
    from collections import OrderedDict
    orders = Order.query.filter(
        Order.status.in_(['completed', 'shipped', 'picked_up'])
    ).order_by(Order.updated_at.desc()).all()
    # Group by (year, month)
    by_month = OrderedDict()
    for order in orders:
        # Use updated_at or created_at for grouping
        from utils.local_time import to_central
        dt = to_central(order.updated_at or order.created_at)      # month and year in Kansas City time
        key = (dt.year, dt.month)
        if key not in by_month:
            by_month[key] = []
        by_month[key].append(order)
    from utils.production_stages import item_counts_for
    return render_template('admin/orders_completed.html', by_month=by_month, item_counts=item_counts_for(orders))


@admin_bp.route('/orders/<int:order_id>')
@admin_required
def order_detail(order_id):
    """View order details"""
    from utils.print_sizes import get_print_width_for_size, production_from_order_item
    from utils.order_costs import apply_order_defaults, order_cost_breakdown, apply_calculated_cogs
    order = Order.query.get_or_404(order_id)
    try:
        if apply_order_defaults(order):
            db.session.commit()
    except Exception:
        db.session.rollback()
    def get_print_width(size, product=None):
        return get_print_width_for_size(size, product)
    def get_display_print_width(item):
        """Always use correct youth dimensions for display (fixes stored wrong values)."""
        return get_print_width_for_size(item.size, item.product) or item.print_width
    from utils.order_artwork import artwork_kit
    from utils.personalization_layout import snapshot_from_item, validate_snapshot_geometry
    item_productions = []
    for item in order.items:
        prod = production_from_order_item(item, customer_name=order.full_name)
        kit = artwork_kit(item, order=order)
        layout = None
        if kit.get('is_personalized_back'):
            snap = snapshot_from_item(item, customer_name=order.full_name)
            ok, failures = validate_snapshot_geometry(snap)
            layout = {
                'snapshot': snap,
                'ok': ok,
                'failures': failures,
                'needs_review': (not snap.get('complete')) or (not ok),
            }
        item_productions.append((item, prod, kit, layout))

    # Stripe / PayPal fee: fetched once from the processor, estimated until then.
    from utils.payment_fees import refresh_processing_fee, true_profit, profit_margin_pct, processor_label
    try:
        if refresh_processing_fee(order):
            db.session.commit()
    except Exception:
        db.session.rollback()

    # Admin-only cost breakdown (blank + DTF) — never exposed publicly
    cost_breakdown = order_cost_breakdown(order, item_productions=item_productions)
    # Keep the estimate current until real supplier costs are entered; after
    # that, leave the admin's actual numbers alone (profit still follows the fee).
    try:
        if not getattr(order, 'cogs_is_actual', False):
            changed = apply_calculated_cogs(order, cost_breakdown)
        else:
            new_profit = true_profit(order)
            changed = new_profit is not None and order.profit != new_profit
            if changed:
                order.profit = new_profit
        if changed:
            db.session.commit()
    except Exception:
        db.session.rollback()

    profit_summary = {
        'paid': float(order.total or 0),
        'tax': float(order.tax or 0),
        'fee': float(order.processing_fee or 0),
        'fee_is_actual': bool(order.processing_fee_is_actual),
        'processor': processor_label(order),
        'cogs': float(order.cost_of_goods or 0),
        'cogs_is_actual': bool(order.cogs_is_actual),
        'profit': true_profit(order),
        'margin_pct': profit_margin_pct(order),
    }

    from utils.bulk_orders import invoices_for_order
    return render_template(
        'admin/order_detail.html',
        order=order,
        bulk_invoices=invoices_for_order(order) if order.payment_method == 'invoice' else [],
        get_print_width=get_print_width,
        get_display_print_width=get_display_print_width,
        item_productions=item_productions,
        cost_breakdown=cost_breakdown,
        profit_summary=profit_summary,
    )


def _artwork_piece(side):
    if side == 'back-name':
        return 'name'
    if side == 'back-number':
        return 'number'
    return 'back'


@admin_bp.route('/orders/<int:order_id>/items/<int:item_id>/preview/<side>')
@admin_required
def preview_item_artwork(order_id, item_id, side):
    """Low-DPI preview for one render mode. Never builds a 300 DPI file."""
    from utils.name_number_art import generate_personalized_png
    from utils.order_artwork import local_file_for_url, piece_print_url
    from utils.personalization_layout import PREVIEW_DPI
    if side not in ('back', 'back-name', 'back-number'):
        return ('', 404)
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    piece = _artwork_piece(side)
    stored = piece_print_url(item, piece)
    local = local_file_for_url(current_app, stored) if stored else None
    if local:
        return send_file(local, mimetype='image/png', max_age=60)
    try:
        data, _snapshot = generate_personalized_png(
            current_app, item, piece, customer_name=order.full_name, dpi=PREVIEW_DPI,
        )
    except Exception as exc:
        current_app.logger.exception(
            'dtf preview-failed order=%s item=%s piece=%s: %s',
            order.id, item.id, piece, exc,
        )
        data = None
    if not data:
        data = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
            b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
    return send_file(BytesIO(data), mimetype='image/png', max_age=60)


@admin_bp.route('/orders/<int:order_id>/items/<int:item_id>/replace-artwork', methods=['POST'])
@admin_required
def replace_item_artwork(order_id, item_id):
    """Give an order line its print file again (the customer sent the artwork again, or it was lost)."""
    from utils.cloud_storage import r2_configured, store_upload
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    back = redirect(url_for('admin.order_detail', order_id=order.id))
    upload = request.files.get('artwork')
    ext = (upload.filename.rsplit('.', 1)[-1].lower() if upload and upload.filename and '.' in upload.filename else '')
    if not upload or ext not in ('png', 'jpg', 'jpeg', 'webp'):
        flash('Choose a PNG, JPG or WEBP file first.', 'error')
        return back
    url = store_upload(upload, 'designs', 'order')
    if r2_configured(current_app._get_current_object()) and not str(url).startswith('http'):
        flash('The file could not be saved to permanent storage, so nothing was changed. Please try again.', 'error')
        return back
    design = item.design
    if design is not None and not design.is_gallery:
        design.file_path = url                            # this customer's own upload: the print file is now the new one
    else:
        item.design_id = None                             # never overwrite a gallery design: this line gets its own file
        item.design_file_name = url
    db.session.commit()
    flash('Print file replaced. It is saved permanently.', 'success')
    return back


@admin_bp.route('/orders/<int:order_id>/items/<int:item_id>/save/<side>')
@admin_required
def save_item_artwork(order_id, item_id, side):
    """Download the transparent print file for a DTF upload."""
    from urllib.request import Request, urlopen
    from utils.order_artwork import (
        back_print_url,
        download_filename,
        front_print_url,
        labeled_png,
        local_file_for_url,
        remote_url_allowed,
    )
    if side not in ('front', 'back', 'back-name', 'back-number'):
        flash('Unknown artwork side.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    if side in ('back', 'back-name', 'back-number') and (
        side != 'back' or (getattr(item, 'back_design_details', None) or {}).get('name')
        or (getattr(item, 'back_design_details', None) or {}).get('number')
    ):
        from utils.personalization_layout import snapshot_for_piece, validate_snapshot_png
        from utils.name_number_art import generate_personalized_png, persist_piece_file
        meta = item.back_design_details or {}
        personalized = bool(meta.get('name') or meta.get('number'))
        inline = request.args.get('inline')
        if personalized or side in ('back-name', 'back-number'):
            piece = _artwork_piece(side)
            try:
                data, snapshot = generate_personalized_png(
                    current_app, item, piece, customer_name=order.full_name,
                )
            except Exception as exc:
                current_app.logger.exception(
                    'personalized png failed order=%s item=%s piece=%s: %s',
                    order.id, item.id, piece, exc,
                )
                flash(f'Could not build the {piece} transfer: {exc}', 'error')
                return redirect(url_for('admin.order_detail', order_id=order.id))
            if not data:
                flash(f'Could not build a {piece} file for this order.', 'error')
                return redirect(url_for('admin.order_detail', order_id=order.id))
            ok, failures = validate_snapshot_png(snapshot_for_piece(snapshot, piece), data)
            approved = request.args.get('approved') == '1' or bool(meta.get('production_approved'))
            if not ok and not approved:
                flash(
                    'This transfer failed production checks: '
                    + '; '.join(f"{f['label']} (expected {f['expected']}, got {f['actual']})" for f in failures),
                    'error',
                )
                return redirect(url_for('admin.order_detail', order_id=order.id))
            try:
                persist_piece_file(current_app, item, piece, data)
            except Exception:
                current_app.logger.exception(
                    'dtf persist-failed order=%s item=%s piece=%s',
                    order.id, item.id, piece,
                )
            filename = download_filename(order, item, side, request.args.get('name'))
            if not request.args.get('plain'):
                data = labeled_png(data, filename)               # the size label is part of the saved picture
            return send_file(
                BytesIO(data),
                as_attachment=not inline,
                download_name=filename,
                mimetype='image/png',
            )
    url = front_print_url(item) if side == 'front' else back_print_url(item)
    if not url:
        flash('No print file is saved for that side.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order.id))
    filename = download_filename(order, item, side, request.args.get('name'))
    local = local_file_for_url(current_app, url)
    inline = request.args.get('inline')
    if local:
        if request.args.get('plain'):
            return send_file(local, as_attachment=not inline, download_name=filename)
        with open(local, 'rb') as handle:
            return send_file(BytesIO(labeled_png(handle.read(), filename)), as_attachment=not inline, download_name=filename, mimetype='image/png')
    fetch_url = url
    if url.startswith('/'):
        fetch_url = request.host_url.rstrip('/') + url
    if fetch_url.startswith(('http://', 'https://')) and (
        remote_url_allowed(current_app, fetch_url, request.host_url) or url.startswith('/')
    ):
        try:
            req = Request(fetch_url, headers={'User-Agent': 'PMKC-Admin/1.0'})
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
                mime = resp.headers.get('Content-Type') or 'image/png'
            if not request.args.get('plain'):
                labeled = labeled_png(data, filename)
                if labeled is not data:
                    data, mime = labeled, 'image/png'
            return send_file(BytesIO(data), as_attachment=not inline, download_name=filename, mimetype=mime)
        except Exception:
            current_app.logger.exception('artwork download failed for order %s item %s %s', order_id, item_id, side)
    flash('Could not download that print file. Open the image and save it from the browser.', 'error')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/orders/<int:order_id>/items/<int:item_id>/photos/<side>')
@admin_required
def photos_item_artwork(order_id, item_id, side):
    """Mobile page: show the 300 DPI PNG so it can be saved to Photos."""
    from utils.order_artwork import download_filename
    if side not in ('front', 'back', 'back-name', 'back-number'):
        flash('Unknown artwork side.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    labels = {
        'front': 'Front transfer',
        'back': 'Combined back layout',
        'back-name': 'Back name',
        'back-number': 'Back number',
    }
    return render_template(
        'admin/save_to_photos.html',
        order=order,
        item=item,
        side=side,
        label=labels[side],
        filename=download_filename(order, item, side),
        image_url=url_for('admin.save_item_artwork', order_id=order.id, item_id=item.id, side=side, inline=1),
        download_url=url_for('admin.save_item_artwork', order_id=order.id, item_id=item.id, side=side),
    )


@admin_bp.route('/orders/<int:order_id>/items/<int:item_id>/approve-layout', methods=['POST'])
@admin_required
def approve_item_layout(order_id, item_id):
    """Admin reviewed the reconstructed DTF against the customer mockup."""
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    meta = dict(item.back_design_details or {})
    meta['production_approved'] = True
    meta['needs_review'] = False
    item.back_design_meta = json.dumps(meta)
    stored = item.transfer_production_details or {}
    if stored.get('back'):
        stored = dict(stored)
        stored['back'] = dict(stored['back'])
        stored['back']['needs_review'] = False
        stored['back']['production_approved'] = True
        item.transfer_production = json.dumps(stored)
    db.session.commit()
    flash('Layout approved. You can now save the production PNG.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order.id))


def _collect_press_shirts(orders):
    """One card per physical shirt: front and back stay together."""
    from utils.print_sizes import production_from_order_item
    from utils.order_artwork import front_print_url, mockup_urls, back_print_url
    from utils.ops_flow import packing_sort_key
    from utils.order_artwork import preload_order_items, items_of
    preload_order_items(orders)
    shirts = []
    for order in orders:
        customer_name = (order.full_name or '').strip() or (order.email or 'Customer')
        packing = packing_sort_key(order)
        pending = []
        items = items_of(order)
        for item_seq, item in enumerate(items):
            prod = production_from_order_item(item, customer_name=customer_name)
            # If no design is linked (manually-created orders), still show the
            # shirt card on the press sheet with a "no design" warning so it
            # isn't silently dropped.
            no_design = not prod or (not prod.get('front') and not prod.get('back'))
            if no_design:
                print_type = (getattr(item, 'print_type', None) or '').upper()
                if print_type not in ('DTF', 'SCREEN', 'VINYL', 'SUBLIMATION'):
                    continue  # truly nothing to press — skip
                # Build a minimal stub so the card renders with a warning
                prod = {
                    'front': {
                        'kind': 'standard',
                        'design_name': '⚠️ NO DESIGN LINKED — attach manually',
                        'design_id': None,
                        'garment_style': getattr(item, 'product_name', None),
                        'age_group': None,
                        'size': getattr(item, 'size', None),
                        'color': getattr(item, 'color', None),
                        'placement': getattr(item, 'placement', None) or 'center_chest',
                        'placement_label': 'Center Chest',
                        'order_by': 'WIDTH',
                        'width': None,
                        'height': None,
                        'width_display': '?',
                        'height_display': '?',
                        'exceeds_safe_area': False,
                        'quantity': getattr(item, 'quantity', 1) or 1,
                    },
                    'back': None,
                }
            pending.append((item_seq, item, prod, getattr(item, 'quantity', 1) or 1))
        piece_total = sum(qty for _seq, _item, _prod, qty in pending)
        piece_index = 0
        for item_seq, item, prod, qty in pending:
            front_m, back_m = mockup_urls(getattr(item, 'product', None), getattr(item, 'color', None))
            front = prod.get('front') or None
            back = prod.get('back') or None
            for copy_index in range(qty):
                piece_index += 1
                shirts.append({
                    'order_number': getattr(order, 'order_number', None),
                    'customer_name': customer_name,
                    'child_name': (getattr(order, 'child_name', None) or '').strip(),
                    'send_home': bool(getattr(order, 'send_home_with_child', False)),
                    'quantity': 1,
                    'piece_index': piece_index,
                    'piece_total': piece_total,
                    'item_seq': item_seq,
                    'copy_index': copy_index,
                    'packing_sort': packing,
                    'size': getattr(item, 'size', None),
                    'color': getattr(item, 'color', None),
                    'age_group': (front or back or {}).get('age_group'),
                    'garment_style': getattr(item, 'product_name', None),
                    'style_number': getattr(item, 'style_number', None),
                    'front': front,
                    'back': back,
                    'front_mockup_url': front_m,
                    'back_mockup_url': back_m or front_m,
                    'front_overlay_url': front_print_url(item) if front else None,
                    'back_overlay_url': back_print_url(item) if (back and back.get('kind') == 'image') else None,
                    'front_placement': getattr(item, 'placement', None) or (front or {}).get('placement') or 'center_chest',
                    'design_id': getattr(item, 'design_id', None),
                    'collection_id': getattr(order, 'collection_id', None),
                    'exceeds_safe_area': bool(
                        (front or {}).get('exceeds_safe_area') or (back or {}).get('exceeds_safe_area')
                    ),
                })
    from utils.logo_codes import stamp_logo_codes
    stamp_logo_codes(orders, shirts)
    return shirts


def _sort_press_shirts(shirts, group_by='label'):
    def key(shirt):
        back = shirt.get('back') or {}
        front = shirt.get('front') or {}
        name = back.get('name') or front.get('design_name') or ''
        packing = shirt.get('packing_sort') or ()
        item_seq = shirt.get('item_seq') or 0
        copy_index = shirt.get('copy_index') or 0
        if group_by == 'garment':
            return (shirt.get('garment_style') or '', shirt.get('size') or '', packing, item_seq, copy_index)
        if group_by == 'name':
            return (name, shirt.get('size') or '', packing, item_seq, copy_index)
        if group_by == 'order':
            return (shirt.get('order_number') or '', packing, item_seq, copy_index)
        if group_by == 'size':
            return (shirt.get('age_group') or '', shirt.get('size') or '', packing, item_seq, copy_index)
        return (packing, item_seq, copy_index)
    return sorted(shirts, key=key)


def _collect_order_productions(orders):
    from utils.print_sizes import production_from_order_item, flatten_production_rows
    from utils.order_artwork import front_print_url, mockup_urls, resolve_print_url
    from utils.order_artwork import preload_order_items, items_of
    preload_order_items(orders)
    productions = []
    for order in orders:
        for item in items_of(order):
            prod = production_from_order_item(item, customer_name=order.full_name)
            if not prod:
                continue
            front_m, back_m = mockup_urls(getattr(item, 'product', None), getattr(item, 'color', None))
            prod['mockup_front_url'] = front_m
            prod['mockup_back_url'] = back_m
            prod['front_overlay_url'] = front_print_url(item)
            prod['front_proof_url'] = resolve_print_url(getattr(item, 'proof_image', None))
            prod['front_placement'] = getattr(item, 'placement', None)
            prod['order_number'] = getattr(order, 'order_number', None)
            productions.append(prod)
    return flatten_production_rows(productions)


def _transfer_csv_response(rows, filename):
    output = StringIO()
    fieldnames = [
        'section', 'kind', 'order_by', 'design_name', 'name', 'number', 'font', 'text_color',
        'garment_style', 'style_number', 'category', 'age_group', 'size', 'color', 'placement_label',
        'width', 'height', 'name_width', 'name_height', 'number_width', 'number_height',
        'number_digits', 'number_scale', 'number_scale_percent',
        'combined_width', 'combined_height', 'gap', 'condense_percent', 'exceeds_safe_area',
        'quantity',
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({
            'section': row.get('section'),
            'kind': row.get('kind'),
            'order_by': row.get('order_by'),
            'design_name': row.get('design_name'),
            'name': row.get('name'),
            'number': row.get('number'),
            'font': row.get('font'),
            'text_color': row.get('text_color'),
            'garment_style': row.get('garment_style'),
            'style_number': row.get('style_number'),
            'category': row.get('category') or row.get('age_group'),
            'age_group': row.get('age_group'),
            'size': row.get('size'),
            'color': row.get('color'),
            'placement_label': row.get('placement_label'),
            'width': row.get('width_display') if row.get('width_display') is not None else row.get('width'),
            'height': row.get('height_display') if row.get('height_display') is not None else row.get('height'),
            'name_width': row.get('name_width_display', row.get('name_width')),
            'name_height': row.get('name_height_display', row.get('name_height')),
            'number_width': row.get('number_width_display', row.get('number_width')),
            'number_height': row.get('number_height_display', row.get('number_height')),
            'number_digits': row.get('number_digits'),
            'number_scale': round(row['number_scale'], 3) if row.get('number_scale') is not None else '',
            'number_scale_percent': row.get('number_scale_percent') if row.get('number_scale_percent') is not None else 'none',
            'combined_width': row.get('combined_width_display', row.get('combined_width')),
            'combined_height': row.get('combined_height_display', row.get('combined_height')),
            'gap': row.get('gap_display', row.get('gap')),
            'condense_percent': row.get('condense_percent') if row.get('condense_percent') is not None else 'none',
            'exceeds_safe_area': 'YES' if row.get('exceeds_safe_area') else '',
            'quantity': row.get('quantity'),
        })
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )


@admin_bp.route('/orders/<int:order_id>/transfers')
@admin_required
def order_transfer_summary(order_id):
    order = Order.query.get_or_404(order_id)
    group_by = request.args.get('group', 'label')
    shirts = _sort_press_shirts(_collect_press_shirts([order]), group_by=group_by)
    return render_template(
        'admin/transfer_production.html',
        title=f'Order #{order.order_number} transfers',
        order=order,
        shirts=shirts,
        group_by=group_by,
        printable=True,
    )


@admin_bp.route('/orders/<int:order_id>/transfers.csv')
@admin_required
def order_transfer_csv(order_id):
    order = Order.query.get_or_404(order_id)
    rows = _collect_order_productions([order])
    return _transfer_csv_response(rows, f'transfers_{order.order_number}.csv')


@admin_bp.route('/orders/<int:order_id>/update-status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    """Update order production stage (maps to both status and production_stage)."""
    order = Order.query.get_or_404(order_id)
    stage = request.form.get('status')  # form field named 'status' but now holds stage value
    admin_notes = request.form.get('admin_notes')

    from utils.production_stages import MOVE_LABELS, apply_stage
    if not apply_stage(order, stage):
        flash('Could not update that stage', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))

    if admin_notes:
        order.admin_notes = admin_notes

    try:
        db.session.commit()
        flash(f'Order moved to: {MOVE_LABELS.get(stage, stage)}', 'success')
        from utils.customer_emails import notify_in_background
        notify_in_background([order.id], stage)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('update_order_status commit failed: %s', e)
        flash('Could not update the order status. Please try again.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))
    if stage in ('completed', 'shipped', 'picked_up'):
        return redirect(url_for('admin.orders_completed'))
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
@admin_required
def cancel_order(order_id):
    """Mark an order cancelled and tell the customer. Refunding the money is done in Stripe or PayPal."""
    order = Order.query.get_or_404(order_id)
    if order.status == 'cancelled':
        flash('That order is already cancelled.', 'info')
        return redirect(url_for('admin.order_detail', order_id=order_id))
    order.status = 'cancelled'
    order.production_stage = None
    db.session.commit()
    from utils.customer_emails import notify_cancelled
    notify_cancelled(order)
    paid = order.payment_status in ('paid', 'refunded') and not order.is_refunded
    note = ' Now refund the payment in Stripe or PayPal.' if paid else ''
    if order.payment_method == 'invoice':
        note = ' It was billed on an invoice: open the invoice to delete it or refund what was paid, so no reminders go out.'
    flash('Order cancelled and the customer was emailed.' + note, 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/tracking', methods=['POST'])
@admin_required
def order_tracking(order_id):
    """Save a tracking number. A new or changed number is emailed to the customer."""
    order = Order.query.get_or_404(order_id)
    number = ' '.join((request.form.get('tracking_number') or '').split())[:60]
    carrier = (request.form.get('carrier') or '').strip()
    carrier = carrier if carrier in ('USPS', 'UPS', 'FedEx', 'Other') else 'USPS'
    changed = (number != (order.tracking_number or '')) or (carrier != (order.carrier or ''))
    order.tracking_number = number or None
    order.carrier = carrier if number else None
    db.session.commit()
    if number and changed:
        from utils.customer_emails import send_tracking_email
        sent = send_tracking_email(order)
        flash('Tracking saved' + (' and emailed to the customer.' if sent else '. (No email was sent. Check email settings.)'), 'success')
    else:
        flash('Tracking saved.' if number else 'Tracking cleared.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/delete', methods=['POST'])
@admin_required
def delete_order(order_id):
    """Permanently delete an order and all its items."""
    order = Order.query.get_or_404(order_id)
    try:
        from models import ManualInvoice
        for inv in ManualInvoice.query.filter_by(order_id=order.id).all():
            inv.order_id = None          # the invoice (and any money on it) stays on file
        for item in order.items:
            db.session.delete(item)
        db.session.delete(order)
        db.session.commit()
        flash(f'Order #{order.order_number} has been permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Could not delete order: {e}', 'error')
    return redirect(url_for('admin.orders'))


@admin_bp.route('/test-email', methods=['POST'])
@admin_required
def test_email():
    """Send a test email to the admin address to verify SMTP is working.

    Names the exact missing variable rather than listing all three, so a
    misconfigured deployment can be fixed without guessing.
    """
    from flask_mail import Message as MailMessage
    from routes.checkout import _mail_sender

    missing = [
        name for name in ('MAIL_SERVER', 'MAIL_USERNAME', 'MAIL_PASSWORD')
        if not current_app.config.get(name)
    ]
    if missing:
        flash(
            'Mail is NOT configured. Add these to Railway → Variables, then redeploy: '
            + ', '.join(missing),
            'error',
        )
        return redirect(request.referrer or url_for('admin.dashboard'))

    recipient = current_app.config.get('ADMIN_EMAIL') or current_user.email or 'purposefullymadekc@gmail.com'
    redirect_note = current_app.config.get('MAIL_TEST_REDIRECT')
    body = (
        'Mail is configured correctly.\n\n'
        f'SMTP server  : {current_app.config.get("MAIL_SERVER")}:{current_app.config.get("MAIL_PORT")}\n'
        f'TLS          : {current_app.config.get("MAIL_USE_TLS")}\n'
        f'From         : {_mail_sender()}\n'
        f'Reply-to     : {current_app.config.get("ADMIN_EMAIL")}\n'
        f'Link base    : {current_app.config.get("ADMIN_BASE_URL")}\n'
        f'Test redirect: {redirect_note or "off (live sending)"}\n'
    )
    from utils.mailer import send as _send_mail
    msg = MailMessage(
        subject='Test email — Purposefully Made KC mail is working',
        recipients=[recipient],
        body=body,
        sender=_mail_sender(),
    )
    if _send_mail(current_app._get_current_object(), msg, description='admin mail test'):
        flash(f'Test email sent to {recipient} — check your inbox.', 'success')
    else:
        flash(
            'Mail send FAILED. The credentials are present but the SMTP relay '
            'rejected or timed out. Check the Railway deploy logs for the full error.',
            'error',
        )
    return redirect(request.referrer or url_for('admin.dashboard'))


@admin_bp.route('/orders/<int:order_id>/resend-email', methods=['POST'])
@admin_required
def resend_order_email(order_id):
    """Resend the customer confirmation email for an existing order."""
    try:
        from routes.checkout import send_order_confirmation_email
        order = Order.query.get_or_404(order_id)
        if not order.email:
            flash('This order has no customer email on file.', 'error')
            return redirect(url_for('admin.order_detail', order_id=order_id))
        sent = send_order_confirmation_email(order, force=True)
        if sent:
            flash(f'Confirmation email sent to {order.email}.', 'success')
        else:
            flash('Could not send — check that MAIL_SERVER, MAIL_USERNAME, and MAIL_PASSWORD are set in Railway Variables.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order_id))
    except Exception as e:
        current_app.logger.exception('resend_order_email failed for order_id=%s: %s', order_id, e)
        flash(f'Server error sending email: {e}', 'error')
        return redirect(url_for('admin.orders'))


@admin_bp.route('/orders/<int:order_id>/update-details', methods=['POST'])
@admin_required
def update_order_details(order_id):
    """Update order details: due_date, order_type, cost_of_goods, profit"""
    order = Order.query.get_or_404(order_id)
    order.due_date = None
    if request.form.get('due_date'):
        try:
            order.due_date = datetime.fromisoformat(request.form.get('due_date'))
        except ValueError:
            pass
    order.order_type = request.form.get('order_type') or 'retail'
    submitted_cogs = _form_money('cost_of_goods', None)
    if request.form.get('cogs_reset') == 'on' or submitted_cogs is None:
        # Back to the calculated estimate; the order page refills it on load.
        order.cogs_is_actual = False
        order.cost_of_goods = None
        order.profit = None
    else:
        submitted_cogs = round(submitted_cogs, 2)
        # Only lock in as "actual" when the number was actually changed, so
        # saving a due date or order type doesn't freeze the estimate.
        if order.cost_of_goods is None or abs(submitted_cogs - float(order.cost_of_goods)) > 0.004:
            order.cogs_is_actual = True
        order.cost_of_goods = submitted_cogs
        if order.total:
            from utils.payment_fees import true_profit
            order.profit = true_profit(order)
        else:
            order.profit = _form_money('profit', None)
    now_refunded = request.form.get('is_refunded') == 'on'
    if now_refunded and not order.is_refunded:
        order.refunded_at = datetime.utcnow()          # the day the refund counts in the books
    order.is_refunded = now_refunded
    if now_refunded:
        from utils.creator_credit import reverse_for_order
        reverse_for_order(order)
    order.refund_notes = request.form.get('refund_notes')
    db.session.commit()
    if now_refunded:
        from utils.customer_emails import notify_refund
        notify_refund(order.id)
    flash('Order details updated', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))
