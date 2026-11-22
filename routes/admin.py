from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, Response
from sqlalchemy import or_
from flask_login import login_required, current_user
from functools import wraps
from models import (db, Product, Collection, Order, OrderItem, Design, User, ProductColorVariant,
                    Vendor, ApparelInventory, TransferInventory, Supply, GrowthMetric, FinancialEntry,
                    CustomDesignRequest, SiteError, AdminNotification)
from werkzeug.utils import secure_filename
from utils import sales_tax
from datetime import datetime
import json
import re
import os
import csv
from io import StringIO, BytesIO
from pathlib import Path

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.context_processor
def _inject_ops_flow():
    try:
        from utils.ops_flow import template_context
        return template_context()
    except Exception:
        return {
            'ops_show_flow': False,
            'ops_flow_steps': [],
            'ops_collection': '',
            'ops_collections': [],
            'ops_url': lambda endpoint, **kwargs: url_for(endpoint),
            'ops_stage_tools': {},
        }

# Only this email is allowed to access admin. All other users get customer portals only.
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to continue.', 'error')
            return redirect(url_for('auth.login'))
        # Allow any account with is_admin=True
        if not getattr(current_user, 'is_admin', False):
            flash('Access denied. Admin access is restricted.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.before_request
def _admin_account_firewall():
    """Second lock on every /admin URL so a missed decorator cannot leak shop data."""
    if not current_user.is_authenticated:
        flash('Please log in to continue.', 'error')
        return redirect(url_for('auth.login', next=request.path))
    if not getattr(current_user, 'is_admin', False):
        flash('Access denied. Admin access is restricted.', 'error')
        return redirect(url_for('main.index'))


_ALLOWED_DESIGN_EXTS = ['.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif']

# Short prefix used in auto-generated SKUs, keyed by gallery folder slug
_SKU_PREFIXES = {
    'kc':             'KC',
    'faith':          'FTH',
    'sports':         'SPT',
    'school':         'SCH',
    'couples':        'FAM',
    'holiday':        'HOL',
    'evergreen':      'FAV',
    'funny':          'FUN',
    'luxury_basics':  'LUX',
    'music':          'MUS',
    'custom_orders':  'DSG',
}


def _next_sku(folder: str) -> str:
    """Return the next sequential SKU for the given folder, e.g. KC-003."""
    import re as _re
    prefix = _SKU_PREFIXES.get(folder or 'custom_orders', 'DSG')
    existing = (
        Design.query
        .filter(Design.sku.ilike(f'{prefix}-%'), Design.is_gallery == True)
        .with_entities(Design.sku)
        .all()
    )
    pat = _re.compile(r'^' + _re.escape(prefix) + r'-(\d+)$', _re.IGNORECASE)
    max_n = 0
    for (sku,) in existing:
        if sku:
            m = pat.match(sku)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f'{prefix}-{str(max_n + 1).zfill(3)}'


def _detect_image_color(file_bytes: bytes) -> str:
    """Return a human-readable dominant color name for image bytes.

    Ignores transparent pixels (alpha < 128) and near-white pixels so we pick
    up the actual ink color rather than the transparent/white background.
    Returns '' if detection fails or no clear color is found.
    """
    _NAMED_COLORS = [
        ('White',       (255, 255, 255)),
        ('Black',       (  0,   0,   0)),
        ('Charcoal',    ( 54,  69,  79)),
        ('Gray',        (128, 128, 128)),
        ('Silver',      (192, 192, 192)),
        ('Red',         (220,  30,  30)),
        ('Maroon',      (128,   0,   0)),
        ('Burgundy',    (128,   0,  32)),
        ('Coral',       (255, 127,  80)),
        ('Pink',        (255, 182, 193)),
        ('Hot Pink',    (255,  20, 147)),
        ('Orange',      (255, 140,   0)),
        ('Gold',        (218, 165,  32)),
        ('Yellow',      (255, 220,   0)),
        ('Navy',        (  0,   0, 128)),
        ('Royal Blue',  ( 65, 105, 225)),
        ('Blue',        (  0, 120, 210)),
        ('Sky Blue',    (135, 206, 235)),
        ('Teal',        (  0, 128, 128)),
        ('Green',       ( 34, 139,  34)),
        ('Forest Green',(  0, 100,   0)),
        ('Olive',       (128, 128,   0)),
        ('Purple',      (128,   0, 128)),
        ('Lavender',    (230, 230, 250)),
        ('Brown',       (139,  69,  19)),
        ('Tan',         (210, 180, 140)),
        ('Cream',       (255, 253, 208)),
    ]
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(file_bytes)).convert('RGBA')
        img.thumbnail((120, 120), Image.LANCZOS)
        pixels = list(img.getdata())
        # Keep only opaque, non-white pixels
        visible = [
            (r, g, b) for r, g, b, a in pixels
            if a >= 128 and not (r > 230 and g > 230 and b > 230)
        ]
        if not visible:
            return ''
        n = len(visible)
        avg_r = sum(p[0] for p in visible) // n
        avg_g = sum(p[1] for p in visible) // n
        avg_b = sum(p[2] for p in visible) // n
        def _dist(rgb):
            return ((avg_r - rgb[0]) ** 2 + (avg_g - rgb[1]) ** 2 + (avg_b - rgb[2]) ** 2) ** 0.5
        name, _ = min(_NAMED_COLORS, key=lambda nc: _dist(nc[1]))
        return name
    except Exception:
        return ''


class DesignUploadError(Exception):
    """Raised when an artwork upload genuinely fails to store."""


def _save_collection_design(file, user_id):
    """Save artwork for a group order.

    Skip background-cut here — that pipeline can take minutes on a phone
    photo and freeze Create Group Order on 'Creating…'. The file is stored
    as uploaded; cut happens later when someone actually prints it.

    Organizer / customer uploads stay on that user's My Designs. Admin
    uploads are group-order-only (no uploaded_by_user_id) so they do not
    clutter the admin account library.
    """
    owner_id = user_id
    if user_id:
        from models import User
        uploader = User.query.get(user_id)
        if uploader is not None and getattr(uploader, 'is_admin', False):
            owner_id = None

    design = _save_uploaded_design(file, owner_id, process_artwork=False)
    if design is not None:
        design.is_gallery = False
        # Ensure admin group-order logos never land in My Designs even if
        # _save_uploaded_design defaults change later.
        if owner_id is None:
            design.uploaded_by_user_id = None
    return design


from utils.design_metadata import title_from_filename


def _save_uploaded_design(file, user_id, *, process_artwork=True):
    """Save an uploaded file to the Design gallery. Returns Design or None."""
    if not file or not file.filename:
        return None
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return None
    name, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in _ALLOWED_DESIGN_EXTS:
        return None

    from utils.cloud_storage import upload_image
    import time
    timestamp = int(time.time())
    unique_name = f"gallery_{name}_{timestamp}{ext}"
    try:
        file_path = upload_image(
            file,
            current_app._get_current_object(),
            subfolder='designs',
            public_id_prefix='gallery',
            process_artwork=process_artwork,
        )
    except Exception as e:
        current_app.logger.exception('Gallery design upload failed (%s): %s', filename, e)
        return None
    if not file_path:
        current_app.logger.error('Gallery design upload returned no path (%s)', filename)
        return None
    title = title_from_filename(name)
    design = Design(
        filename=unique_name,
        original_filename=file.filename,
        file_path=file_path,
        is_gallery=True,
        title=title,
        folder='custom_orders',
        uploaded_by_user_id=user_id,
        has_transparency=True,
    )
    try:
        from PIL import Image
        if not file_path.startswith('http'):
            from pathlib import Path as _Path
            filepath = _Path('static') / file_path
            img = Image.open(filepath)
            design.width, design.height = img.size
            design.file_size = filepath.stat().st_size
    except Exception:
        pass
    db.session.add(design)
    db.session.flush()
    return design


def _save_design_for_user(file, user_id, title=None, design_fee=0):
    """Save print-ready artwork for a customer profile.

    Stores locally first (instant), then the caller promotes to R2 after commit.
    Skips background-cut — admin uploads are already edited.
    Returns (design, local_path, r2_prefix) or (None, None, None).
    """
    if not file or not file.filename:
        return None, None, None
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return None, None, None
    name, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in _ALLOWED_DESIGN_EXTS:
        return None, None, None

    try:
        file.stream.seek(0)
    except Exception:
        pass
    file_bytes = file.read()
    if not file_bytes:
        raise DesignUploadError('storage_failed')

    import time
    timestamp = int(time.time())
    unique_name = f"user_{user_id}_{name}_{timestamp}{ext}"
    prefix = f'user_{user_id}'
    upload_dir = Path(current_app.config['UPLOAD_FOLDER']) / 'designs'
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / unique_name).write_bytes(file_bytes)
    except Exception as e:
        current_app.logger.exception(
            'Design upload to user %s profile failed (%s): %s', user_id, filename, e,
        )
        raise DesignUploadError('storage_failed') from e

    file_path = f'uploads/designs/{unique_name}'
    local_path = str(upload_dir / unique_name)
    design = Design(
        filename=unique_name,
        original_filename=file.filename,
        file_path=file_path,
        is_gallery=False,
        title=title or title_from_filename(name),
        folder='custom_orders',
        uploaded_by_user_id=user_id,
        design_fee=float(design_fee or 0),
        has_transparency=True,
    )
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(file_bytes))
        design.width, design.height = img.size
        design.file_size = len(file_bytes)
    except Exception:
        pass
    db.session.add(design)
    db.session.flush()
    return design, local_path, prefix


def _form_money(field, default=None):
    """Parse a money field from the current form. Returns default when absent.

    float(request.form.get(...)) crashed with TypeError whenever a numeric
    input arrived empty or missing, which took down the product save.
    """
    raw = request.form.get(field)
    if raw is None:
        return default
    raw = str(raw).strip().replace('$', '').replace(',', '')
    if raw == '':
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _email_design_request_decision(req_id, decision, reason=None):
    req = CustomDesignRequest.query.get(req_id)
    if req:
        _send_design_request_decision_email(req, decision, reason)


def _promote_design_to_r2(design_id, local_path, prefix):
    if not local_path:
        return
    from pathlib import Path as _Path
    path = _Path(local_path)
    if not path.is_file():
        return
    file_bytes = path.read_bytes()
    from utils.cloud_storage import r2_configured, upload_bytes
    app = current_app._get_current_object()
    if not r2_configured(app):
        return
    url = upload_bytes(file_bytes, app, path.name, subfolder='designs', public_id_prefix=prefix)
    if not url:
        return
    d = Design.query.get(design_id)
    if d:
        d.file_path = url
        db.session.commit()


@admin_bp.route('/')
@admin_required
def index():
    """Admin dashboard"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        _cst = ZoneInfo("America/Chicago")
        _now = datetime.now(_cst)
    except Exception:
        _now = datetime.now()
    # Statistics
    total_orders    = Order.query.count()
    from utils.production_stages import orders_for_stages
    pending_orders  = orders_for_stages(['order_received']).count()           # exactly what the Order Received list shows
    in_production   = Order.query.filter_by(status='in_production').count()
    ready_for_pickup = Order.query.filter_by(status='ready').count()
    total_revenue   = db.session.query(db.func.sum(Order.total)).filter(
        Order.payment_status == 'paid'
    ).scalar() or 0
    pending_design_requests = CustomDesignRequest.query.filter_by(status='pending').count()
    email_problems_count = 0
    try:
        from models import EmailFailure
        email_problems_count = EmailFailure.query.filter_by(resolved=False).count()
    except Exception:
        db.session.rollback()
    recent_site_errors = 0
    try:
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_site_errors = SiteError.query.filter(SiteError.created_at >= cutoff).count()
    except Exception:
        recent_site_errors = 0

    # Recent orders — last 5 by created date, any status (paid/completed included)
    recent_orders = (
        Order.query
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )

    # Greeting based on local business time (CST/CDT)
    hour = _now.hour
    if hour < 12:
        greeting = 'Good morning'
    elif hour < 17:
        greeting = 'Good afternoon'
    else:
        greeting = 'Good evening'

    admin_name = (current_user.first_name or '').strip() or None

    try:
        from utils.admin_notifications import backfill_pending_design_requests
        backfill_pending_design_requests()
    except Exception:
        from utils.quiet_errors import report_quiet
        report_quiet('catching up pending design requests')
        try:
            db.session.rollback()
        except Exception:
            pass

    return render_template('admin/dashboard.html',
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         in_production=in_production,
                         ready_for_pickup=ready_for_pickup,
                         total_revenue=total_revenue,
                         recent_orders=recent_orders,
                         pending_design_requests=pending_design_requests,
                         recent_site_errors=recent_site_errors,
                         email_problems_count=email_problems_count,
                         greeting=greeting,
                         admin_name=admin_name,
                         now=_now)


@admin_bp.route('/site-errors')
@admin_required
def site_errors():
    """Recent customer-facing 500s, matched by the reference ID on the error page."""
    from utils.error_notify import (
        redact_query_string,
        safe_error_message,
        safe_referrer_display,
    )
    try:
        rows = SiteError.query.order_by(SiteError.created_at.desc()).limit(50).all()
    except Exception:
        db.session.rollback()
        rows = []

    # Never render raw query strings / long exception dumps in the UI.
    errors = []
    for err in rows:
        errors.append({
            'created_at': err.created_at,
            'error_id': err.error_id,
            'method': err.method,
            'path': err.path,
            'query_safe': redact_query_string(err.query_string or ''),
            'referrer_safe': safe_referrer_display(err.referrer or ''),
            'message_safe': safe_error_message(err.message),
            'notified': err.notified,
        })
    return render_template('admin/site_errors.html', errors=errors)


@admin_bp.route('/site-errors/<error_id>/delete', methods=['POST'])
@admin_required
def site_error_delete(error_id):
    """Dismiss one recorded 500 after you have checked it."""
    row = SiteError.query.filter_by(error_id=error_id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    flash('That error is off the list.', 'success')
    return redirect(url_for('admin.site_errors'))


@admin_bp.route('/site-errors/clear', methods=['POST'])
@admin_required
def site_errors_clear():
    """Clear the whole error list once the underlying issues are handled."""
    SiteError.query.delete()
    db.session.commit()
    flash('All site errors are cleared.', 'success')
    return redirect(url_for('admin.site_errors'))


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
    from utils.cloud_storage import image_url, r2_configured, store_upload
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


# ===== PRODUCTS =====

@admin_bp.route('/products')
@admin_required
def products():
    """Manage products"""
    try:
        import os
        # Optional filter/sort by Customer Favorite status
        fav_filter = request.args.get('favorites') == '1'
        query = Product.query
        if fav_filter:
            query = query.filter(Product.is_customer_favorite.is_(True))
        # Always surface favorites first, then by style number
        products = query.order_by(Product.is_customer_favorite.desc(),
                                  Product.style_number).all()
        favorite_count = Product.query.filter(Product.is_customer_favorite.is_(True)).count()

        # Size/color counts + lightest-color thumbnail in one variant pass
        from collections import defaultdict
        from utils.mockups import (lightest_front_mockup_url, sorted_front_mockup_urls, get_first_shop_image_url,
                                   get_carousel_colors_for_product)

        variants_by_pid = defaultdict(list)
        if products:
            for variant in ProductColorVariant.query.filter(
                ProductColorVariant.product_id.in_([p.id for p in products])
            ).all():
                variants_by_pid[variant.product_id].append(variant)

        for p in products:
            try:
                p.size_count = len(json.loads(p.available_sizes)) if p.available_sizes else 0
            except (TypeError, ValueError):
                p.size_count = 0
            variants = variants_by_pid.get(p.id, [])
            variant_count = len(variants)
            try:
                parsed = json.loads(p.available_colors) if p.available_colors else []
                json_count = len(parsed) if isinstance(parsed, list) else 0
            except (TypeError, ValueError):
                json_count = 0
            p.color_count = variant_count if variant_count > 0 else min(json_count, 200)
            # Build ordered fallback list: local files first (guaranteed to exist),
            # then DB/CDN urls (may 404), then template url
            local_url = get_first_shop_image_url(p, current_app, carousel=get_carousel_colors_for_product(p, current_app, variants=variants))
            db_urls = sorted_front_mockup_urls(variants)
            seen = set()
            all_urls = []
            for u in ([local_url] if local_url else []) + db_urls:
                if u and u not in seen:
                    seen.add(u)
                    all_urls.append(u)
            template_url = (p.front_mockup_template or '').strip()
            if template_url and template_url not in seen:
                all_urls.append(template_url)
            p.thumb_url = all_urls[0] if all_urls else None
            p.thumb_fallbacks = all_urls[1:]  # remaining URLs for JS cascade

        # Check if S&S API is configured - check environment variable directly
        api_key = os.getenv('SSACTIVEWEAR_API_KEY')
        api_configured = bool(api_key) and api_key != 'your_ss_activewear_api_key_here'
        
        # Get last sync time
        last_sync = ProductColorVariant.query.order_by(ProductColorVariant.last_synced.desc()).first()
        last_sync_time = last_sync.last_synced if last_sync else None
        try:
            from datetime import datetime as _dt
            from services.color_availability import SYNC_OK_KEY
            from utils.site_settings import get_setting
            last_sync_time = _dt.fromisoformat(get_setting(SYNC_OK_KEY, '')) or last_sync_time
        except (TypeError, ValueError):
            pass  # no supplier stock sync recorded yet: fall back to the newest color row

        return render_template('admin/products.html',
                             products=products,
                             api_configured=api_configured,
                             last_sync_time=last_sync_time,
                             fav_filter=fav_filter,
                             favorite_count=favorite_count)
    
    except Exception as e:
        # Comprehensive error handling for admin products page
        import sys
        import traceback
        print(f"ERROR in admin products: {e}", file=sys.stderr)
        traceback.print_exc()
        
        # Try to determine if it's a schema issue
        error_msg = str(e).lower()
        if 'no such column' in error_msg or 'column' in error_msg and 'does not exist' in error_msg:
            flash('Database schema is updating. Please wait 30 seconds and refresh the page.', 'warning')
        else:
            flash(f'Error loading products page: {str(e)}', 'error')
        
        # Return empty page with API configured check
        import os
        api_key = os.getenv('SSACTIVEWEAR_API_KEY')
        api_configured = bool(api_key) and api_key != 'your_ss_activewear_api_key_here'
        
        return render_template('admin/products.html',
                             products=[],
                             api_configured=api_configured,
                             last_sync_time=None)


@admin_bp.route('/products/fetch-ss-images', methods=['POST'])
@admin_required
def fetch_ss_images():
    """
    Get Product Images — two-phase:
      Phase 1: S&S Activewear API — create/update color variants with ghost images
      Phase 2: Local static/sanmar/ files — link any already-on-disk images
    Phase 2 always runs, even if Phase 1 fails or S&S is unavailable.
    """
    import os, sys, re
    from datetime import datetime
    from pathlib import Path
    from models import db, Product, ProductColorVariant

    api_key = os.getenv('SSACTIVEWEAR_API_KEY', '').strip()
    account_number = os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER', '').strip()

    # ── Shared state ───────────────────────────────────────────────────────────
    created_variants = 0
    updated_variants = 0
    updated_products = 0
    skipped = 0
    local_linked = 0
    errors = []
    ss_status = ''

    # ── Phase 1: Local static/sanmar/ images (fast, synchronous) ──────────────
    try:
        sanmar_dir = Path(current_app.root_path) / 'static' / 'sanmar'
        if sanmar_dir.is_dir():
            for style_folder in sanmar_dir.iterdir():
                if not style_folder.is_dir():
                    continue
                folder_name = style_folder.name
                bc_style    = 'BC' + folder_name
                cc_style    = 'CC' + folder_name
                product = Product.query.filter(
                    db.or_(
                        Product.style_number == bc_style,
                        Product.style_number == cc_style,
                        Product.style_number == folder_name,
                    )
                ).first()
                if not product:
                    continue

                file_map: dict = {}
                for f in style_folder.iterdir():
                    if not f.is_file():
                        continue
                    m = re.match(rf'^{re.escape(folder_name)}_(.+?)_(front|back)\.jpe?g$', f.name, re.IGNORECASE)
                    if not m:
                        continue
                    key = m.group(1).replace('_', ' ').lower()
                    side = m.group(2).lower()
                    if key not in file_map:
                        file_map[key] = {}
                    file_map[key][side] = f'/static/sanmar/{folder_name}/{f.name}'

                existing = {
                    (v.color_name or '').lower(): v
                    for v in ProductColorVariant.query.filter_by(product_id=product.id).all()
                }

                for color_key, paths in file_map.items():
                    color_name_display = color_key.title()
                    if color_key in existing:
                        v = existing[color_key]
                        changed = False
                        if not v.front_image_url and paths.get('front'):
                            v.front_image_url = paths['front']; changed = True
                        if not v.back_image_url and paths.get('back'):
                            v.back_image_url = paths['back']; changed = True
                        if changed:
                            local_linked += 1
                    else:
                        db.session.add(ProductColorVariant(
                            product_id=product.id,
                            color_name=color_name_display,
                            front_image_url=paths.get('front'),
                            back_image_url=paths.get('back'),
                        ))
                        local_linked += 1

                if not product.front_mockup_template and file_map:
                    ff = next((v['front'] for v in file_map.values() if 'front' in v), None)
                    if ff: product.front_mockup_template = ff
                if not product.back_mockup_template and file_map:
                    fb = next((v['back'] for v in file_map.values() if 'back' in v), None)
                    if fb: product.back_mockup_template = fb

            db.session.commit()
    except Exception as e:
        db.session.rollback()
        errors.append(f'Local link error: {e}')

    # ── Phase 2: S&S Activewear API in background thread (no 30s timeout) ─────
    if api_key and account_number:
        import threading
        app_ref = current_app._get_current_object()

        def _fetch_ss_background():
            import sys
            from datetime import datetime as _dt
            with app_ref.app_context():
                try:
                    from services.ssactivewear_api import SSActivewearAPI
                    from models import db as _db, Product as _P, ProductColorVariant as _PCV
                    _api = SSActivewearAPI(api_key=api_key, account_number=account_number)
                    cdn = 'https://cdn.ssactivewear.com/'

                    def _img(url):
                        if not url: return None
                        return url if url.startswith('http') else cdn + url.lstrip('/')

                    for product in _P.query.filter(_P.style_number.ilike('BC%')).all():
                        ss_style = product.style_number[2:] if product.style_number.upper().startswith('BC') else product.style_number
                        try:
                            ss_rows = _api.get_products_by_style_number(ss_style) or _api.get_products_by_style_number(product.style_number)
                            if not ss_rows:
                                continue

                            color_map: dict = {}
                            for row in ss_rows:
                                cname = (row.get('colorName') or '').strip()
                                if not cname: continue
                                k = cname.lower()
                                if k in color_map: continue
                                front = _img(row.get('ghostFrontImage') or row.get('colorFrontImage') or row.get('frontImage'))
                                back  = _img(row.get('ghostBackImage')  or row.get('colorBackImage')  or row.get('backImage'))
                                if front or back:
                                    color_map[k] = {'name': cname, 'front': front, 'back': back,
                                                    'hex': row.get('colorHex') or row.get('hex')}
                            if not color_map:
                                continue

                            existing = {(v.color_name or '').lower(): v for v in _PCV.query.filter_by(product_id=product.id).all()}
                            changed = False
                            for k, imgs in color_map.items():
                                if k in existing:
                                    v = existing[k]
                                    if imgs['front'] and not v.front_image_url:
                                        v.front_image_url = imgs['front']; changed = True
                                    if imgs['back'] and not v.back_image_url:
                                        v.back_image_url = imgs['back']; changed = True
                                else:
                                    _db.session.add(_PCV(
                                        product_id=product.id,
                                        color_name=imgs['name'], color_hex=imgs.get('hex'),
                                        front_image_url=imgs['front'], back_image_url=imgs['back'],
                                        last_synced=_dt.utcnow(),
                                    ))
                                    changed = True

                            if changed:
                                if not product.front_mockup_template:
                                    ff = next((v['front'] for v in color_map.values() if v.get('front')), None)
                                    if ff: product.front_mockup_template = ff
                                _db.session.commit()

                        except Exception as e:
                            _db.session.rollback()
                            print(f'SS bg [{product.style_number}]: {e}', file=sys.stderr)

                    print('SS background image fetch complete.', file=sys.stderr)
                except Exception as e:
                    print(f'SS background fetch failed: {e}', file=sys.stderr)

        threading.Thread(target=_fetch_ss_background, daemon=True).start()
        ss_msg = ' S&S images are fetching in the background for all other styles — they\'ll appear within a few minutes.'
    else:
        ss_msg = ''

    # ── Flash ──────────────────────────────────────────────────────────────────
    msg = f'Done! Created/linked {local_linked} color variants from your uploaded images.' if local_linked else 'Local images processed.'
    msg += ss_msg
    if errors:
        msg += f' Errors: {", ".join(errors[:3])}'
    flash(msg, 'success' if not errors else 'warning')

    return redirect(url_for('admin.products'))


@admin_bp.route('/products/sync-sanmar-inventory', methods=['POST'])
@admin_required
def sync_sanmar_inventory():
    """Sync live warehouse quantities from SanMar and S&S into every active style."""
    from services.inventory_sync import start_inventory_sync_thread

    start_inventory_sync_thread(current_app._get_current_object())
    flash(
        'Live inventory sync started for SanMar and S&S. '
        'In-stock / out-of-stock quantities will refresh over the next few minutes.',
        'success',
    )
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/import-bella-canvas-csv', methods=['POST'])
@admin_required
def import_bella_canvas_csv():
    """Import products from a BellaCanvas SDL CSV file upload."""
    import sys
    from services.bella_canvas_csv import parse_csv
    from models import ProductColorVariant
    from datetime import datetime

    uploaded = request.files.get('csv_file')
    if not uploaded or not uploaded.filename:
        flash('No file selected. Please choose a CSV file to upload.', 'error')
        return redirect(url_for('admin.products'))

    if not uploaded.filename.lower().endswith('.csv'):
        flash('Please upload a .csv file (the BellaCanvasData file from SanMar).', 'error')
        return redirect(url_for('admin.products'))

    try:
        products_data = parse_csv(uploaded)
    except Exception as exc:
        flash(f'Could not parse CSV: {exc}', 'error')
        return redirect(url_for('admin.products'))

    if not products_data:
        flash('No products found in the CSV file.', 'warning')
        return redirect(url_for('admin.products'))

    from models import Product, db
    added = updated = variants_added = variants_updated = 0

    for product_data in products_data:
        color_variants_data = product_data.pop('color_variants', [])
        style_num = product_data.get('style_number', '')
        if not style_num:
            continue

        # Match existing products whether they were stored with or without the BC prefix.
        # e.g. CSV style "BC3001C" should update the old S&S product stored as "3001C".
        style_no_prefix = style_num.lstrip('BC').lstrip('bc') if style_num.upper().startswith('BC') else style_num
        existing = (
            Product.query.filter_by(style_number=style_num).first()
            or Product.query.filter_by(style_number=style_no_prefix).first()
        )

        if existing:
            for key, value in product_data.items():
                # Never overwrite admin-set price
                if key == 'base_price':
                    continue
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.is_active = product_data.get('is_active', True)
            product = existing
            updated += 1
        else:
            product = Product(**product_data)
            db.session.add(product)
            db.session.flush()
            added += 1

        for cv_data in color_variants_data:
            color_name = cv_data.get('color_name', '')
            if not color_name:
                continue
            existing_cv = ProductColorVariant.query.filter_by(
                product_id=product.id, color_name=color_name
            ).first()
            if existing_cv:
                if cv_data.get('front_image_url'):
                    existing_cv.front_image_url = cv_data['front_image_url']
                if cv_data.get('back_image_url'):
                    existing_cv.back_image_url = cv_data['back_image_url']
                if cv_data.get('color_swatch_url'):
                    existing_cv.color_swatch_url = cv_data['color_swatch_url']
                existing_cv.last_synced = datetime.utcnow()
                variants_updated += 1
            else:
                new_cv = ProductColorVariant(
                    product_id=product.id,
                    color_name=color_name,
                    front_image_url=cv_data.get('front_image_url', ''),
                    back_image_url=cv_data.get('back_image_url', ''),
                    color_swatch_url=cv_data.get('color_swatch_url', ''),
                    size_inventory=json.dumps({}),
                )
                db.session.add(new_cv)
                variants_added += 1

    db.session.commit()

    flash(
        f'CSV import complete: {added} new products, {updated} updated, '
        f'{variants_added} new color variants, {variants_updated} updated.',
        'success'
    )
    print(
        f'[CSV Import] {added} added, {updated} updated, '
        f'{variants_added} variants added, {variants_updated} variants updated.',
        file=sys.stderr, flush=True,
    )
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/add', methods=['GET', 'POST'])
@admin_required
def add_product():
    """Add new product"""
    if request.method == 'POST':
        from utils.json_fields import store_json_list
        base_price = _form_money('base_price')
        if base_price is None or base_price < 0:
            flash('Enter a base price (a number, 0 or higher) before saving.', 'error')
            return render_template('admin/add_product.html')
        product = Product(
            style_number=request.form.get('style_number'),
            name=request.form.get('name'),
            category=request.form.get('category'),
            description=request.form.get('description'),
            base_price=base_price,
            wholesale_cost=_form_money('wholesale_cost', 0.0),
            is_active=False,
            is_customer_favorite=request.form.get('is_customer_favorite') == 'on',
            available_sizes=store_json_list(request.form.get('available_sizes')),
            available_colors=store_json_list(request.form.get('available_colors')),
            print_area_config=request.form.get('print_area_config')
        )
        
        db.session.add(product)
        db.session.commit()

        if request.form.get('is_active') == 'on':
            flash('Product added. Add a product photo before making this active.', 'error')
        else:
            flash('Product added successfully', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/add_product.html')


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    """Edit product"""
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        from werkzeug.utils import secure_filename
        import os

        # Validate the price before touching the row, so a bad value cannot
        # leave the product half-updated.
        base_price = _form_money('base_price')
        if base_price is None or base_price < 0:
            flash('Enter a base price (a number, 0 or higher) before saving.', 'error')
            return render_template('admin/edit_product.html', product=product)

        product.style_number = request.form.get('style_number')
        product.name = request.form.get('name')
        product.brand = request.form.get('brand')
        product.category = request.form.get('category')
        product.age_group = request.form.get('age_group')
        product.fit_type = request.form.get('fit_type')
        product.neck_style = request.form.get('neck_style')
        product.sleeve_length = request.form.get('sleeve_length')
        product.family_key = request.form.get('family_key', '').strip() or None
        product.description = request.form.get('description')
        product.base_price = base_price
        product.wholesale_cost = _form_money('wholesale_cost', 0.0)
        want_active = request.form.get('is_active') == 'on'
        product.is_customer_favorite = request.form.get('is_customer_favorite') == 'on'
        from utils.json_fields import store_json_list
        product.available_sizes = store_json_list(request.form.get('available_sizes'))
        product.available_colors = store_json_list(request.form.get('available_colors'))
        product.print_area_config = request.form.get('print_area_config')
        
        # Sizing and fabric details
        product.fit_guide = request.form.get('fit_guide')
        product.fabric_details = request.form.get('fabric_details')
        
        # Handle front image upload
        if 'front_image' in request.files:
            front_file = request.files['front_image']
            if front_file and front_file.filename:
                from utils.cloud_storage import store_upload
                product.front_mockup_template = store_upload(
                    front_file, 'products', secure_filename(f"{product.style_number}_front"))
        
        # Handle back image upload
        if 'back_image' in request.files:
            back_file = request.files['back_image']
            if back_file and back_file.filename:
                from utils.cloud_storage import store_upload
                product.back_mockup_template = store_upload(
                    back_file, 'products', secure_filename(f"{product.style_number}_back"))

        from utils.mockups import product_has_shop_image
        if want_active and not product_has_shop_image(product):
            product.is_active = False
            flash('Add a product photo before making this active.', 'error')
        else:
            product.is_active = want_active
        
        db.session.commit()
        flash('Product updated successfully', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/edit_product.html', product=product)


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    """Remove a product from the catalog.

    OrderItem.product_id is a non-nullable foreign key, so a style that
    appears in any past order cannot be removed without leaving that order
    pointing at nothing. Those are hidden from the shop instead. Styles
    nobody has ever bought — the unbuyable ones with no sizes, for example —
    are deleted outright, including colour variants, favorites, and group-order
    memberships.
    """
    from sqlalchemy.exc import IntegrityError
    from models import Favorite, collection_products

    product = Product.query.get_or_404(product_id)
    name = product.name
    style = product.style_number

    if product.order_items.count():
        product.is_active = False
        db.session.commit()
        flash(
            f'"{name}" appears in past orders, so it was hidden from the shop '
            f'instead of deleted. Order history stays readable.',
            'success',
        )
        return redirect(url_for('admin.products'))

    Favorite.query.filter_by(product_id=product.id).delete(synchronize_session=False)
    db.session.execute(
        collection_products.delete().where(
            collection_products.c.product_id == product.id
        )
    )
    db.session.delete(product)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        leftover = Product.query.get(product_id)
        if leftover:
            leftover.is_active = False
            db.session.commit()
            flash(
                f'"{name}" could not be deleted because something still points '
                f'at it. It was hidden from the shop instead.',
                'warning',
            )
        return redirect(url_for('admin.products'))

    flash(f'"{name}" ({style}) was removed from the catalog.', 'success')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/<int:product_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_product_active(product_id):
    """Toggle a product's is_active flag and return the new state as JSON."""
    from flask import request as flask_request, jsonify
    product = Product.query.get_or_404(product_id)
    turning_on = not product.is_active
    if turning_on:
        from utils.mockups import product_has_shop_image
        if not product_has_shop_image(product):
            message = 'Add a product photo before making this active.'
            if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'ok': False,
                    'is_active': product.is_active,
                    'label': 'Inactive',
                    'message': message,
                }), 400
            flash(message, 'error')
            return redirect(url_for('admin.products'))
    product.is_active = not product.is_active
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('toggle_product_active failed: %s', e)
        if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'message': 'Could not update product. Please try again.'}), 500
        flash('Could not update product. Please try again.', 'error')
        return redirect(url_for('admin.products'))

    label   = 'Active' if product.is_active else 'Inactive'
    message = f'"{product.name}" is now {label.lower()}'

    if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'is_active': product.is_active, 'label': label, 'message': message})

    flash(message, 'success')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/<int:product_id>/toggle-favorite', methods=['POST'])
@admin_required
def toggle_product_favorite(product_id):
    """Toggle a product's Customer Favorite flag and return the new state as JSON."""
    from flask import request as flask_request, jsonify
    product = Product.query.get_or_404(product_id)
    product.is_customer_favorite = not product.is_customer_favorite
    db.session.commit()

    label = 'Customer Favorite' if product.is_customer_favorite else 'Not featured'
    message = (f'"{product.name}" is now a Customer Favorite'
               if product.is_customer_favorite
               else f'"{product.name}" removed from Customer Favorites')

    if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'is_favorite': product.is_customer_favorite,
                        'label': label, 'message': message})

    flash(message, 'success')
    return redirect(request.referrer or url_for('admin.products'))


# ===== WIDEN IMAGE IMPORT =====

@admin_bp.route('/import-widen', methods=['POST', 'OPTIONS'])
def import_widen_images():
    """
    One-shot endpoint: accepts scraped Widen flat-image data from the browser
    and bulk-upserts ProductColorVariant records.

    Auth: shared secret in JSON body (no session needed so we can POST from
    medialibrary1.com). CORS headers allow any origin. The secret comes from
    WIDEN_IMPORT_SECRET; when that is unset this endpoint refuses everything.

    Expected body:
      {
        "secret": "<the value of WIDEN_IMPORT_SECRET>",
        "images": {
          "CC1717": {
            "Dusk": {"front": "<url>", "back": "<url>"},
            ...
          },
          ...
        }
      }
    """
    from flask import request as rq, jsonify
    from models import ProductColorVariant
    from datetime import datetime

    # CORS headers on every response (preflight + actual)
    cors_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    }

    if rq.method == 'OPTIONS':
        return ('', 204, cors_headers)

    from utils.widen_import_auth import secret_matches

    body = rq.get_json(silent=True) or {}
    if not secret_matches(body.get('secret')):
        return (jsonify({'error': 'unauthorized'}), 403, cors_headers)

    images = body.get('images', {})
    if not images:
        return (jsonify({'error': 'no images data'}), 400, cors_headers)

    updated = created = skipped = 0

    for style_number, color_map in images.items():
        product = Product.query.filter_by(style_number=style_number).first()
        if not product:
            skipped += len(color_map)
            continue

        first_front = first_back = None

        for color_name, sides in color_map.items():
            front_url = sides.get('front', '')
            back_url  = sides.get('back', '')
            if not front_url and not back_url:
                skipped += 1
                continue

            variant = ProductColorVariant.query.filter(
                ProductColorVariant.product_id == product.id,
                db.func.lower(ProductColorVariant.color_name) == color_name.lower()
            ).first()

            if variant:
                if front_url: variant.front_image_url = front_url
                if back_url:  variant.back_image_url  = back_url
                variant.last_synced = datetime.utcnow()
                updated += 1
            else:
                db.session.add(ProductColorVariant(
                    product_id=product.id,
                    color_name=color_name,
                    front_image_url=front_url,
                    back_image_url=back_url,
                    last_synced=datetime.utcnow(),
                ))
                created += 1

            if not first_front and front_url: first_front = front_url
            if not first_back  and back_url:  first_back  = back_url

        # Set product-level mockup template if not already set
        if first_front and not product.front_mockup_template:
            product.front_mockup_template = first_front
        if first_back  and not product.back_mockup_template:
            product.back_mockup_template = first_back

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return (jsonify({'error': str(e)}), 500, cors_headers)

    result = {'ok': True, 'updated': updated, 'created': created, 'skipped': skipped}
    return (jsonify(result), 200, cors_headers)


# ===== ORGANIZATIONS =====

@admin_bp.route('/organizations')
@admin_required
def organizations():
    """List all organizations."""
    from models import Organization
    orgs = Organization.query.order_by(Organization.created_at.desc()).all()
    return render_template('admin/organizations.html', orgs=orgs)


@admin_bp.route('/organizations/<int:org_id>/toggle', methods=['POST'])
@admin_required
def toggle_organization(org_id):
    from models import Organization
    org = Organization.query.get_or_404(org_id)
    org.is_active = not org.is_active
    db.session.commit()
    status = 'activated' if org.is_active else 'deactivated'
    flash(f'"{org.name}" {status}.', 'success')
    return redirect(url_for('admin.organizations'))


# ===== DAILY AFFIRMATIONS =====

@admin_bp.route('/affirmations')
@admin_required
def affirmations():
    """List all affirmations with edit/add/delete."""
    from models import Affirmation
    items = Affirmation.query.order_by(Affirmation.sort_order, Affirmation.id).all()
    return render_template('admin/affirmations.html', affirmations=items)


@admin_bp.route('/affirmations/add', methods=['POST'])
@admin_required
def affirmation_add():
    """Add a new affirmation."""
    from models import Affirmation
    from affirmations_seed import normalize_affirmation_text
    text = normalize_affirmation_text(request.form.get('text', ''))
    if not text:
        flash('Affirmation text cannot be empty.', 'error')
        return redirect(url_for('admin.affirmations'))
    max_order = db.session.query(db.func.max(Affirmation.sort_order)).scalar() or 0
    db.session.add(Affirmation(text=text, is_active=True, sort_order=max_order + 1))
    db.session.commit()
    flash('Affirmation added.', 'success')
    return redirect(url_for('admin.affirmations'))


@admin_bp.route('/affirmations/<int:aff_id>/edit', methods=['POST'])
@admin_required
def affirmation_edit(aff_id):
    """Update the text of an existing affirmation."""
    from models import Affirmation
    from affirmations_seed import normalize_affirmation_text
    aff = Affirmation.query.get_or_404(aff_id)
    text = normalize_affirmation_text(request.form.get('text', ''))
    if not text:
        flash('Affirmation text cannot be empty.', 'error')
        return redirect(url_for('admin.affirmations'))
    aff.text = text
    db.session.commit()
    flash('Affirmation updated.', 'success')
    return redirect(url_for('admin.affirmations'))


@admin_bp.route('/affirmations/<int:aff_id>/toggle', methods=['POST'])
@admin_required
def affirmation_toggle(aff_id):
    """Toggle active/inactive state."""
    from models import Affirmation
    aff = Affirmation.query.get_or_404(aff_id)
    aff.is_active = not aff.is_active
    db.session.commit()
    state = 'activated' if aff.is_active else 'deactivated'
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'is_active': aff.is_active})
    flash(f'Affirmation {state}.', 'success')
    return redirect(url_for('admin.affirmations'))


@admin_bp.route('/affirmations/<int:aff_id>/delete', methods=['POST'])
@admin_required
def affirmation_delete(aff_id):
    """Permanently delete an affirmation."""
    from models import Affirmation
    aff = Affirmation.query.get_or_404(aff_id)
    db.session.delete(aff)
    db.session.commit()
    flash('Affirmation deleted.', 'success')
    return redirect(url_for('admin.affirmations'))


# ===== DESIGN GALLERY (legacy URL → merged Designs page) =====

@admin_bp.route('/design-gallery', strict_slashes=False)
@admin_required
def design_gallery():
    """Old gallery URL — permanently redirect to the merged Designs page."""
    return redirect(_admin_designs_url('gallery'), code=301)


@admin_bp.route('/design-gallery/<int:design_id>/promote', methods=['POST'])
@admin_required
def promote_design_to_gallery(design_id):
    """Promote an existing user design to the public gallery"""
    design = Design.query.get_or_404(design_id)
    try:
        design.is_gallery = True
        if not design.title:
            design.title = title_from_filename((design.original_filename or 'Design').rsplit('.', 1)[0])[:100]
        db.session.commit()
        flash(f'"{design.title}" added to the gallery.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to promote design %s: %s', design_id, e)
        flash('Could not promote design. Please try again.', 'error')
    return redirect(url_for('admin.designs', tab='gallery'))


@admin_bp.route('/design-gallery/upload', methods=['POST'])
@admin_required
def design_gallery_upload():
    """Upload a design to the customer gallery.

    Supports both traditional form POST (redirects with flash) and AJAX
    (X-Requested-With: XMLHttpRequest) which returns JSON.  The JS batch
    uploader always uses the AJAX path.
    """
    from sqlalchemy.exc import SQLAlchemyError

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _err(msg, status=400):
        if is_ajax:
            return jsonify({'ok': False, 'error': msg}), status
        flash(msg, 'error')
        return redirect(url_for('admin.designs', tab='gallery'))

    if 'file' not in request.files:
        return _err('No file provided.')

    file = request.files['file']
    if not file or not file.filename:
        return _err('No file selected.')

    filename = secure_filename(file.filename)
    if '.' not in filename:
        return _err('File must have an extension (PNG, JPG, etc.).')

    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_DESIGN_EXTS:
        return _err('Unsupported format. Use PNG, JPG, WEBP, or HEIC.')

    try:
        # ── Folder assignment ──
        # Checkboxes send extra_categories (JS) or upload_cats (form). Color
        # variants inherit their parent's folder. New mains cannot skip this.
        from utils.design_categories import (
            assigned_gallery_folders,
            assigned_music_genres,
            compose_extra_categories,
        )
        from utils.design_variants import ensure_not_nested_parent

        from utils.design_places import apply_places, parse_places, places_to_storage_keys
        places = parse_places(request.form)
        all_cats = assigned_gallery_folders(request.form) or places_to_storage_keys(places)
        genres = assigned_music_genres(request.form)
        parent_id = request.form.get('parent_design_id', type=int)
        parent = None
        if parent_id:
            parent = ensure_not_nested_parent(Design.query.get(parent_id))
            if not (parent and parent.is_gallery and parent.id):
                parent = None
        ai_key = (current_app.config.get('OPENAI_API_KEY') or '').strip()
        if not all_cats and parent is None and not ai_key:
            return _err('Choose a folder before uploading.')       # without the AI key there is nothing to file it for you

        # Grab bytes now for color detection (stream is consumed by _save_uploaded_design)
        try:
            file.stream.seek(0)
            _color_bytes = file.stream.read()
            file.stream.seek(0)
        except Exception:
            _color_bytes = None

        # The exact same file already in the gallery: do not store a second copy. A design can sit in as
        # many collections as it needs, so there is no reason for two records.
        upload_hash = None
        if _color_bytes and parent is None:
            from utils.design_fingerprint import file_hash as _file_hash
            upload_hash = _file_hash(_color_bytes)
            twin = Design.query.filter(Design.file_hash == upload_hash, Design.is_gallery == True).first()  # noqa: E712
            if twin is not None:
                said = (f'"{twin.title or twin.original_filename or "That design"}" is already in your library, '
                        'so I did not add it again.')
                if is_ajax:
                    return jsonify({'ok': True, 'duplicate': True, 'design_id': twin.id, 'sku': twin.sku or '',
                                    'color': '', 'status': twin.ai_status or '', 'held': False, 'message': said})
                flash(said, 'info')
                return redirect(url_for('admin.designs', tab='gallery'))

        # Use _save_uploaded_design so cloud storage (R2) and background
        # removal are handled exactly the same way as every other upload path.
        design = _save_uploaded_design(file, current_user.id)
        if design is None:
            return _err('Upload failed — file could not be stored. Please try again.')

        # ── Automatic, editable name + color metadata ──
        from utils.design_metadata import (
            clean_filename_title,
            color_label_from_metadata,
            is_generic_title,
            suggest_design_metadata,
            unique_variant_label,
        )

        title = (request.form.get('title') or '').strip()
        variant_label = (request.form.get('variant_label') or '').strip()[:80]
        needs_vision = is_generic_title(title) or not variant_label or (parent is None and bool(ai_key))
        metadata = {}
        smart = None
        if needs_vision and _color_bytes and ai_key:
            # One look at the artwork gives the name, colors, collections, tags and style.
            from utils.design_ai import interpret, request_classification
            raw_result = request_classification(_color_bytes, ai_key)
            if raw_result:
                smart = interpret(raw_result, filename=file.filename, title_hint=title)
                metadata = smart

        if is_generic_title(title):
            title = (
                (metadata.get('title') or '').strip()
                or clean_filename_title(file.filename)
                or 'New Design'
            )
        design.title = title[:200]

        sku = (request.form.get('sku') or '').strip()
        if sku:
            design.sku = sku

        # Vision sees multicolor palettes; pixel detection is the no-key fallback.
        if not variant_label and _color_bytes:
            variant_label = (
                color_label_from_metadata(metadata)
                or _detect_image_color(_color_bytes)
            )

        held = False
        if parent and parent.id != design.id:
            design.parent_design_id = parent.id
            design.variant_label = unique_variant_label(
                parent, variant_label or 'Color'
            )
            if not (parent.variant_label or '').strip():
                parent.variant_label = 'Default'
            # Every color in one family uses the same customer-facing name.
            design.title = parent.title or parent.original_filename or design.title
            design.folder = parent.folder or (all_cats[0] if all_cats else 'evergreen')
            design.extra_categories = parent.extra_categories
            design.is_gallery = True
            if not sku and parent.sku:
                design.sku = parent.sku
            elif not sku:
                design.sku = _next_sku(design.folder)
        else:
            from utils.design_ai import apply_classification, classify_from_text, link_manual_folders
            if all_cats:
                folder = all_cats[0]
                extra_cats = compose_extra_categories(all_cats[1:], genres) or ''
                design.folder = folder
                design.extra_categories = extra_cats or None
            else:
                design.folder = 'evergreen'                      # the automatic filing below replaces this
            if variant_label:
                design.variant_label = unique_variant_label(None, variant_label)
            try:
                if places:
                    apply_places(design, places, current_user.id, remember=False)
                else:
                    link_manual_folders(design, all_cats)
                result = smart or classify_from_text(design.title, file.filename)
                apply_classification(design, result, chose_folder=bool(all_cats), user_id=current_user.id)
            except Exception:
                current_app.logger.exception('smart filing failed for design %s', design.id)
                design.ai_status = 'error'
            # A design the system filed by itself and is not sure about waits for your review instead of going public.
            held = (not all_cats) and design.ai_status in ('needs_review', 'error')
            if held:
                design.is_gallery = False
            elif not sku:
                design.sku = _next_sku(design.folder)

        db.session.commit()

        # Fingerprint it so duplicates and color or wording versions are noticed (suggestions only).
        try:
            if _color_bytes:
                from utils.design_fingerprint import store_fingerprint, suggest_for
                design.file_hash = upload_hash or design.file_hash
                if store_fingerprint(design, _color_bytes):
                    db.session.flush()
                    suggest_for(design)
                db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('could not fingerprint design %s', design.id)

        label = design.title or design.original_filename or 'Design'
        if is_ajax:
            note = f'"{label}" is waiting for your review.' if held else f'"{label}" added to gallery!'
            return jsonify({'ok': True, 'design_id': design.id, 'sku': design.sku or '', 'color': design.variant_label or '',
                            'status': design.ai_status or '', 'held': held, 'message': note})
        if design.parent_design_id:
            flash(
                f'Color "{design.variant_label}" added to '
                f'"{design.parent_design.title or design.parent_design.original_filename}".',
                'success',
            )
        elif held:
            flash(f'"{label}" is waiting for your review before it goes public.', 'info')
        else:
            flash(f'Design "{label}" added to gallery!', 'success')
        return redirect(url_for('admin.designs', tab='gallery'))

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('design_gallery_upload DB error: %s', e)
        return _err('A database error occurred. If this keeps happening, run the migration script.', 500)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('design_gallery_upload unexpected error: %s', e)
        return _err('Something went wrong while uploading. Please try again.', 500)


@admin_bp.route('/design-gallery/fix-skus', methods=['POST'])
@admin_required
def design_gallery_fix_skus():
    """Re-assign clean sequential SKUs to every gallery design, grouped by folder."""
    import re as _re
    try:
        # Main designs only (no variants), sorted by folder then upload date
        mains = (
            Design.query
            .filter_by(is_gallery=True, parent_design_id=None)
            .order_by(Design.folder.asc(), Design.uploaded_at.asc())
            .all()
        )
        by_folder: dict[str, list] = {}
        for d in mains:
            by_folder.setdefault(d.folder or 'custom_orders', []).append(d)

        count = 0
        for folder, items in by_folder.items():
            prefix = _SKU_PREFIXES.get(folder, 'DSG')
            for i, d in enumerate(items, start=1):
                d.sku = f'{prefix}-{str(i).zfill(3)}'
                count += 1

        # Color variants inherit their parent's SKU (keeps them grouped visually)
        variants = Design.query.filter(
            Design.is_gallery == True,
            Design.parent_design_id.isnot(None)
        ).all()
        for v in variants:
            if v.parent_design and v.parent_design.sku:
                v.sku = v.parent_design.sku

        db.session.commit()
        return jsonify({'ok': True, 'message': f'Updated SKUs for {count} designs.'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('fix_skus error: %s', e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@admin_bp.route('/design-gallery/<int:design_id>/edit', methods=['POST'])
@admin_required
def design_gallery_edit(design_id):
    """Update gallery design metadata (and optionally replace the image file)."""
    from sqlalchemy.exc import SQLAlchemyError

    design = Design.query.get_or_404(design_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    from utils.design_categories import (
        GALLERY_FOLDER_KEYS,
        assigned_music_genres,
        compose_extra_categories,
        public_extra_storage_keys,
        stored_music_genres,
    )
    GALLERY_FOLDERS = GALLERY_FOLDER_KEYS

    title = (request.form.get('title') or '').strip()
    sku = (request.form.get('sku') or '').strip()
    variant_label = (request.form.get('variant_label') or '').strip()[:80]
    # Checkbox form, legacy single-folder form, and metadata-only updates all
    # share this endpoint. Only replace categories when one of those forms
    # explicitly supplied category state.
    all_cats_raw = [
        c for c in request.form.getlist('extra_categories')
        if c in GALLERY_FOLDERS
    ]
    if request.form.get('music_genres_present') == '1':
        genres = assigned_music_genres(request.form)
    else:
        genres = stored_music_genres(design.extra_categories)
    from utils.design_places import apply_places, parse_places, places_label, places_attr, places_to_storage_keys, current_places
    places = parse_places(request.form) if request.form.get('places_present') == '1' else None
    if places is not None and not design.parent_design_id:
        if not places:
            msg = 'Choose where this design belongs.'
            if is_ajax:
                return jsonify({'ok': False, 'error': msg}), 400
            flash(msg, 'error')
            return redirect(url_for('admin.designs', tab='gallery'))
        all_cats_raw = places_to_storage_keys(places)
        folder = all_cats_raw[0]
        extra_cats = compose_extra_categories(all_cats_raw[1:], genres)
    elif places is not None:
        places = None                                   # a color version keeps its main design's places
        folder = design.folder or 'custom_orders'
        extra_cats = design.extra_categories or ''
    elif request.form.get('categories_present') == '1':
        if not all_cats_raw:
            msg = 'Choose at least one gallery category.'
            if is_ajax:
                return jsonify({'ok': False, 'error': msg}), 400
            flash(msg, 'error')
            return redirect(url_for('admin.designs', tab='gallery'))
        folder = all_cats_raw[0]
        extra_cats = compose_extra_categories(all_cats_raw[1:], genres)
    elif (request.form.get('folder') or '').strip() in GALLERY_FOLDERS:
        folder = request.form.get('folder').strip()
        extra_cats = design.extra_categories or ''
        if request.form.get('music_genres_present') == '1':
            extra_cats = compose_extra_categories(
                public_extra_storage_keys(extra_cats),
                genres,
            )
    else:
        folder = design.folder or 'custom_orders'
        extra_cats = design.extra_categories or ''
        if request.form.get('music_genres_present') == '1':
            extra_cats = compose_extra_categories(
                public_extra_storage_keys(extra_cats),
                genres,
            )

    try:
        if title:
            design.title = title[:200]
        if places:
            apply_places(design, places, current_user.id)
        design.folder = folder
        design.extra_categories = extra_cats or None
        design.sku = sku[:50] if sku else None
        if variant_label:
            from utils.design_metadata import unique_variant_label
            parent = design.parent_design if design.parent_design_id else None
            design.variant_label = unique_variant_label(
                parent, variant_label, exclude_id=design.id
            )

        new_file = request.files.get('file')
        if new_file and new_file.filename:
            filename = secure_filename(new_file.filename)
            if '.' not in filename:
                msg = 'Replacement file must have an extension (PNG, JPG, etc.).'
                if is_ajax:
                    return jsonify({'ok': False, 'error': msg}), 400
                flash(msg, 'error')
                return redirect(url_for('admin.designs', tab='gallery'))
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _ALLOWED_DESIGN_EXTS:
                msg = 'Unsupported format. Use PNG, JPG, WEBP, or HEIC.'
                if is_ajax:
                    return jsonify({'ok': False, 'error': msg}), 400
                flash(msg, 'error')
                return redirect(url_for('admin.designs', tab='gallery'))

            from utils.cloud_storage import upload_image
            import time
            name = os.path.splitext(filename)[0]
            unique_name = f"gallery_{name}_{int(time.time())}{ext}"
            new_path = upload_image(
                new_file,
                current_app._get_current_object(),
                subfolder='designs',
                public_id_prefix='gallery',
                process_artwork=True,
            )
            if not new_path:
                msg = 'Could not store the new image. Please try again.'
                if is_ajax:
                    return jsonify({'ok': False, 'error': msg}), 500
                flash(msg, 'error')
                return redirect(url_for('admin.designs', tab='gallery'))

            old_path = design.file_path
            design.filename = unique_name
            design.original_filename = new_file.filename
            design.file_path = new_path
            design.has_transparency = True
            try:
                from PIL import Image
                if not new_path.startswith('http'):
                    filepath = Path('static') / new_path
                    img = Image.open(filepath)
                    design.width, design.height = img.size
                    design.file_size = filepath.stat().st_size
            except Exception:
                pass
            # Remove previous local file only (leave remote URLs alone)
            if old_path and not str(old_path).startswith('http'):
                try:
                    old_full = Path('static') / old_path
                    if old_full.is_file():
                        old_full.unlink()
                except OSError:
                    pass

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('design_gallery_edit DB error %s: %s', design_id, e)
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Could not save changes. Please try again.'}), 500
        flash('Could not save changes. Please try again.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('design_gallery_edit unexpected error %s: %s', design_id, e)
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Something went wrong. Please try again.'}), 500
        flash('Something went wrong while saving. Please try again.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))

    from utils.cloud_storage import image_url as resolve_image_url
    payload = {
        'ok': True,
        'message': f'Updated "{design.title or design.original_filename}"',
        'design': {
            'id': design.id,
            'title': design.title or design.original_filename or 'Design',
            'folder': design.folder or 'custom_orders',
            'extra_categories': design.extra_categories or '',
            'places': places_attr(current_places(design)),
            'places_label': places_label(current_places(design)),
            'sku': design.sku or '',
            'variant_label': design.variant_label or '',
            'image_url': resolve_image_url(design.file_path) if design.file_path else '',
        },
    }
    if is_ajax:
        return jsonify(payload)
    flash(payload['message'], 'success')
    return redirect(url_for('admin.designs', tab='gallery'))


@admin_bp.route('/design-gallery/<int:design_id>/make-main', methods=['POST'])
@admin_required
def design_gallery_make_main(design_id):
    """Use this color as the gallery-card cover for its family."""
    from utils.design_variants import promote_gallery_main

    design = Design.query.get_or_404(design_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    name = design.variant_label or design.title or design.original_filename or 'This color'

    def _err(msg, status=400):
        if is_ajax:
            return jsonify({'ok': False, 'error': msg}), status
        flash(msg, 'error')
        return redirect(url_for('admin.designs', tab='gallery'))

    if not design.is_gallery:
        return _err('That color is not in the gallery.')

    try:
        new_main = promote_gallery_main(design)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to set gallery cover for design %s: %s', design_id, e)
        return _err('Could not change the cover color. Please try again.', 500)

    label = (new_main.variant_label if new_main else '') or name
    message = f'"{label}" is now the cover color customers see first.'
    if is_ajax:
        return jsonify({'ok': True, 'message': message, 'main_id': new_main.id if new_main else design.id})
    flash(message, 'success')
    return redirect(url_for('admin.designs', tab='gallery'))


def _unpublish_design_and_variants(design):
    """Unpublish a gallery design and any color variants attached to it."""
    from utils.design_variants import unpublish_color_variants
    design.is_gallery = False
    design.gallery_status = None
    unpublish_color_variants(design)


def _hard_delete_design_and_variants(design):
    """Delete color children first (FK), then the main design."""
    from utils.design_variants import unpublish_color_variants
    children = list(design.color_variants.all())
    for child in children:
        try:
            in_orders = child.order_items.count() > 0
        except Exception:
            in_orders = False
        if child.uploaded_by_user_id or in_orders:
            child.is_gallery = False
            child.gallery_status = None
            child.hidden_from_admin = True
            child.parent_design_id = None
        else:
            _delete_design_file(child)
            db.session.delete(child)
    # Detach any remaining soft-kept children before deleting parent
    unpublish_color_variants(design)
    for child in design.color_variants.all():
        child.parent_design_id = None
    _delete_design_file(design)
    db.session.delete(design)


@admin_bp.route('/design-gallery/<int:design_id>/remove', methods=['POST'])
@admin_required
def design_gallery_remove(design_id):
    """Remove design from gallery (does not delete file)"""
    design = Design.query.get_or_404(design_id)
    name = design.title or design.original_filename or 'Design'
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        if design.is_gallery or design.color_variants.filter_by(is_gallery=True).count():
            _unpublish_design_and_variants(design)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to remove design %s from gallery: %s', design_id, e)
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Could not remove the design. Please try again.'}), 500
        flash('Could not remove the design. Please try again.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))
    if is_ajax:
        return jsonify({'ok': True, 'message': f'"{name}" removed from gallery'})
    flash('Design removed from gallery', 'success')
    return redirect(url_for('admin.designs', tab='gallery'))


@admin_bp.route('/design-gallery/<int:design_id>/delete', methods=['POST'])
@admin_required
def design_gallery_delete(design_id):
    """Permanently delete a gallery design (admin only).

    If a customer still owns the design, unpublish it instead of destroying
    their My Designs copy. Color variants follow the main design.
    """
    design = Design.query.get_or_404(design_id)
    name = design.title or design.original_filename or 'Design'
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        if design.uploaded_by_user_id:
            _unpublish_design_and_variants(design)
            design.hidden_from_admin = True
            for child in design.color_variants.all():
                child.hidden_from_admin = True
            db.session.commit()
            msg = f'"{name}" unpublished and removed from admin lists. Customer copy kept.'
            if is_ajax:
                return jsonify({'ok': True, 'message': msg})
            flash('Design unpublished; customer copy kept', 'success')
            return redirect(url_for('admin.designs', tab='gallery'))

        try:
            in_orders = design.order_items.count() > 0
        except Exception:
            in_orders = False
        if in_orders:
            _unpublish_design_and_variants(design)
            design.hidden_from_admin = True
            for child in design.color_variants.all():
                child.hidden_from_admin = True
            db.session.commit()
            msg = f'"{name}" unpublished (used in orders; file kept).'
            if is_ajax:
                return jsonify({'ok': True, 'message': msg})
            flash('Design unpublished (used in orders)', 'success')
            return redirect(url_for('admin.designs', tab='gallery'))

        _hard_delete_design_and_variants(design)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to delete design %s: %s', design_id, e)
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Could not delete the design. Please try again.'}), 500
        flash('Could not delete the design. Please try again.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))
    if is_ajax:
        return jsonify({'ok': True, 'message': f'"{name}" permanently deleted'})
    flash('Design deleted permanently', 'success')
    return redirect(url_for('admin.designs', tab='gallery'))


# ===== MEDIA LIBRARY IMAGE IMPORT =====

# ===== PAID CHECKOUTS THAT DID NOT BECOME ORDERS =====

def _capture_view(cap):
    from utils.payment_safety import cart_lines_text
    try:
        customer = json.loads(cap.customer_json or '{}') or {}
    except ValueError:
        customer = {}
    try:
        cart = json.loads(cap.cart_json or '[]') or []
    except ValueError:
        cart = []
    name = ' '.join(p for p in (customer.get('first_name'), customer.get('last_name')) if p) or cap.payer_name or 'Unknown'
    return {
        'cap': cap,
        'name': name,
        'email': customer.get('email') or cap.payer_email or '',
        'phone': customer.get('phone') or '',
        'shipping_method': customer.get('shipping_method') or 'pickup',
        'shipping_info': customer.get('shipping_info') or {},
        'cart': cart,
        'lines': [l[2:] for l in cart_lines_text(cart).splitlines() if l.startswith('- ')],
        'clues': _safe_clues(cap) if not cart else {},
    }


def _safe_clues(cap):
    from utils.payment_safety import activity_near
    try:
        return activity_near(cap.created_at)
    except Exception:
        current_app.logger.exception('could not gather clues for capture %s', cap.id)
        return {}


@admin_bp.route('/orders/unsaved-payments')
@admin_required
def unsaved_payments():
    from models import PaymentCapture
    pending = (
        PaymentCapture.query
        .filter(PaymentCapture.order_id.is_(None))
        .filter(PaymentCapture.resolved_at.is_(None))
        .filter(db.or_(PaymentCapture.amount.isnot(None), PaymentCapture.awaiting_collection.is_(True)))
        .order_by(PaymentCapture.created_at.desc())
        .all()
    )
    return render_template('admin/unsaved_payments.html', rows=[_capture_view(c) for c in pending])


@admin_bp.route('/orders/unsaved-payments/lookup', methods=['POST'])
@admin_required
def unsaved_payment_lookup():
    """Find a PayPal payment by transaction or order ID and stage it for recovery."""
    from utils.payment_safety import (
        resolve_paypal_order_id, fetch_paypal_order, completed_capture_total,
        payer_from_order_json, record_paypal_capture,
    )
    ref = (request.form.get('paypal_ref') or '').strip()
    paypal_order_id = resolve_paypal_order_id(ref)
    if not paypal_order_id:
        flash('PayPal could not find that transaction. Copy the Transaction ID from the PayPal email or app and try again.', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    existing = Order.query.filter_by(paypal_order_id=paypal_order_id).first()
    if existing:
        flash(f'That payment already has an order: {existing.order_number}.', 'info')
        return redirect(url_for('admin.order_detail', order_id=existing.id))
    order_json = fetch_paypal_order(paypal_order_id)
    amount = completed_capture_total(order_json)
    if amount is None:
        flash('PayPal shows no completed payment for that transaction.', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    payer_name, payer_email = payer_from_order_json(order_json)
    first, _, last = (payer_name or '').partition(' ')
    customer = {'first_name': first, 'last_name': last, 'email': payer_email, 'shipping_method': 'pickup'}
    shipping = (((order_json or {}).get('purchase_units') or [{}])[0].get('shipping') or {})
    addr = shipping.get('address') or {}
    if addr.get('address_line_1'):
        customer['paypal_shipping_info'] = {
            'recipient': (shipping.get('name') or {}).get('full_name') or payer_name,
            'street': addr.get('address_line_1'),
            'street_2': addr.get('address_line_2') or '',
            'city': addr.get('admin_area_2'),
            'state': addr.get('admin_area_1'),
            'zip': addr.get('postal_code'),
        }
    # A customer with an account keeps their cart on file; use it if it's there.
    cart = []
    user = None
    if payer_email:
        user = User.query.filter(db.func.lower(User.email) == payer_email.lower()).first()
        if user and getattr(user, 'cart_json', None):
            try:
                cart = json.loads(user.cart_json) or []
            except ValueError:
                cart = []
    cap = record_paypal_capture(
        paypal_order_id, amount, order_json=order_json, cart=cart or None,
        customer=customer, user_id=user.id if user else None,
    )
    if cap is not None and not cap.failure_reason:
        cap.failure_reason = 'Found by PayPal lookup after the order did not save.'
        db.session.commit()
    if cart:
        flash(f'Found it: ${amount:.2f} from {payer_name}. Their saved cart was loaded below. Check it, then create the order.', 'success')
    else:
        flash(f'Found it: ${amount:.2f} from {payer_name}. No saved cart was on file, so add what they ordered below, then create the order.', 'info')
    return redirect(url_for('admin.unsaved_payments'))


def _save_capture_cart(cap, cart):
    cap.cart_json = json.dumps(cart)
    db.session.commit()


@admin_bp.route('/orders/unsaved-payments/<int:cap_id>/add-item', methods=['POST'])
@admin_required
def unsaved_payment_add_item(cap_id):
    from models import PaymentCapture
    cap = PaymentCapture.query.get_or_404(cap_id)
    style = (request.form.get('style_number') or '').strip()
    product = Product.query.filter(db.func.lower(Product.style_number) == style.lower()).first() if style else None
    if not product:
        flash(f'No product with style number "{style}".', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    design = None
    design_ref = (request.form.get('design') or '').strip()
    if design_ref:
        design = Design.query.filter(db.func.lower(Design.sku) == design_ref.lower()).first()
        if not design and design_ref.isdigit():
            design = Design.query.get(int(design_ref))
        if not design:
            flash(f'No design with SKU or ID "{design_ref}".', 'error')
            return redirect(url_for('admin.unsaved_payments'))
    try:
        qty = max(1, int(request.form.get('quantity') or 1))
        price = float(request.form.get('unit_price') or product.base_price or 0)
    except ValueError:
        flash('Quantity and price must be numbers.', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    try:
        width = float(request.form.get('print_width') or 0) or None
        height = float(request.form.get('print_height') or 0) or None
    except ValueError:
        width = height = None
    try:
        cart = json.loads(cap.cart_json or '[]') or []
    except ValueError:
        cart = []
    cart.append({
        'product_id': product.id,
        'size': (request.form.get('size') or 'M').strip(),
        'color': (request.form.get('color') or '').strip() or 'Unknown',
        'quantity': qty,
        'unit_price': round(price, 2),
        'design_id': design.id if design else None,
        'design_url': getattr(design, 'file_url', None) if design else None,
        'placement': (request.form.get('placement') or 'front').strip(),
        'print_width': width,
        'print_height': height,
        'collection_id': cap.collection_id,
    })
    _save_capture_cart(cap, cart)
    flash('Item added.', 'success')
    return redirect(url_for('admin.unsaved_payments'))


@admin_bp.route('/orders/unsaved-payments/<int:cap_id>/remove-item/<int:index>', methods=['POST'])
@admin_required
def unsaved_payment_remove_item(cap_id, index):
    from models import PaymentCapture
    cap = PaymentCapture.query.get_or_404(cap_id)
    try:
        cart = json.loads(cap.cart_json or '[]') or []
    except ValueError:
        cart = []
    if 0 <= index < len(cart):
        cart.pop(index)
        _save_capture_cart(cap, cart)
    return redirect(url_for('admin.unsaved_payments'))


@admin_bp.route('/orders/unsaved-payments/<int:cap_id>/resolve', methods=['POST'])
@admin_required
def unsaved_payment_resolve(cap_id):
    from models import PaymentCapture
    cap = PaymentCapture.query.get_or_404(cap_id)
    cap.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('Marked as handled.', 'success')
    return redirect(url_for('admin.unsaved_payments'))


@admin_bp.route('/orders/unsaved-payments/<int:cap_id>/create', methods=['POST'])
@admin_required
def unsaved_payment_create_order(cap_id):
    """Turn a paid checkout into a real order, exactly like checkout would."""
    from models import PaymentCapture
    from routes.checkout import create_order_from_capture
    cap = PaymentCapture.query.get_or_404(cap_id)
    if cap.order_id:
        return redirect(url_for('admin.order_detail', order_id=cap.order_id))
    if cap.amount is None:
        flash('This payment has not been collected yet.', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    try:
        has_cart = bool(json.loads(cap.cart_json or '[]'))
    except ValueError:
        has_cart = False
    if not has_cart:
        flash('Add what they ordered first.', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    order, failure = create_order_from_capture(cap, overrides={
        'first_name': (request.form.get('first_name') or '').strip(),
        'last_name': (request.form.get('last_name') or '').strip(),
        'email': (request.form.get('email') or '').strip(),
        'fulfillment': request.form.get('fulfillment') or '',
    }, send_email=request.form.get('send_email') == 'on')
    if order is None:
        flash(failure or 'The order could not be created.', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    if cap.amount is not None and abs(float(cap.amount) - float(order.total or 0)) >= 0.01:
        flash(f'Order {order.order_number} created. Note: the customer paid ${cap.amount:.2f} but these items total ${order.total:.2f}.', 'info')
    else:
        flash(f'Order {order.order_number} created.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/orders/unsaved-payments/<int:cap_id>/copy-from-order', methods=['POST'])
@admin_required
def unsaved_payment_copy_items(cap_id):
    """Copy another order's items exactly (designs, back print, print sizes).

    Group-store orders are identical except size, so copying a sibling order
    that has the right size rebuilds a lost cart precisely.
    """
    from models import PaymentCapture
    cap = PaymentCapture.query.get_or_404(cap_id)
    number = (request.form.get('order_number') or '').strip()
    source = Order.query.filter(db.func.upper(Order.order_number) == number.upper()).first() if number else None
    if not source:
        flash(f'No order numbered "{number}".', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    try:
        cart = json.loads(cap.cart_json or '[]') or []
    except ValueError:
        cart = []
    items = source.items.all() if hasattr(source.items, 'all') else list(source.items or [])
    for item in items:
        def _load(raw):
            if not raw:
                return None
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return None
        meta = _load(item.back_design_meta)
        back_url = (meta or {}).get('file_url') if isinstance(meta, dict) else None
        cart.append({
            'product_id': item.product_id,
            'size': item.size,
            'color': item.color,
            'quantity': item.quantity or 1,
            'unit_price': item.unit_price,
            'design_id': item.design_id,
            'design_url': None if item.design_id else item.design_file_name,
            'placement': item.placement,
            'print_type': item.print_type,
            'back_design_url': back_url or item.back_design_file_name,
            'back_design_meta': meta,
            'transfer_production': _load(item.transfer_production),
            'print_width': item.print_width,
            'print_height': item.print_height,
            'position_x': item.position_x,
            'position_y': item.position_y,
            'rotation': item.rotation or 0,
            'proof_image': item.proof_image,
            'proof_back_url': item.proof_back_image,
            'catalog_section': item.catalog_section,
            'uniform_kit': item.uniform_kit,
            'collection_id': source.collection_id,
        })
    if source.collection_id and not cap.collection_id:
        cap.collection_id = source.collection_id
    _save_capture_cart(cap, cart)
    flash(f'Copied {len(items)} item(s) from {source.order_number}.', 'success')
    return redirect(url_for('admin.unsaved_payments'))


@admin_bp.route('/orders/unsaved-payments/<int:cap_id>/collect', methods=['POST'])
@admin_required
def unsaved_payment_collect(cap_id):
    """Collect a PayPal payment the customer approved but whose phone never finished."""
    from models import PaymentCapture
    from routes.checkout import create_order_from_capture
    from utils.payment_safety import collect_approved_paypal
    cap = PaymentCapture.query.get_or_404(cap_id)
    if cap.provider != 'paypal' or cap.amount is not None or not cap.awaiting_collection:
        flash('That payment is not waiting to be collected.', 'info')
        return redirect(url_for('admin.unsaved_payments'))
    amount = collect_approved_paypal(cap)
    if amount is None:
        flash('PayPal would not collect it. The approval may have expired (about 3 hours); '
              'the customer would need to pay again.', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    order, failure = create_order_from_capture(cap)
    if order is None:
        flash(f'Collected ${amount:.2f}, but the order needs your help: {failure}', 'error')
        return redirect(url_for('admin.unsaved_payments'))
    flash(f'Collected ${amount:.2f} and created order {order.order_number}.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/orders/<int:order_id>/mark-paid', methods=['POST'])
@admin_required
def mark_order_paid(order_id):
    """Release an Underpaid order once the balance is settled."""
    from routes.checkout import send_order_confirmation_email
    from utils.payment_fees import true_profit
    order = Order.query.get_or_404(order_id)
    if order.payment_status != 'underpaid':
        flash('That order is not marked Underpaid.', 'info')
        return redirect(url_for('admin.order_detail', order_id=order_id))
    order.payment_status = 'paid'
    if order.status == 'new':
        order.status = 'paid'
    p = true_profit(order)
    if p is not None:
        order.profit = p
    db.session.commit()
    if request.form.get('send_receipt') == 'on' and not order.confirmation_email_sent_at:
        send_order_confirmation_email(order)
    flash(f'Order {order.order_number} marked paid.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


# The Reports, Ledger and Expenses pages live in their own file but share this blueprint and its locks.
from routes import admin_books  # noqa: E402,F401
from routes import admin_donations  # noqa: E402,F401
from routes import admin_bulk_orders  # noqa: E402,F401
from routes import admin_operations  # noqa: E402,F401   (vendors, production board, financial, equipment, growth)
from routes import admin_design_requests  # noqa: E402,F401   (gallery approval queue, notifications, Have Us Draw It requests)
from routes import admin_inventory_settings  # noqa: E402,F401   (inventory, site settings, packaging SOP, customers and marketing)
from routes import admin_production  # noqa: E402,F401   (production sheets, receipts and packing slips, invoices, labels)
from routes import admin_designs  # noqa: E402,F401   (design library, review, organize, matches, tags, categories)
from routes import admin_collections  # noqa: E402,F401   (group stores: products, designs, sections, settings)
from routes.admin_designs import _admin_designs_url  # noqa: E402,F401  (used by the old gallery address)
from routes.admin_design_requests import _delete_design_file, _send_design_request_decision_email  # noqa: E402,F401  (also used by other admin sections and routes/org.py)
from routes import admin_tools  # noqa: E402,F401   (search box, emails that did not send)
from routes import admin_backroom  # noqa: E402,F401
from routes import admin_artwork_pack  # noqa: E402,F401
# School district setup, QR codes and reports.
from routes import admin_districts  # noqa: E402,F401
