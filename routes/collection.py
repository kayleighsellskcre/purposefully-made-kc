from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, Response
from flask_login import current_user, login_required
from models import db, Collection, Product, ProductColorVariant, Design
from utils.mockups import get_carousel_colors_for_product, get_first_shop_image_url, product_has_shop_image
from utils.json_fields import parse_json_list
from utils.product_filters import catalog_filter_options, prepare_catalog
from utils.sizes import sort_sizes
from sqlalchemy.orm import joinedload
import json
import io

collection_bp = Blueprint('collection', __name__, url_prefix='/c')


@collection_bp.app_template_global()
def download_stamp():
    """Changes every second, so a spreadsheet link is never served from a cache."""
    import time
    return int(time.time())


def _private_download_headers(filename):
    """Headers for private spreadsheet downloads.

    Cloudflare caches .xlsx URLs by default, which served an old copy of
    the order spreadsheet (and could hand it to someone else). no-store
    tells the browser and every CDN in between never to keep a copy.
    """
    return {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Cache-Control': 'private, no-store, no-cache, max-age=0, must-revalidate',
        'CDN-Cache-Control': 'no-store',
        'Cloudflare-CDN-Cache-Control': 'no-store',
        'Pragma': 'no-cache',
        'Expires': '0',
    }


@collection_bp.route('/<slug>/qr.png')
def qr_code(slug):
    """Return a QR code PNG for this collection's share URL."""
    collection = Collection.query.filter_by(slug=slug).first_or_404()
    share_url = request.url_root.rstrip('/') + url_for('collection.view', slug=slug)
    try:
        import qrcode
        from qrcode.image.pil import PilImage
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(share_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='#3A3D48', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return Response(
            buf.getvalue(),
            mimetype='image/png',
            headers={'Cache-Control': 'public, max-age=3600'},
        )
    except ImportError:
        from flask import abort
        abort(500, 'qrcode library not installed. Run: pip install qrcode[pil]')


@collection_bp.route('/leave')
def leave():
    """Drop group-order session and return to the regular shop.

    Header links pass ?next=/path so leaving Shop / About / etc. lands on the
    page the shopper asked for, without staying stuck in the group banner.
    """
    from utils.group_orders import leave_group_order
    leave_group_order()
    next_url = (request.args.get('next') or '').strip()
    # Same-site relative paths only — never bounce to an absolute URL.
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    flash('You left the group order. You can still shop the regular store.', 'info')
    return redirect(url_for('shop.index'))


@collection_bp.route('/<slug>')
def view(slug):
    """View collection landing page - design board of available items"""
    collection = Collection.query.options(
        joinedload(Collection.products)
    ).filter_by(slug=slug, is_active=True).first_or_404()
    
    # Check password if protected
    if collection.is_password_protected:
        if not session.get(f'collection_{collection.id}_access'):
            return redirect(url_for('collection.password', slug=slug))
    
    from utils.group_roster import is_organizer_pays
    if is_organizer_pays(collection):
        return _roster_form(collection)

    # Check if deadline has passed — show warning but still allow viewing
    from utils.group_orders import (
        allowed_colors_for_product,
        attach_collection,
        is_deadline_passed,
        is_not_yet_open,
        load_design_dict,
        load_showcase_designs,
        resolve_uniform_design_id,
        team_store_config,
        visible_store_products,
    )
    from utils.pricing import group_order_listed_price
    collection.deadline_passed = is_deadline_passed(collection)
    collection.not_yet_open = is_not_yet_open(collection)
    collection.cannot_order = collection.deadline_passed or collection.not_yet_open

    # Keep this group order in session so customize/cart/checkout stay attached
    attach_collection(collection)

    # Get products in this collection with carousel colors (DB + mockup folder)
    all_products = visible_store_products(collection)
    store_config = team_store_config(collection)
    fan_ids = set(store_config['fan_product_ids'])
    uniform = store_config['uniform']
    fan_back = not (
        store_config['configured']
        and uniform['enabled']
        and not store_config.get('fan_personalization_enabled')
    )
    uniform_ids = set(uniform.get('product_ids') or [])
    if uniform.get('product_id'):
        uniform_ids.add(uniform['product_id'])
    uniform_product = None
    uniform_products = []
    uniform_kits = []
    products = []
    kit_designs = {}
    if uniform['enabled']:
        kit_designs = {
            'home': load_design_dict(resolve_uniform_design_id(collection, 'home')),
            'away': load_design_dict(resolve_uniform_design_id(collection, 'away')),
        }
    for product in all_products:
        if uniform['enabled'] and product.id in uniform_ids:
            kit_colors = [
                (key, uniform[f'{key}_color'])
                for key in ('home', 'away')
                if uniform.get(f'{key}_color')
            ]
            allowed_uniform_colors = {color for _key, color in kit_colors}
            variants = get_carousel_colors_for_product(
                product, current_app, allowed_colors=allowed_uniform_colors
            )
            by_color = {v.get('color_name'): v for v in variants}
            product.carousel_colors = variants
            product.fallback_image_url = get_first_shop_image_url(
                product, current_app, carousel=variants
            )
            if not product_has_shop_image(
                product, current_app,
                carousel=variants,
                image_url=product.fallback_image_url,
            ):
                continue
            product.available_sizes_list = sort_sizes(
                parse_json_list(product.available_sizes)
            )
            kits = [
                {'key': key, 'label': key.title(), 'color': color,
                 'variant': by_color.get(color),
                 'design': kit_designs.get(key)}
                for key, color in kit_colors
                if by_color.get(color)
            ]
            if not uniform_product:
                uniform_product = product
                uniform_kits = kits
            uniform_products.append({'product': product, 'kits': kits})
            continue
        if store_config['configured'] and product.id not in fan_ids:
            continue
        allowed_colors = allowed_colors_for_product(product, collection)
        variants = get_carousel_colors_for_product(product, current_app, allowed_colors=allowed_colors)
        product.carousel_colors = variants
        product.fallback_image_url = get_first_shop_image_url(
            product, current_app, carousel=variants)
        product.available_sizes_list = sort_sizes(parse_json_list(product.available_sizes))
        # When colors are restricted, skip styles that don't come in those colors.
        if allowed_colors is not None and not variants:
            continue
        if not product_has_shop_image(
            product, current_app,
            carousel=variants,
            image_url=product.fallback_image_url,
        ):
            continue
        product.listed_price = group_order_listed_price(
            product, collection, include_back=fan_back
        )
        products.append(product)

    products = prepare_catalog(products)
    filter_opts = catalog_filter_options(products)
    from utils.group_orders import build_store_cards
    products, age_matching_note = build_store_cards(products)
    showcase_designs = load_showcase_designs(collection)
    return render_template('collection/view.html',
                         collection=collection,
                         products=products,
                         age_matching_note=age_matching_note,
                         team_store=store_config,
                         uniform_product=uniform_product,
                         uniform_products=uniform_products,
                         uniform_kits=uniform_kits,
                         showcase_designs=showcase_designs,
                         catalog_filter_opts=filter_opts)


# ── Organizer pays: the link collects name + size only ──────────────────────

def _roster_form(collection, error=None, form=None, status=200):
    """One-screen size form for an organizer-pays group order."""
    from utils.group_orders import is_deadline_passed, is_not_yet_open, user_can_manage_collection
    from utils.group_roster import roster_closed, roster_item

    # Parents never shop here, so never pin this store to their session.
    session.pop('collection_id', None)
    item = roster_item(collection)
    thanks = session.pop(f'roster_thanks_{collection.id}', None)
    closed_reason = None
    if roster_closed(collection):
        closed_reason = 'This order is closed. Sizes have already been sent in.'
    elif is_deadline_passed(collection):
        closed_reason = 'This order is closed. The deadline to send in sizes has passed.'
    elif is_not_yet_open(collection):
        from utils.group_orders import format_schedule_date
        closed_reason = (
            'This order opens on '
            f'{format_schedule_date(collection.order_opens_at)}. Check back then to send in your size.'
        )
    elif item is None:
        closed_reason = 'This order is not quite ready yet. Please check back soon.'
    return render_template(
        'collection/roster_form.html',
        collection=collection,
        item=item,
        thanks=thanks,
        closed_reason=closed_reason,
        error=error,
        form=form or {},
        can_manage=user_can_manage_collection(collection),
    ), status


def _rate_limit_roster(view):
    from utils.rate_limit import rate_limit
    return rate_limit("60 per hour")(view)


@collection_bp.route('/<slug>/roster', methods=['POST'])
@_rate_limit_roster
def roster_submit(slug):
    """Save one person's name + size. No account, no cart, no payment."""
    from models import GroupRosterEntry
    from utils.group_orders import is_deadline_passed, is_not_yet_open
    from utils.group_roster import is_organizer_pays, roster_closed, roster_item, validate_submission

    collection = Collection.query.filter_by(slug=slug, is_active=True).first_or_404()
    if not is_organizer_pays(collection):
        return redirect(url_for('collection.view', slug=slug))
    if collection.is_password_protected and not session.get(f'collection_{collection.id}_access'):
        return redirect(url_for('collection.password', slug=slug))

    # Honeypot: real people never see this field.
    if (request.form.get('website') or '').strip():
        return redirect(url_for('collection.view', slug=slug))

    item = roster_item(collection)
    if (
        item is None
        or roster_closed(collection)
        or is_deadline_passed(collection)
        or is_not_yet_open(collection)
    ):
        return redirect(url_for('collection.view', slug=slug))

    cleaned, error = validate_submission(request.form, item)
    if error:
        return _roster_form(collection, error=error, form=request.form, status=400)
    first, last, size = cleaned
    entry = GroupRosterEntry(
        collection_id=collection.id, first_name=first, last_name=last, size=size,
    )
    db.session.add(entry)
    db.session.commit()
    session[f'roster_thanks_{collection.id}'] = {
        'name': entry.full_name, 'size': entry.size,
    }
    return redirect(url_for('collection.view', slug=slug) + '#roster-thanks')


def _managed_roster_collection(slug):
    """Organizer-pays store the current user may manage, or None."""
    from utils.group_orders import user_can_manage_collection
    from utils.group_roster import is_organizer_pays

    collection = Collection.query.filter_by(slug=slug).first_or_404()
    if not is_organizer_pays(collection) or not user_can_manage_collection(collection):
        return None
    return collection


@collection_bp.route('/<slug>/roster.xlsx')
@login_required
def roster_xlsx(slug):
    from utils.group_roster import roster_xlsx as build_xlsx

    collection = _managed_roster_collection(slug)
    if not collection:
        from flask import abort
        abort(404)
    safe_name = slug.replace('/', '_').replace(' ', '_')
    return Response(
        build_xlsx(collection),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=_private_download_headers(f'roster_{safe_name}.xlsx'),
    )


@collection_bp.route('/<slug>/roster/<int:entry_id>/remove', methods=['POST'])
@login_required
def roster_remove(slug, entry_id):
    """Let the organizer remove a duplicate or mistaken line before paying."""
    from models import GroupRosterEntry
    from utils.group_roster import roster_closed

    collection = _managed_roster_collection(slug)
    if not collection:
        from flask import abort
        abort(404)
    if roster_closed(collection):
        flash('This order has already been placed, so the list can no longer change.', 'error')
        return redirect(url_for('collection.share', slug=slug))
    entry = GroupRosterEntry.query.filter_by(id=entry_id, collection_id=collection.id).first_or_404()
    name = entry.full_name
    db.session.delete(entry)
    db.session.commit()
    flash(f'Removed {name} from the list.', 'success')
    return redirect(url_for('collection.share', slug=slug) + '#roster')


@collection_bp.route('/<slug>/roster/pay', methods=['POST'])
@login_required
def roster_pay(slug):
    """Put the whole roster in the organizer's cart and send them to checkout."""
    from utils.cart_store import save_cart
    from utils.group_roster import build_roster_cart, roster_closed, roster_entries, roster_item

    collection = _managed_roster_collection(slug)
    if not collection:
        from flask import abort
        abort(404)
    if not collection.is_active:
        flash('This group order is turned off. Turn it back on to place the order.', 'error')
        return redirect(url_for('collection.share', slug=slug))
    if roster_closed(collection):
        flash('The order for this group has already been placed.', 'info')
        return redirect(url_for('collection.share', slug=slug))
    item = roster_item(collection)
    if item is None:
        flash('Pick one shirt and one color for this group order before paying.', 'error')
        return redirect(url_for('shop.edit_group_order', slug=slug))
    entries = roster_entries(collection)
    if not entries:
        flash('No sizes have come in yet.', 'error')
        return redirect(url_for('collection.share', slug=slug))

    # Replace whatever was in the cart so the group order checks out on its own.
    save_cart(build_roster_cart(collection, item, entries))
    session['collection_id'] = collection.id
    session.modified = True
    return redirect(url_for('checkout.index'))


@collection_bp.route('/<slug>/password', methods=['GET', 'POST'])
def password(slug):
    """Password protection for collection"""
    collection = Collection.query.filter_by(slug=slug, is_active=True).first_or_404()
    
    if not collection.is_password_protected:
        return redirect(url_for('collection.view', slug=slug))
    
    if request.method == 'POST':
        password = request.form.get('password')
        
        if collection.check_password(password):
            session[f'collection_{collection.id}_access'] = True
            return redirect(url_for('collection.view', slug=slug))
        else:
            flash('Incorrect password', 'error')
    
    return render_template('collection/password.html', collection=collection)


@collection_bp.route('/<slug>/share')
def share(slug):
    """Collection share page (shows share link and QR code)"""
    from utils.group_orders import user_can_manage_collection

    collection = Collection.query.filter_by(slug=slug).first_or_404()
    if not collection.is_active and not user_can_manage_collection(collection):
        from flask import abort
        abort(404)

    # Check password if protected
    if collection.is_password_protected:
        if not session.get(f'collection_{collection.id}_access'):
            return redirect(url_for('collection.password', slug=slug))

    # Resolve designs for this collection so the share page can show them
    designs = []
    if collection.allowed_design_ids:
        try:
            ids = json.loads(collection.allowed_design_ids)
            if ids:
                designs = Design.query.filter(Design.id.in_(ids)).all()
        except Exception:
            designs = []

    # Determine if the current user can manage (delete) designs
    can_manage = (
        current_user.is_authenticated and (
            getattr(current_user, 'is_admin', False) or
            current_user.id == collection.created_by_user_id
        )
    )

    roster = None
    roster_item_info = None
    roster_problem = None
    extra_logos = 0
    from utils.group_roster import (
        extra_logo_count, is_organizer_pays, roster_item, roster_item_error, roster_summary,
    )
    if can_manage and is_organizer_pays(collection):
        roster = roster_summary(collection)
        roster_problem = roster_item_error(collection)
        roster_item_info = None if roster_problem else roster_item(collection)
        extra_logos = extra_logo_count(collection)

    return render_template('collection/share.html', collection=collection,
                           designs=designs, can_manage=can_manage,
                           organizer_pays=is_organizer_pays(collection),
                           roster=roster, roster_item=roster_item_info,
                           roster_problem=roster_problem, extra_logos=extra_logos)


@collection_bp.route('/<slug>/design/<int:design_id>/delete', methods=['POST'])
@login_required
def delete_design(slug, design_id):
    """Remove a design from a group order's allowed list.

    Only the collection creator or an admin may do this.
    """
    collection = Collection.query.filter_by(slug=slug).first_or_404()

    # Permission check
    is_admin = getattr(current_user, 'is_admin', False)
    is_creator = current_user.id == collection.created_by_user_id
    if not (is_admin or is_creator):
        flash('You do not have permission to delete designs from this group order.', 'error')
        return redirect(url_for('collection.share', slug=slug))

    # Remove the design from allowed_design_ids
    try:
        ids = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
        ids = [i for i in ids if i != design_id]
        collection.allowed_design_ids = json.dumps(ids) if ids else None
        db.session.commit()
        flash('Design removed from this group order.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error removing design %s from collection %s: %s', design_id, slug, e)
        flash('Could not remove the design. Please try again.', 'error')

    return redirect(url_for('collection.share', slug=slug))


# ── Excel Export ─────────────────────────────────────────────────────────────

@collection_bp.route('/<slug>/export.xlsx')
@login_required
def export_xlsx(slug):
    """Download an Excel workbook for this group order.

    Accessible to:
      - Site admins (is_admin flag)
      - The user who created the collection (created_by_user_id)
    """
    collection = Collection.query.filter_by(slug=slug).first_or_404()

    is_admin   = getattr(current_user, 'is_admin', False)
    is_creator = (current_user.id == collection.created_by_user_id)
    if not (is_admin or is_creator):
        flash('You do not have permission to export this group order.', 'error')
        return redirect(url_for('collection.share', slug=slug))

    try:
        xlsx_bytes = _build_group_order_xlsx(collection, include_internal=is_admin)
    except Exception as e:
        current_app.logger.exception('Excel export failed for collection %s: %s', slug, e)
        flash('Could not generate the Excel file. Please try again.', 'error')
        return redirect(url_for('collection.share', slug=slug))

    safe_name = slug.replace('/', '_').replace(' ', '_')
    filename  = f"group_order_{safe_name}.xlsx"
    return Response(
        xlsx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=_private_download_headers(filename),
    )


def _build_group_order_xlsx(collection, include_internal=False):
    """Build and return raw .xlsx bytes for the given collection.

    The first sheet, "All Orders", has one row per shirt with every detail
    of the order it belongs to, so nothing needs to be cross-referenced.
    include_internal adds admin-only columns (admin notes, cost, profit);
    organizers who download their own store never see those.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from models import Order, OrderItem

    # ── colour palette ──────────────────────────────────────────────────────
    HEADER_FILL  = PatternFill('solid', fgColor='B87C6F')   # terra-cotta
    HEADER_FONT  = Font(bold=True, color='FFFFFF', size=11)
    TITLE_FONT   = Font(bold=True, size=14)
    THIN         = Side(style='thin', color='CCCCCC')
    THIN_BORDER  = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    MONEY_FMT    = '$#,##0.00'
    CENTER       = Alignment(horizontal='center', vertical='center', wrap_text=True)
    LEFT         = Alignment(horizontal='left',   vertical='center', wrap_text=True)

    def style_header_row(ws, row, cols):
        for col in range(1, cols + 1):
            cell = ws.cell(row=row, column=col)
            cell.fill      = HEADER_FILL
            cell.font      = HEADER_FONT
            cell.border    = THIN_BORDER
            cell.alignment = CENTER

    def style_data_row(ws, row, cols, alt=False):
        fill = PatternFill('solid', fgColor='FAF7F4') if alt else PatternFill('solid', fgColor='FFFFFF')
        for col in range(1, cols + 1):
            cell = ws.cell(row=row, column=col)
            cell.fill      = fill
            cell.border    = THIN_BORDER
            cell.alignment = LEFT

    def set_col_widths(ws, widths):
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    wb = openpyxl.Workbook()

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 1 — Summary
    # ════════════════════════════════════════════════════════════════════════
    ws_sum = wb.active
    ws_sum.title = 'Summary'

    from datetime import datetime

    orders = collection.orders.all()
    orders.sort(key=lambda o: (
        0 if o.send_home_with_child else 1,
        (o.teacher_name or '').strip().lower(),
        (o.child_grade or '').strip().lower(),
        (o.child_name or '').strip().lower(),
        o.created_at or datetime.min,
    ))

    ws_sum['A1'] = f'Group Order: {collection.name}'
    ws_sum['A1'].font = TITLE_FONT
    ws_sum.merge_cells('A1:F1')
    ws_sum['A1'].alignment = CENTER

    from utils.local_time import format_central
    ws_sum['A2'] = f'Exported: {format_central(datetime.utcnow())} (Central)'
    ws_sum['A2'].font = Font(italic=True, color='888888', size=9)
    ws_sum.merge_cells('A2:F2')

    from utils.group_orders import format_schedule_date
    opens_label = format_schedule_date(collection.order_opens_at) or '-'
    deadline_label = format_schedule_date(collection.order_deadline) or '-'
    ws_sum['A3'] = f'Opens: {opens_label}   Deadline: {deadline_label}'
    ws_sum.merge_cells('A3:F3')

    paid_orders   = [o for o in orders if o.payment_status == 'paid']
    total_revenue = sum(o.total for o in paid_orders)
    total_items   = sum(item.quantity for o in orders for item in o.items)

    ws_sum['A5'] = 'Total Orders';  ws_sum['B5'] = len(orders)
    ws_sum['A6'] = 'Paid Orders';   ws_sum['B6'] = len(paid_orders)
    ws_sum['A7'] = 'Total Revenue'; ws_sum['B7'] = total_revenue; ws_sum['B7'].number_format = MONEY_FMT
    ws_sum['A8'] = 'Total Items';   ws_sum['B8'] = total_items

    pending_orders = [o for o in orders if o.payment_status != 'paid']
    ws_sum['A9'] = 'Unpaid / Cash Due'; ws_sum['B9'] = len(pending_orders)
    ws_sum['A10'] = 'Send Home Orders'; ws_sum['B10'] = sum(1 for o in orders if o.send_home_with_child)
    ws_sum['A11'] = 'Shipping Orders';  ws_sum['B11'] = sum(1 for o in orders if (o.fulfillment_method or '') == 'shipping')

    for row in range(5, 12):
        ws_sum.cell(row=row, column=1).font = Font(bold=True)

    ws_sum['A13'] = ('Every order, with every detail, is on the "All Orders" tab (one row per shirt). '
                     '"Orders" has one row per order, "Line Items" lists each shirt, and '
                     '"Size Breakdown" totals sizes for printing.')
    ws_sum['A13'].alignment = Alignment(wrap_text=True, vertical='top')
    ws_sum['A13'].font = Font(italic=True, color='666666')
    ws_sum.merge_cells('A13:F15')

    ws_sum.row_dimensions[1].height = 28
    ws_sum.column_dimensions['A'].width = 20
    ws_sum.column_dimensions['B'].width = 18

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 2 — Orders
    # ════════════════════════════════════════════════════════════════════════
    ws_ord = wb.create_sheet('Orders')
    ord_headers = [
        'Order #', 'Date', 'Name', 'Email', 'Phone',
        'Fulfillment', 'Send Home', 'Child', 'Coach/Teacher', 'Grade',
        'Payment', 'Status',
        'Items', 'Subtotal', 'Shipping', 'Tax', 'Total', 'Notes',
        'Paid With', 'Amount Paid', 'Paid On', 'Promo Code',
        'Production Stage', 'Ship To', 'Tracking',
    ]
    if include_internal:
        ord_headers += ['Admin Notes', 'Cost of Goods', 'Profit']
    ws_ord.append(ord_headers)
    style_header_row(ws_ord, 1, len(ord_headers))
    ws_ord.row_dimensions[1].height = 22

    for idx, order in enumerate(orders, start=2):
        items_count = sum(i.quantity for i in order.items)
        ws_ord.append([
            order.order_number,
            format_central(order.created_at, '%Y-%m-%d %I:%M %p') if order.created_at else '',
            order.full_name,
            order.email or '',
            order.phone or '',
            order.fulfillment_method or '',
            'Yes' if order.send_home_with_child else '',
            order.child_name or '',
            order.teacher_name or '',
            order.child_grade or '',
            order.payment_status or '',
            order.status or '',
            items_count,
            order.subtotal,
            order.shipping_cost or 0,
            order.tax or 0,
            order.total,
            order.customer_notes or '',
            _payment_label(order),
            order.amount_paid if order.amount_paid is not None else '',
            format_central(order.paid_at, '%Y-%m-%d %I:%M %p') if order.paid_at else '',
            order.promo_code or '',
            _stage_label(order.production_stage),
            _ship_to(order),
            ' '.join(x for x in (order.carrier or '', order.tracking_number or '') if x),
        ] + ([
            order.admin_notes or '',
            order.cost_of_goods if order.cost_of_goods is not None else '',
            order.profit if order.profit is not None else '',
        ] if include_internal else []))
        style_data_row(ws_ord, idx, len(ord_headers), alt=(idx % 2 == 0))
        money_cols = [14, 15, 16, 17, 20] + ([27, 28] if include_internal else [])
        for col in money_cols:
            ws_ord.cell(row=idx, column=col).number_format = MONEY_FMT

    set_col_widths(ws_ord, [18, 18, 22, 28, 14, 12, 12, 18, 18, 10, 10, 14, 7, 10, 10, 8, 10, 30,
                            12, 12, 18, 12, 18, 36, 22] + ([30, 12, 10] if include_internal else []))
    ws_ord.freeze_panes = 'B2'
    ws_ord.auto_filter.ref = ws_ord.dimensions

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 3 — Line Items
    # ════════════════════════════════════════════════════════════════════════
    ws_items = wb.create_sheet('Line Items')
    item_headers = [
        'Order #', 'Customer', 'Child', 'Coach/Teacher', 'Grade',
        'Product', 'Style #', 'Section', 'Uniform Kit',
        'Color', 'Size', 'Qty', 'Placement',
        'Design', 'Back (Name/Number)', 'Unit Price', 'Line Total',
    ]
    ws_items.append(item_headers)
    style_header_row(ws_items, 1, len(item_headers))
    ws_items.row_dimensions[1].height = 22

    row_idx = 2
    for order in orders:
        for item in order.items:
            back_meta = {}
            if item.back_design_meta:
                try:
                    back_meta = json.loads(item.back_design_meta)
                except Exception:
                    pass
            back_str = ''
            if back_meta:
                parts = []
                if back_meta.get('name'):
                    parts.append(f"Name: {back_meta['name']}")
                if back_meta.get('number'):
                    parts.append(f"#{back_meta['number']}")
                back_str = '  |  '.join(parts)

            ws_items.append([
                order.order_number,
                order.full_name,
                order.child_name or '',
                order.teacher_name or '',
                order.child_grade or '',
                item.product_name or '',
                item.style_number or '',
                'Player Uniform' if item.catalog_section == 'uniform' else 'Family & Fan Wear',
                (item.uniform_kit or '').title(),
                item.color or '',
                item.size or '',
                item.quantity,
                item.placement or '',
                item.design_file_name or '',
                back_str,
                item.unit_price,
                item.subtotal,
            ])
            style_data_row(ws_items, row_idx, len(item_headers), alt=(row_idx % 2 == 0))
            ws_items.cell(row=row_idx, column=16).number_format = MONEY_FMT
            ws_items.cell(row=row_idx, column=17).number_format = MONEY_FMT
            row_idx += 1

    set_col_widths(ws_items, [18, 22, 18, 18, 10, 28, 10, 18, 13, 18, 7, 5, 14, 26, 22, 10, 10])

    # ════════════════════════════════════════════════════════════════════════
    # All Orders — one row per shirt with every detail of its order.
    # Shown first so the full picture is the first thing that opens.
    # ════════════════════════════════════════════════════════════════════════
    ws_all = wb.create_sheet('All Orders', 0)
    all_headers = [
        'Order #', 'Order Date', 'Customer', 'Email', 'Phone',
        'Child', 'Coach/Teacher', 'Grade', 'Send Home',
        'Fulfillment', 'Ship To',
        'Product', 'Style #', 'Section', 'Color', 'Size', 'Qty',
        'Front Design', 'Placement', 'Print Size (in)',
        'Back Name', 'Back Number', 'Back Font', 'Back Colors', 'Back Image',
        'Item Notes', 'Unit Price', 'Line Total',
        'Order Subtotal', 'Shipping', 'Tax', 'Order Total',
        'Paid With', 'Payment Status', 'Amount Paid', 'Promo Code',
        'Order Status', 'Production Stage', 'Tracking', 'Customer Notes',
    ]
    if include_internal:
        all_headers += ['Admin Notes']
    ws_all.append(all_headers)
    style_header_row(ws_all, 1, len(all_headers))
    ws_all.row_dimensions[1].height = 30
    money_idx = [all_headers.index(h) + 1 for h in (
        'Unit Price', 'Line Total', 'Order Subtotal', 'Shipping', 'Tax', 'Order Total', 'Amount Paid')]

    row_idx = 2
    for n, order in enumerate(orders):
        items = list(order.items) or [None]
        for i, item in enumerate(items):
            first = i == 0
            meta = (item.back_design_details or {}) if item else {}
            colors = ', '.join(
                x for x in (
                    meta.get('text_color') or '',
                    ('outline ' + meta['outline_color']) if meta.get('outline') and meta.get('outline_color') else '',
                ) if x
            )
            print_size = ''
            if item and item.print_width and item.print_height:
                print_size = f'{item.print_width:g} x {item.print_height:g}'
            section = ''
            if item:
                section = (
                    f'{(item.uniform_kit or "Player").title()} Uniform'
                    if item.catalog_section == 'uniform' else 'Family & Fan Wear'
                )
            ws_all.append([
                order.order_number,
                format_central(order.created_at, '%Y-%m-%d %I:%M %p') if order.created_at else '',
                order.full_name,
                order.email or '',
                order.phone or '',
                order.child_name or '',
                order.teacher_name or '',
                order.child_grade or '',
                'Yes' if order.send_home_with_child else '',
                (order.fulfillment_method or '').title(),
                _ship_to(order),
                (item.product_name or '') if item else '',
                (item.style_number or '') if item else '',
                section,
                (item.color or '') if item else '',
                (item.size or '') if item else '',
                item.quantity if item else '',
                (item.design_file_name or '') if item else '',
                _placement_label(item.placement) if item else '',
                print_size,
                meta.get('name') or '',
                meta.get('number') or '',
                meta.get('font') or '',
                colors,
                (item.back_design_file_name or '') if item and not (meta.get('name') or meta.get('number')) else '',
                (item.notes or '') if item else '',
                item.unit_price if item else '',
                item.subtotal if item else '',
                # Order money only on the order's first row so column sums stay right.
                order.subtotal if first else '',
                (order.shipping_cost or 0) if first else '',
                (order.tax or 0) if first else '',
                order.total if first else '',
                _payment_label(order),
                (order.payment_status or '').title(),
                (order.amount_paid if order.amount_paid is not None else '') if first else '',
                order.promo_code or '',
                (order.status or '').replace('_', ' ').title(),
                _stage_label(order.production_stage),
                ' '.join(x for x in (order.carrier or '', order.tracking_number or '') if x),
                order.customer_notes or '',
            ] + ([order.admin_notes or ''] if include_internal else []))
            # Alternate shading by order, not by row, so one order's shirts read as a block.
            style_data_row(ws_all, row_idx, len(all_headers), alt=(n % 2 == 1))
            for col in money_idx:
                ws_all.cell(row=row_idx, column=col).number_format = MONEY_FMT
            row_idx += 1

    if row_idx == 2:
        ws_all.append(['No orders yet.'])

    set_col_widths(ws_all, [
        18, 18, 22, 28, 14,
        18, 18, 9, 10,
        11, 36,
        28, 10, 17, 16, 7, 5,
        26, 13, 13,
        16, 11, 14, 18, 24,
        26, 10, 10,
        12, 10, 9, 11,
        11, 13, 11, 12,
        13, 17, 22, 30,
    ] + ([30] if include_internal else []))
    ws_all.freeze_panes = 'D2'
    ws_all.auto_filter.ref = ws_all.dimensions
    wb.active = 0

    # Organizer-pays stores: the name + size list parents sent in.
    from utils.group_roster import is_organizer_pays, roster_entries
    if is_organizer_pays(collection):
        ws_roster = wb.create_sheet('Roster', 1)
        ws_roster.append(['#', 'First Name', 'Last Name', 'Size', 'Submitted'])
        style_header_row(ws_roster, 1, 5)
        for n, e in enumerate(roster_entries(collection), start=1):
            ws_roster.append([
                n, e.first_name, e.last_name, e.size,
                format_central(e.created_at, '%Y-%m-%d %I:%M %p') if e.created_at else '',
            ])
            style_data_row(ws_roster, n + 1, 5, alt=(n % 2 == 0))
        set_col_widths(ws_roster, [5, 18, 18, 8, 20])
        ws_roster.freeze_panes = 'A2'

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 4 — Size Breakdown (production tally)
    # ════════════════════════════════════════════════════════════════════════
    ws_sizes = wb.create_sheet('Size Breakdown')

    SIZE_ORDER = ['NB', '3M', '6M', '12M', '18M', '24M',
                  '2T', '3T', '4T', '5T',
                  'YXS', 'YS', 'YM', 'YL', 'YXL',
                  'XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL']

    tally    = {}
    all_sizes = set()
    for order in orders:
        for item in order.items:
            section = (
                f'{(item.uniform_kit or "Player").title()} Uniform'
                if item.catalog_section == 'uniform'
                else 'Family & Fan Wear'
            )
            key  = (section, item.product_name or '', item.color or '')
            size = item.size or '?'
            all_sizes.add(size)
            tally.setdefault(key, {})
            tally[key][size] = tally[key].get(size, 0) + item.quantity

    known_set   = set(SIZE_ORDER)
    extra_sizes = sorted(s for s in all_sizes if s not in known_set)
    sorted_sizes = [s for s in SIZE_ORDER if s in all_sizes] + extra_sizes

    size_hdr = ['Section', 'Product', 'Color'] + sorted_sizes + ['TOTAL']
    ws_sizes.append(size_hdr)
    style_header_row(ws_sizes, 1, len(size_hdr))
    ws_sizes.row_dimensions[1].height = 22

    row_idx = 2
    for (section, product_name, color), size_map in sorted(tally.items()):
        row_data  = [section, product_name, color]
        row_total = 0
        for size in sorted_sizes:
            qty = size_map.get(size, 0)
            row_total += qty
            row_data.append(qty if qty else '')
        row_data.append(row_total)
        ws_sizes.append(row_data)
        style_data_row(ws_sizes, row_idx, len(size_hdr), alt=(row_idx % 2 == 0))
        ws_sizes.cell(row=row_idx, column=len(size_hdr)).font = Font(bold=True)
        row_idx += 1

    # Grand total row
    gt_row    = ['', '', 'TOTAL']
    grand_total = 0
    for size in sorted_sizes:
        col_total = sum(tally[k].get(size, 0) for k in tally)
        gt_row.append(col_total if col_total else '')
        grand_total += col_total
    gt_row.append(grand_total)
    ws_sizes.append(gt_row)
    for col in range(1, len(size_hdr) + 1):
        cell = ws_sizes.cell(row=row_idx, column=col)
        cell.fill   = PatternFill('solid', fgColor='3A3D48')
        cell.font   = Font(bold=True, color='FFFFFF')
        cell.border = THIN_BORDER

    set_col_widths(ws_sizes, [18, 28, 18] + [6] * len(sorted_sizes) + [8])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _payment_label(order):
    method = (getattr(order, 'payment_method', None) or '').lower()
    return {
        'stripe': 'Card',
        'paypal': 'PayPal / Venmo',
        'cash': 'Cash',
    }.get(method, method.title())


def _stage_label(stage):
    return (stage or '').replace('_', ' ').title()


_PLACEMENT_LABELS = {
    'center_chest': 'Center chest',
    'left_chest': 'Left chest',
    'right_chest': 'Right chest',
    'center_back': 'Center back',
    'full_front': 'Full front',
    'full_back': 'Full back',
}


def _placement_label(placement):
    if not placement:
        return ''
    return _PLACEMENT_LABELS.get(placement, placement.replace('_', ' ').capitalize())


def _ship_to(order):
    if (getattr(order, 'fulfillment_method', None) or '') != 'shipping':
        return ''
    city_line = ' '.join(x for x in (
        ((order.shipping_city or '') + ',') if order.shipping_city else '',
        order.shipping_state or '',
        order.shipping_zip or '',
    ) if x)
    parts = [
        order.shipping_recipient or '',
        order.shipping_street or '',
        order.shipping_street_2 or '',
        city_line,
    ]
    return ', '.join(x for x in parts if x)
