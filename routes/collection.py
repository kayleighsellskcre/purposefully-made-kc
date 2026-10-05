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
        headers={'Content-Disposition': f'attachment; filename="roster_{safe_name}.xlsx"'},
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
        xlsx_bytes = _build_group_order_xlsx(collection)
    except Exception as e:
        current_app.logger.exception('Excel export failed for collection %s: %s', slug, e)
        flash('Could not generate the Excel file. Please try again.', 'error')
        return redirect(url_for('collection.share', slug=slug))

    safe_name = slug.replace('/', '_').replace(' ', '_')
    filename  = f"group_order_{safe_name}.xlsx"
    return Response(
        xlsx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


def _build_group_order_xlsx(collection):
    """Build and return raw .xlsx bytes for the given collection."""
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

    ws_sum['A2'] = f'Exported: {datetime.utcnow().strftime("%B %d, %Y %H:%M UTC")}'
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

    for row in range(5, 9):
        ws_sum.cell(row=row, column=1).font = Font(bold=True)

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
    ]
    ws_ord.append(ord_headers)
    style_header_row(ws_ord, 1, len(ord_headers))
    ws_ord.row_dimensions[1].height = 22

    for idx, order in enumerate(orders, start=2):
        items_count = sum(i.quantity for i in order.items)
        ws_ord.append([
            order.order_number,
            order.created_at.strftime('%Y-%m-%d %H:%M') if order.created_at else '',
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
        ])
        style_data_row(ws_ord, idx, len(ord_headers), alt=(idx % 2 == 0))
        for col in (14, 15, 16, 17):
            ws_ord.cell(row=idx, column=col).number_format = MONEY_FMT

    set_col_widths(ws_ord, [18, 16, 22, 28, 14, 12, 12, 18, 18, 10, 10, 14, 7, 10, 10, 8, 10, 30])

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
