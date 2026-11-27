"""Admin Inventory, background reprocess, Site Settings, packaging SOP, and the customers and marketing tracker.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
import os
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from models import (db, ApparelInventory, Collection, Design, Order, Supply, TransferInventory, User, Vendor)
from utils import sales_tax

from routes.admin import _form_money, admin_bp, admin_required  # noqa: E402


# ===== INVENTORY (DTF costs + stock counts) =====

@admin_bp.route('/inventory')
@admin_required
def inventory():
    """Inventory hub: DTF transfer cost settings used for order COGS."""
    from utils.order_costs import get_dtf_costs
    return render_template('admin/inventory.html', costs=get_dtf_costs())


@admin_bp.route('/inventory/save-costs', methods=['POST'])
@admin_required
def save_inventory_costs():
    """Persist DTF transfer pricing to data/costs.json (server-side only)."""
    from utils.order_costs import save_dtf_costs
    save_dtf_costs({
        'dtf_per_sq_in': request.form.get('dtf_per_sq_in'),
        'dtf_gang_sheet_per_foot': request.form.get('dtf_gang_sheet_per_foot'),
        'dtf_vendor': request.form.get('dtf_vendor'),
        'dtf_notes': request.form.get('dtf_notes'),
    })
    flash('DTF transfer costs saved.', 'success')
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory')
@admin_required
def operations_inventory():
    """Stock counts - apparel, transfers, supplies"""
    apparel = ApparelInventory.query.order_by(ApparelInventory.brand, ApparelInventory.color).all()
    transfers = TransferInventory.query.order_by(TransferInventory.design_name).all()
    supplies = Supply.query.order_by(Supply.category, Supply.name).all()
    vendors = Vendor.query.order_by(Vendor.name).all()
    from utils.low_stock import low_items
    return render_template('admin/operations/inventory.html',
                         apparel=apparel, transfers=transfers, supplies=supplies, vendors=vendors, low_count=len(low_items()))


@admin_bp.route('/operations/inventory/apparel/add', methods=['POST'])
@admin_required
def add_apparel_inventory():
    inv = ApparelInventory(brand=request.form.get('brand'), color=request.form.get('color'),
                           size=request.form.get('size'), quantity=int(request.form.get('quantity') or 0),
                           cost_per_unit=_form_money('cost_per_unit', 0.0) or None,
                           reorder_threshold=int(request.form.get('reorder_threshold') or 5))
    db.session.add(inv)
    db.session.commit()
    flash('Apparel added', 'success')
    return redirect(url_for('admin.operations_inventory'))


@admin_bp.route('/operations/inventory/apparel/<int:id>/update', methods=['POST'])
@admin_required
def update_apparel_inventory(id):
    inv = ApparelInventory.query.get_or_404(id)
    inv.quantity = int(request.form.get('quantity') or 0)
    if 'cost_per_unit' in request.form:
        inv.cost_per_unit = _form_money('cost_per_unit', 0.0) or None
    if 'reorder_threshold' in request.form:
        inv.reorder_threshold = int(request.form.get('reorder_threshold') or 0)
    db.session.commit()
    flash('Apparel updated', 'success')
    return redirect(url_for('admin.operations_inventory'))


@admin_bp.route('/operations/inventory/supply/add', methods=['POST'])
@admin_required
def add_supply():
    s = Supply(category=request.form.get('category'), name=request.form.get('name'),
               quantity=int(request.form.get('quantity') or 0), unit=request.form.get('unit') or 'ea',
               cost_per_unit=_form_money('cost_per_unit', 0.0) or None,
               reorder_threshold=int(request.form.get('reorder_threshold') or 0))
    db.session.add(s)
    db.session.commit()
    flash('Supply added', 'success')
    return redirect(url_for('admin.operations_inventory'))


@admin_bp.route('/operations/inventory/supply/<int:id>/update', methods=['POST'])
@admin_required
def update_supply(id):
    s = Supply.query.get_or_404(id)
    s.quantity = int(request.form.get('quantity') or 0)
    if 'cost_per_unit' in request.form:
        s.cost_per_unit = _form_money('cost_per_unit', 0.0) or None
    if 'reorder_threshold' in request.form:
        s.reorder_threshold = int(request.form.get('reorder_threshold') or 0)
    db.session.commit()
    flash('Supply updated', 'success')
    return redirect(url_for('admin.operations_inventory'))


@admin_bp.route('/operations/inventory/transfer/add', methods=['POST'])
@admin_required
def add_transfer_inventory():
    t = TransferInventory(design_name=request.form.get('design_name'), size=request.form.get('size'),
                          quantity=int(request.form.get('quantity') or 0),
                          cost_per_sheet=_form_money('cost_per_sheet', 0.0) or None,
                          reorder_threshold=int(request.form.get('reorder_threshold') or 0),
                          vendor_id=int(request.form.get('vendor_id')) if request.form.get('vendor_id') else None,
                          delivery_time=request.form.get('delivery_time'))
    db.session.add(t)
    db.session.commit()
    flash('Transfer added', 'success')
    return redirect(url_for('admin.operations_inventory'))


@admin_bp.route('/operations/inventory/transfer/<int:id>/update', methods=['POST'])
@admin_required
def update_transfer_inventory(id):
    t = TransferInventory.query.get_or_404(id)
    t.quantity = int(request.form.get('quantity') or 0)
    if 'reorder_threshold' in request.form:
        t.reorder_threshold = int(request.form.get('reorder_threshold') or 0)
    db.session.commit()
    flash('Transfer updated', 'success')
    return redirect(url_for('admin.operations_inventory'))


# ===== DESIGN BACKGROUND REPROCESS =====

@admin_bp.route('/design-gallery/reprocess-backgrounds', methods=['POST'])
@admin_required
def reprocess_design_backgrounds():
    """Re-download every design, strip the background, and re-upload the clean PNG."""
    import io, urllib.request, traceback as _tb
    try:
        from werkzeug.datastructures import FileStorage
        from utils.cloud_storage import upload_image
        from services.image_processing import process_artwork_bytes

        designs = Design.query.all()
        ok, failed, skipped = 0, 0, 0

        for d in designs:
            if not d.file_path:
                skipped += 1
                continue
            try:
                fp = d.file_path.strip()
                if fp.startswith('http'):
                    req = urllib.request.Request(fp, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        raw = resp.read()
                else:
                    from pathlib import Path
                    local = Path(current_app.root_path) / 'static' / fp
                    if not local.exists():
                        skipped += 1
                        continue
                    raw = local.read_bytes()

                result = process_artwork_bytes(raw, mode='aggressive')
                png_bytes = result.get('data')
                if not png_bytes:
                    failed += 1
                    continue

                orig = (d.original_filename or d.filename or 'design.png')
                base = orig.rsplit('.', 1)[0] if '.' in orig else orig
                new_name = f"{base}_clean.png"

                fs = FileStorage(
                    stream=io.BytesIO(png_bytes),
                    filename=new_name,
                    content_type='image/png',
                )
                new_path = upload_image(
                    fs,
                    current_app._get_current_object(),
                    subfolder='designs',
                    public_id_prefix='gallery',
                    process_artwork=False,
                )
                if new_path:
                    d.file_path = new_path
                    ok += 1
                else:
                    failed += 1
            except BaseException as e:
                current_app.logger.exception('Reprocess failed for design %s: %s', d.id, e)
                failed += 1

        db.session.commit()
        return jsonify({
            'ok': ok,
            'failed': failed,
            'skipped': skipped,
            'message': f'Done — {ok} reprocessed, {failed} failed, {skipped} skipped.',
        })
    except BaseException:
        db.session.rollback()
        err = _tb.format_exc()
        current_app.logger.error('reprocess_design_backgrounds fatal: %s', err)
        return jsonify({'error': err}), 500


# ===== SITE SETTINGS =====

@admin_bp.route('/operations/site-settings', methods=['GET', 'POST'])
@admin_required
def site_settings():
    """Small settings the owner changes herself: order time, customer emails, pickup spot, her photo and note."""
    from utils import ready_date
    from utils.site_settings import get_flag, get_setting, set_setting
    from utils.customer_emails import FLAG_KEY, PICKUP_ADDRESS_KEY, PICKUP_NOTES_KEY
    from utils.business_info import BUSINESS
    BUSINESS_PICKUP = BUSINESS['pickup_address']
    if request.method == 'POST':
        section = request.form.get('section')
        if section == 'ready':
            raw = (request.form.get('ready_business_days') or '').strip()
            if raw.isdigit() and ready_date.MIN_DAYS <= int(raw) <= ready_date.MAX_DAYS:
                ready_date.save_business_days(raw)
                flash('Saved. Customers now see the new ready date.', 'success')
            else:
                flash(f'Enter a whole number from {ready_date.MIN_DAYS} to {ready_date.MAX_DAYS}.', 'error')
        elif section == 'credit':
            try:
                pct = float((request.form.get('credit_percent') or '').strip())
                if not 0 <= pct <= 20:
                    raise ValueError
                set_setting('creator_credit_percent', f'{pct:g}', 'Store credit creators earn on shared-design orders (%)')
                flash(f'Saved. Orders picked up or shipped from now on earn {pct:g}%.', 'success')
            except ValueError:
                flash('Enter a percent from 0 to 20.', 'error')
        elif section == 'print_sizes':
            from utils import print_scale as PSC
            try:
                PSC.save_adjustments(request.form.get('medium_adjust'), request.form.get('oversized_adjust'))
                if (request.form.get('back_oversized_price') or '').strip() != '':
                    PSC.save_back_oversized_price(request.form.get('back_oversized_price'))
                flash('Saved. New carts use these print size prices.', 'success')
            except (TypeError, ValueError):
                flash('Enter dollar amounts like -1 or 6.', 'error')
        elif section == 'shipping':
            raw = (request.form.get('free_shipping_min') or '').strip().lstrip('$')
            try:
                value = float(raw) if raw else 0.0
                if value < 0 or value > 100000:
                    raise ValueError
                set_setting('free_shipping_min', f'{value:g}' if value else '', 'Order total that makes shipping free (blank = off)')
                flash(f'Saved. Shipping is free on orders of ${value:,.2f} or more.' if value else 'Saved. Free shipping is off.', 'success')
            except ValueError:
                flash('Enter a dollar amount like 75, or leave it blank to turn it off.', 'error')
        elif section == 'coupon_new':
            from models import Coupon
            from utils import coupons as CP
            from datetime import timedelta
            code = CP.normalize(request.form.get('code'))
            def _num(name):
                raw = (request.form.get(name) or '').strip().lstrip('$')
                return float(raw) if raw else None
            try:
                pct, amt, mini = _num('percent_off'), _num('amount_off'), _num('min_subtotal')
                uses = int(request.form.get('max_uses') or 0) or None
                ends = datetime.fromisoformat(request.form['expires_at']) + timedelta(days=1) - timedelta(seconds=1) if request.form.get('expires_at') else None
                free = bool(request.form.get('free_shipping'))
                if not code or not code.isalnum():
                    flash('A code is letters and numbers only, like SPRING10.', 'error')
                elif Coupon.query.filter_by(code=code).first():
                    flash(f'{code} already exists. Turn it off or pick another name.', 'error')
                elif not (pct or amt or free) or (pct and not 0 < pct <= 100) or (amt is not None and amt < 0):
                    flash('Give the code a percent (1 to 100), a dollar amount, or free shipping.', 'error')
                else:
                    db.session.add(Coupon(code=code, percent_off=pct, amount_off=amt, free_shipping=free, min_subtotal=mini,
                                          max_uses=uses, expires_at=ends))
                    db.session.commit()
                    flash(f'Code {code} is ready.', 'success')
            except (ValueError, KeyError):
                flash('Please check the numbers and date you entered.', 'error')
        elif section == 'coupon_toggle':
            from models import Coupon
            row = db.session.get(Coupon, int(request.form.get('coupon_id') or 0))
            if row is not None:
                if request.form.get('delete'):
                    db.session.delete(row)
                else:
                    row.active = not row.active
                db.session.commit()
                flash('Saved.', 'success')
        elif section == 'emails':
            set_setting(FLAG_KEY, '1' if request.form.get('customer_status_emails') else '0', 'Email customers as orders move')
            set_setting(PICKUP_ADDRESS_KEY, (request.form.get('pickup_address') or '').strip()[:300], 'Where customers pick up orders')
            set_setting(PICKUP_NOTES_KEY, (request.form.get('pickup_notes') or '').strip()[:300], 'Pickup hours or instructions')
            flash('Saved.', 'success')
        elif section == 'tax':
            try:
                saved = sales_tax.save_rate_percent(request.form.get('rate'))
                flash(f'Saved. New orders use {saved:g}% Kansas sales tax.', 'success')
            except (TypeError, ValueError) as exc:
                flash(str(exc) if str(exc) else 'Enter a rate like 9.6.', 'error')
        elif section == 'owner':
            set_setting('owner_name', (request.form.get('owner_name') or '').strip()[:80], 'Owner name')
            set_setting('owner_note', (request.form.get('owner_note') or '').strip()[:600], 'Owner note')
            if request.form.get('remove_owner_photo'):
                set_setting('owner_photo_url', '', 'Owner photo')
            photo = request.files.get('owner_photo')
            if photo and photo.filename:
                ext = os.path.splitext(photo.filename.lower())[1]
                if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                    from utils.cloud_storage import store_upload
                    set_setting('owner_photo_url', store_upload(photo, 'site', 'owner'), 'Owner photo')
                else:
                    flash('Please choose a JPG, PNG or WEBP photo.', 'error')
                    return redirect(url_for('admin.site_settings'))
            flash('Saved. Your photo and note now show on About and Contact.', 'success')
        return redirect(url_for('admin.site_settings'))
    from routes.main import _owner
    from models import Coupon
    from utils import print_scale as PSC
    from utils import print_sizes as PSZ
    from utils.order_costs import get_dtf_costs
    rate = get_dtf_costs().get('dtf_per_sq_in', 0.05)
    size_rows = []
    for key, label in PSC.SCALES:
        w = PSZ.front_transfer_size('M', None, 'center_back', 1, 1.2, scale=key)
        size_rows.append({'key': key, 'label': label, 'hint': PSC.HINTS[key], 'width': w['width_display'], 'height': w['height_display'],
                          'cost': round(w['width'] * w['height'] * rate, 2)})
    return render_template('admin/operations/site_settings.html',
                           print_size_rows=size_rows, print_adjust=PSC.adjustments(), back_oversized_price=PSC.back_oversized_price(),
                           business_days=ready_date.get_business_days(),
                           preview=ready_date.format_day(ready_date.ready_by()),
                           min_days=ready_date.MIN_DAYS, max_days=ready_date.MAX_DAYS,
                           credit_percent=get_setting('creator_credit_percent', '2'),
                           free_shipping_min=get_setting('free_shipping_min', ''),
                           coupon_rows=Coupon.query.order_by(Coupon.created_at.desc()).all(),
                           emails_on=get_flag(FLAG_KEY, True), tax_percent=sales_tax.rate_percent(),
                           pickup_address=get_setting(PICKUP_ADDRESS_KEY, '') or BUSINESS_PICKUP,
                           pickup_notes=get_setting(PICKUP_NOTES_KEY, ''),
                           owner=_owner(), owner_name_saved=get_setting('owner_name', ''),
                           owner_note_saved=get_setting('owner_note', ''))


@admin_bp.route('/operations/reviews', methods=['GET', 'POST'])
@admin_required
def reviews():
    """Read, approve, hide or delete customer reviews. Only approved ones show on the site."""
    from models import Review
    if request.method == 'POST':
        row = db.session.get(Review, int(request.form.get('review_id') or 0))
        action = request.form.get('action')
        from utils.reviews_public import clear_cache
        clear_cache()
        if row is None:
            flash('That review was not found.', 'error')
        elif action == 'approve':
            row.status = 'approved'
            db.session.commit()
            flash('Approved. It now shows on the homepage and the Kind Words page.', 'success')
        elif action == 'hide':
            row.status = 'hidden'
            db.session.commit()
            flash('Hidden from the website.', 'success')
        elif action == 'delete':
            db.session.delete(row)
            db.session.commit()
            flash('Deleted.', 'success')
        return redirect(url_for('admin.reviews'))
    rows = Review.query.order_by((Review.status == 'pending').desc(), Review.created_at.desc()).all()
    return render_template('admin/operations/reviews.html', reviews=rows,
                           pending=sum(1 for r in rows if r.status == 'pending'))


# ===== OPERATIONS: PACKAGING SOP =====

@admin_bp.route('/operations/packaging-sop')
@admin_required
def packaging_sop():
    """Packaging & Fulfillment SOP checklist - printable"""
    return render_template('admin/operations/packaging_sop.html')


# ===== OPERATIONS: CUSTOMERS & MARKETING =====

@admin_bp.route('/operations/customers')
@admin_required
def customers():
    """Customer & marketing tracker - repeat customers, collections (school/team/event)"""
    from sqlalchemy import func
    # Repeat customers: the same email on 2+ orders, in any capitalization, account or guest checkout
    email_key = func.lower(func.trim(Order.email))
    rows = (db.session.query(email_key.label('e'), func.count(Order.id), func.max(Order.created_at), func.sum(Order.total))
            .filter(Order.email.isnot(None), Order.email != '', Order.status != 'cancelled')
            .group_by(email_key).having(func.count(Order.id) >= 2)
            .order_by(func.count(Order.id).desc(), func.max(Order.created_at).desc()).all())
    repeat_customers = []
    for key, count, last_at, spent in rows:
        latest = (Order.query.filter(email_key == key, Order.status != 'cancelled')
                  .order_by(Order.created_at.desc()).first())
        user = User.query.filter(func.lower(User.email) == key).first()
        name = (user.full_name if user else '') or ' '.join(
            p for p in (latest.first_name, latest.last_name) if p) if latest else ''
        repeat_customers.append({'name': name or key, 'email': key, 'order_count': count,
                                 'last_order': last_at, 'spent': float(spent or 0)})
    # Collections (school/team/event)
    collections = Collection.query.filter_by(is_active=True).order_by(Collection.name).all()
    return render_template('admin/operations/customers.html',
                         repeat_customers=repeat_customers,
                         collections=collections)
