from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from sqlalchemy import or_
from flask_login import login_required, current_user
from functools import wraps
from models import (db, Product, Collection, Order, OrderItem, Design, User, ProductColorVariant,
                    Vendor, ApparelInventory, TransferInventory, Supply, GrowthMetric, FinancialEntry,
                    CustomDesignRequest, SiteError)
from werkzeug.utils import secure_filename
from datetime import datetime
import json
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
    title = name.replace('_', ' ').title()
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
        title=title or name.replace('_', ' ').title(),
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
    pending_orders  = Order.query.filter(Order.status.in_(['new', 'paid'])).count()
    in_production   = Order.query.filter_by(status='in_production').count()
    ready_for_pickup = Order.query.filter_by(status='ready').count()
    total_revenue   = db.session.query(db.func.sum(Order.total)).filter(
        Order.payment_status == 'paid'
    ).scalar() or 0
    pending_design_requests = CustomDesignRequest.query.filter_by(status='pending').count()
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

    return render_template('admin/dashboard.html',
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         in_production=in_production,
                         ready_for_pickup=ready_for_pickup,
                         total_revenue=total_revenue,
                         recent_orders=recent_orders,
                         pending_design_requests=pending_design_requests,
                         recent_site_errors=recent_site_errors,
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


# ===== ORDERS =====

@admin_bp.route('/orders')
@admin_required
def orders():
    """Manage orders - Master Order Log"""
    from utils.production_stages import DONE_STATUSES, normalize_stage_arg, orders_for_stage
    status = request.args.get('stage') or request.args.get('status')
    collection_id = request.args.get('collection')
    order_type = request.args.get('order_type')
    page = request.args.get('page', 1, type=int)

    if status is None or status == '':
        redirect_args = {'stage': 'order_received'}
        if collection_id:
            redirect_args['collection'] = collection_id
        if order_type:
            redirect_args['order_type'] = order_type
        return redirect(url_for('admin.orders', **redirect_args))

    stage = normalize_stage_arg(status)
    if stage == 'all':
        query = Order.query.filter(~Order.status.in_(DONE_STATUSES))
    else:
        query = orders_for_stage(stage)
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    if order_type:
        if order_type == 'retail':
            query = query.filter(or_(Order.order_type == 'retail', Order.order_type == None))
        else:
            query = query.filter_by(order_type=order_type)
    
    orders = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    collections = Collection.query.all()
    
    return render_template('admin/orders.html', 
                         orders=orders,
                         collections=collections,
                         selected_status=stage,
                         selected_collection=collection_id,
                         selected_order_type=order_type)


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
        dt = order.updated_at or order.created_at
        key = (dt.year, dt.month)
        if key not in by_month:
            by_month[key] = []
        by_month[key].append(order)
    return render_template('admin/orders_completed.html', by_month=by_month)


@admin_bp.route('/orders/<int:order_id>')
@admin_required
def order_detail(order_id):
    """View order details"""
    from utils.print_sizes import get_print_width_for_size, production_from_order_item
    from utils.order_costs import apply_order_defaults
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
    return render_template(
        'admin/order_detail.html',
        order=order,
        get_print_width=get_print_width,
        get_display_print_width=get_display_print_width,
        item_productions=item_productions,
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
    from utils.order_artwork import piece_print_url
    from utils.personalization_layout import PREVIEW_DPI
    if side not in ('back', 'back-name', 'back-number'):
        return ('', 404)
    order = Order.query.get_or_404(order_id)
    item = OrderItem.query.filter_by(id=item_id, order_id=order.id).first_or_404()
    piece = _artwork_piece(side)
    stored = piece_print_url(item, piece)
    if stored:
        return redirect(stored)
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


@admin_bp.route('/orders/<int:order_id>/items/<int:item_id>/save/<side>')
@admin_required
def save_item_artwork(order_id, item_id, side):
    """Download the transparent print file for a DTF upload."""
    from urllib.request import Request, urlopen
    from utils.order_artwork import (
        back_print_url,
        download_filename,
        front_print_url,
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
            filename = download_filename(order, item, side)
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
    filename = download_filename(order, item, side)
    local = local_file_for_url(current_app, url)
    inline = request.args.get('inline')
    if local:
        return send_file(local, as_attachment=not inline, download_name=filename)
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


@admin_bp.route('/orders/repair-personalization', methods=['POST'])
@admin_required
def repair_personalization():
    """Rewrite stored name/number PNGs from each order's saved snapshot."""
    from flask import current_app
    from utils.personalization_layout import repair_existing_personalized_items
    result = repair_existing_personalized_items(current_app)
    flash(
        f'Personalization repair finished. Scanned {result["scanned"]}, '
        f'stamped {result["repaired"]} saved layouts, '
        f'skipped {result["skipped"]} already stamped, '
        f'flagged {result["flagged"]} for review. '
        'No production PNGs were generated. Use Save PNG on each item for a 300 DPI file. '
        'Prices and customer mockups were not changed.',
        'success',
    )
    return redirect(url_for('admin.orders'))


def _collect_press_shirts(orders):
    """One card per physical shirt: front and back stay together."""
    from utils.print_sizes import production_from_order_item
    from utils.order_artwork import front_print_url, mockup_urls
    shirts = []
    for order in orders:
        for item in order.items:
            prod = production_from_order_item(item, customer_name=order.full_name)
            if not prod or (not prod.get('front') and not prod.get('back')):
                continue
            front_m, back_m = mockup_urls(getattr(item, 'product', None), getattr(item, 'color', None))
            front = prod.get('front') or None
            back = prod.get('back') or None
            shirts.append({
                'order_number': getattr(order, 'order_number', None),
                'quantity': getattr(item, 'quantity', 1) or 1,
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
                'front_placement': getattr(item, 'placement', None) or (front or {}).get('placement') or 'center_chest',
                'exceeds_safe_area': bool(
                    (front or {}).get('exceeds_safe_area') or (back or {}).get('exceeds_safe_area')
                ),
            })
    return shirts


def _sort_press_shirts(shirts, group_by='size'):
    def key(shirt):
        back = shirt.get('back') or {}
        front = shirt.get('front') or {}
        name = back.get('name') or front.get('design_name') or ''
        if group_by == 'garment':
            return (shirt.get('garment_style') or '', shirt.get('size') or '', name)
        if group_by == 'name':
            return (name, shirt.get('size') or '')
        if group_by == 'order':
            return (shirt.get('order_number') or '', name)
        return (shirt.get('age_group') or '', shirt.get('size') or '', name)
    return sorted(shirts, key=key)


def _collect_order_productions(orders):
    from utils.print_sizes import production_from_order_item, flatten_production_rows
    from utils.order_artwork import front_print_url, mockup_urls, resolve_print_url
    productions = []
    for order in orders:
        for item in order.items:
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
    group_by = request.args.get('group', 'size')
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

    from utils.production_stages import apply_stage
    apply_stage(order, stage)

    if admin_notes:
        order.admin_notes = admin_notes

    db.session.commit()
    stage_labels = {
        'order_received': 'Order Received', 'waiting_supplies': 'Waiting on Supplies',
        'ready_to_press': 'Ready to Press', 'pressed': 'Pressed', 'packaged_ready': 'Packaged & Ready'
    }
    flash(f'Order moved to: {stage_labels.get(stage, stage)}', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/delete', methods=['POST'])
@admin_required
def delete_order(order_id):
    """Permanently delete an order and all its items."""
    order = Order.query.get_or_404(order_id)
    try:
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
    order.cost_of_goods = _form_money('cost_of_goods', 0.0) or None
    if order.cost_of_goods is not None and order.total:
        order.profit = order.total - order.cost_of_goods
    else:
        order.profit = _form_money('profit', 0.0) or None
    order.is_refunded = request.form.get('is_refunded') == 'on'
    order.refund_notes = request.form.get('refund_notes')
    db.session.commit()
    flash('Order details updated', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/update-item/<int:item_id>', methods=['POST'])
@admin_required
def update_order_item(order_id, item_id):
    """Update order item: print_type, design_file_name"""
    item = OrderItem.query.filter_by(id=item_id, order_id=order_id).first_or_404()
    item.print_type = request.form.get('print_type') or item.print_type
    item.design_file_name = request.form.get('design_file_name') or item.design_file_name
    if item.design:
        item.design_file_name = item.design_file_name or item.design.filename
    db.session.commit()
    flash('Item updated', 'success')
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
        from utils.mockups import lightest_front_mockup_url, sorted_front_mockup_urls, get_first_shop_image_url

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
            local_url = get_first_shop_image_url(p, current_app)
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


@admin_bp.route('/products/link-mockups', methods=['POST'])
@admin_required
def link_mockup_images():
    """Create missing products from mockup folders and link all color images. No S&S API needed."""
    from utils.mockups import create_products_from_mockup_folders, ensure_variant_mockup_urls
    try:
        created = create_products_from_mockup_folders(current_app)
        db.session.commit()
        ensure_variant_mockup_urls(current_app)
        db.session.commit()
        msg = f'Linked mockup images for all products.'
        if created:
            msg = f'Created {created} products from mockup folders. ' + msg
        flash(msg, 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/sync-api', methods=['POST'])
@admin_required
def sync_api():
    """Sync products from S&S Activewear API with color variants and inventory"""
    import sys
    
    print("="*80, file=sys.stderr, flush=True)
    print("ADMIN: STARTING S&S API SYNC WITH COLOR VARIANTS & INVENTORY", file=sys.stderr, flush=True)
    print("="*80, file=sys.stderr, flush=True)
    
    try:
        from services.ssactivewear_api import SSActivewearAPI
        from models import ProductColorVariant
        import os
        
        # Debug: Check environment
        api_key = os.getenv('SSACTIVEWEAR_API_KEY')
        account = os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER')
        print(f"ENV CHECK - API Key exists: {bool(api_key)}", file=sys.stderr, flush=True)
        print(f"ENV CHECK - Account: {account}", file=sys.stderr, flush=True)
        
        api = SSActivewearAPI()
        print("API CLIENT INITIALIZED", file=sys.stderr, flush=True)
        
        
        # Use mockup-styles sync: only syncs styles that have mockup folders in uploads/mockups
        # Works even when full catalog returns nothing (fetches each style directly)
        print("CALLING sync_mockup_styles...", file=sys.stderr, flush=True)
        try:
            products_data = api.sync_mockup_styles()
        except ValueError as e:
            flash(f'S&S API: {str(e)}. Creating products from mockup folders only.', 'warning')
            products_data = []
        print(f"PRODUCTS DATA RETURNED: {len(products_data) if products_data else 0}", file=sys.stderr, flush=True)

        if not products_data:
            print("No products from S&S - will create from mockup folders only", file=sys.stderr, flush=True)
        
        added = 0
        updated = 0
        color_variants_added = 0
        
        print(f"PROCESSING {len(products_data)} PRODUCTS FROM S&S...", file=sys.stderr, flush=True)
        for product_data in (products_data or []):
            # Extract color variants before saving product
            color_variants_data = product_data.pop('color_variants', [])
            
            style_num = product_data.get('style_number')
            existing = Product.query.filter_by(style_number=style_num).first()
            
            if existing:
                # Update existing
                existing.name = product_data['name']
                existing.category = product_data['category']
                existing.age_group = product_data.get('age_group')
                existing.fit_type = product_data.get('fit_type')
                existing.neck_style = product_data.get('neck_style')
                existing.sleeve_length = product_data.get('sleeve_length')
                existing.description = product_data['description']
                existing.base_price = product_data['base_price']
                existing.wholesale_cost = product_data.get('wholesale_cost', 0)
                existing.available_sizes = product_data['available_sizes']
                existing.available_colors = product_data['available_colors']
                existing.brand = product_data.get('brand', 'Bella+Canvas')
                existing.api_data = product_data.get('api_data')
                existing.size_chart = product_data.get('size_chart')
                existing.fit_guide = product_data.get('fit_guide')
                existing.fabric_details = product_data.get('fabric_details')
                # Update images if provided
                if product_data.get('front_mockup_template'):
                    existing.front_mockup_template = product_data['front_mockup_template']
                if product_data.get('back_mockup_template'):
                    existing.back_mockup_template = product_data['back_mockup_template']
                product = existing
                updated += 1
                print(f"  UPDATED: {style_num}", file=sys.stderr, flush=True)
            else:
                # Add new
                product = Product(**product_data)
                db.session.add(product)
                added += 1
                print(f"  ADDED: {style_num}", file=sys.stderr, flush=True)
            
            # Flush to get product ID
            db.session.flush()
            
            # Save color variants with mockup images and inventory
            for variant_data in color_variants_data:
                existing_variant = ProductColorVariant.query.filter_by(
                    product_id=product.id,
                    color_name=variant_data['color_name']
                ).first()
                
                if existing_variant:
                    # Update existing variant
                    existing_variant.front_image_url = variant_data.get('front_image')
                    existing_variant.back_image_url = variant_data.get('back_image')
                    existing_variant.side_image_url = variant_data.get('side_image')
                    incoming_inv = variant_data.get('size_inventory')
                    from utils.stock import is_usable_inventory_payload
                    if is_usable_inventory_payload(incoming_inv):
                        existing_variant.size_inventory = incoming_inv
                    existing_variant.ss_color_id = variant_data.get('color_id')
                    existing_variant.last_synced = datetime.utcnow()
                else:
                    # Create new variant
                    new_variant = ProductColorVariant(
                        product_id=product.id,
                        color_name=variant_data['color_name'],
                        front_image_url=variant_data.get('front_image'),
                        back_image_url=variant_data.get('back_image'),
                        side_image_url=variant_data.get('side_image'),
                        size_inventory=variant_data.get('size_inventory'),
                        ss_color_id=variant_data.get('color_id')
                    )
                    db.session.add(new_variant)
                    color_variants_added += 1
            
            print(f"    {len(color_variants_data)} color variants synced", file=sys.stderr, flush=True)
        
        db.session.commit()

        # Create products from mockup folders when S&S doesn't have them
        from utils.mockups import create_products_from_mockup_folders
        created_from_mockups = create_products_from_mockup_folders(current_app)
        if created_from_mockups:
            db.session.commit()
            print(f"  CREATED {created_from_mockups} PRODUCTS FROM MOCKUP FOLDERS", file=sys.stderr, flush=True)

        from utils.mockups import ensure_variant_mockup_urls
        ensure_variant_mockup_urls(current_app)
        db.session.commit()

        print(f"COMMIT SUCCESSFUL! Added: {added}, Updated: {updated}, Color Variants: {color_variants_added}, From mockups: {created_from_mockups}", file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        msg = f'✅ Synced {len(products_data)} products with {color_variants_added} color variants!'
        if created_from_mockups:
            msg += f' Created {created_from_mockups} products from mockup folders.'
        flash(msg, 'success')
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        print("="*80, file=sys.stderr, flush=True)
        print("ERROR DURING SYNC:", file=sys.stderr, flush=True)
        print(error_details, file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        flash(f'Error syncing from API: {str(e)}', 'error')
    
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/unlink-ss-bella-canvas', methods=['POST'])
@admin_required
def unlink_ss_bella_canvas():
    """
    Remove all S&S Activewear linkage from Bella+Canvas products.

    Clears:
      - ProductColorVariant.ss_color_id  (S&S internal SKU reference)
      - Product.api_data                  (the S&S JSON blob)

    Does NOT touch base_price, descriptions, images, sizes, colors,
    or any other product data — only the S&S API binding.
    """
    import sys
    try:
        # Cast a wide net — any product that has S&S api_data OR whose brand/name
        # suggests Bella+Canvas. We do NOT restrict to brand=='Bella+Canvas' alone
        # because many products were added before that field was consistently set.
        bella_products = Product.query.filter(
            db.or_(
                Product.api_data.isnot(None),
                Product.brand == 'Bella+Canvas',
                Product.name.ilike('%bella%canvas%'),
            )
        ).all()

        products_cleared = 0
        variants_cleared = 0

        for product in bella_products:
            changed = False
            if product.api_data is not None:
                product.api_data = None
                changed = True
            if changed:
                products_cleared += 1

            for variant in product.color_variants:
                if variant.ss_color_id is not None:
                    variant.ss_color_id = None
                    variants_cleared += 1

        db.session.commit()
        print(
            f'ADMIN: Unlinked S&S from {products_cleared} products, '
            f'{variants_cleared} variants',
            file=sys.stderr, flush=True
        )
        if products_cleared == 0 and variants_cleared == 0:
            flash(
                'Nothing to unlink — these products have no S&S API data attached. '
                'You\'re already ready to sync from SanMar.',
                'info'
            )
        else:
            flash(
                f'S&S unlink complete — cleared {products_cleared} product(s) and '
                f'{variants_cleared} color variant(s). All prices preserved.',
                'success'
            )
    except Exception as e:
        db.session.rollback()
        flash(f'Error unlinking S&S data: {str(e)}', 'error')

    return redirect(url_for('admin.products'))


@admin_bp.route('/products/sync-sanmar', methods=['POST'])
@admin_required
def sync_sanmar():
    """Sync curated bestsellers from SanMar (Bella+Canvas plus other shop brands)."""
    import sys
    from services.sanmar_api import SanMarAPI, check_credentials, SanMarAuthError
    from models import ProductColorVariant
    from datetime import datetime

    print("=" * 80, file=sys.stderr, flush=True)
    print("ADMIN: SYNCING CURATED SANMAR BRANDS", file=sys.stderr, flush=True)
    print("=" * 80, file=sys.stderr, flush=True)

    # Check credentials before attempting sync
    cred_check = check_credentials()
    if not cred_check['ok']:
        missing = ', '.join(cred_check['missing'])
        flash(
            f'SanMar sync failed — missing credentials: {missing}. '
            f'Add these to your Railway environment variables.',
            'error'
        )
        return redirect(url_for('admin.products'))

    try:
        from services.sanmar_catalog import CURATED_BRANDS
        api = SanMarAPI()
        notes = []
        added = updated = variants_added = variants_updated = 0

        for brand in CURATED_BRANDS:
            try:
                products_data = api.bestsellers_for_brand(brand)
            except Exception as brand_err:
                notes.append(f'{brand["name"]}: {brand_err}')
                print(f'[SanMar] {brand["name"]} failed: {brand_err}', file=sys.stderr, flush=True)
                continue

            if not products_data:
                notes.append(f'{brand["name"]}: none returned')
                continue

            notes.append(f'{brand["name"]}: {len(products_data)} styles')

            for product_data in products_data:
                color_variants_data = product_data.pop('color_variants', [])
                style_num = product_data.get('style_number', '')
                if not style_num:
                    continue

                try:
                    upper = style_num.upper()
                    existing = Product.query.filter_by(style_number=style_num).first()
                    if not existing and upper.startswith('BC'):
                        existing = Product.query.filter_by(style_number=style_num[2:]).first()
                    if not existing and not upper.startswith('BC'):
                        existing = Product.query.filter_by(style_number=f'BC{style_num}').first()
                    if existing:
                        for key, value in product_data.items():
                            # Preserve existing retail price — never let SanMar's
                            # wholesale-derived price overwrite what admin has set.
                            if key == 'base_price':
                                continue
                            if key == 'is_customer_favorite':
                                continue
                            if hasattr(existing, key) and value is not None:
                                setattr(existing, key, value)
                        existing.is_active = True
                        product = existing
                        updated += 1
                    else:
                        product_data['is_active'] = True
                        product = Product(**product_data)
                        db.session.add(product)
                        added += 1

                    db.session.flush()

                    for variant_data in color_variants_data:
                        color_name = variant_data.get('color_name', '')
                        if not color_name:
                            continue
                        existing_variant = ProductColorVariant.query.filter_by(
                            product_id=product.id, color_name=color_name
                        ).first()
                        inv = variant_data.get('size_inventory')
                        if isinstance(inv, dict):
                            inv = json.dumps(inv)
                        if existing_variant:
                            existing_variant.front_image_url = variant_data.get('front_image') or existing_variant.front_image_url
                            existing_variant.back_image_url  = variant_data.get('back_image')  or existing_variant.back_image_url
                            if variant_data.get('color_hex'):
                                existing_variant.color_hex = variant_data.get('color_hex')
                            if variant_data.get('color_swatch'):
                                existing_variant.color_swatch_url = variant_data.get('color_swatch')
                            from utils.stock import is_usable_inventory_payload
                            if is_usable_inventory_payload(inv):
                                existing_variant.size_inventory = inv
                            existing_variant.last_synced     = datetime.utcnow()
                            variants_updated += 1
                        else:
                            db.session.add(ProductColorVariant(
                                product_id=product.id,
                                color_name=color_name,
                                front_image_url=variant_data.get('front_image'),
                                back_image_url=variant_data.get('back_image'),
                                color_hex=variant_data.get('color_hex') or None,
                                color_swatch_url=variant_data.get('color_swatch') or None,
                                size_inventory=inv,
                                last_synced=datetime.utcnow()
                            ))
                            variants_added += 1

                    db.session.commit()

                except Exception as e:
                    db.session.rollback()
                    print(f'  Error on {style_num}: {e}', file=sys.stderr, flush=True)
                    continue

        if added == 0 and updated == 0:
            flash(
                'SanMar sync finished but no bestsellers were saved. '
                + (' '.join(notes) if notes else 'Check that Web Services is enabled for these brands.'),
                'warning'
            )
            return redirect(url_for('admin.products'))

        summary = '; '.join(notes) if notes else ''
        flash(
            f'SanMar bestseller sync complete! {added} products added, {updated} updated, '
            f'{variants_added} color variants added, {variants_updated} updated. {summary}',
            'success'
        )

    except SanMarAuthError as e:
        db.session.rollback()
        flash(
            f'SanMar authentication failed: {e}. '
            f'Double-check SANMAR_USERNAME and SANMAR_PASSWORD in Railway.',
            'error'
        )
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc(file=sys.stderr)
        flash(f'Error during SanMar sync: {str(e)}', 'error')

    return redirect(url_for('admin.products'))


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
                product = Product.query.filter(
                    db.or_(Product.style_number == bc_style, Product.style_number == folder_name)
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


@admin_bp.route('/products/link-local-images', methods=['POST'])
@admin_required
def link_local_images():
    """
    Scan static/sanmar/{style}/ folders and wire up front/back image URLs
    on ProductColorVariant rows that currently have no image.

    Filename convention: {style}_{Color_with_underscores}_front.jpg
    DB style numbers: BC3001 → folder: 3001
    """
    import os, re
    from pathlib import Path
    from models import db, Product, ProductColorVariant

    sanmar_dir = Path(current_app.root_path) / 'static' / 'sanmar'
    if not sanmar_dir.is_dir():
        flash('static/sanmar/ directory not found.', 'danger')
        return redirect(url_for('admin.products'))

    updated = 0
    skipped = 0

    for style_folder in sanmar_dir.iterdir():
        if not style_folder.is_dir():
            continue

        folder_name = style_folder.name          # e.g. "3001"
        bc_style = 'BC' + folder_name            # e.g. "BC3001"

        product = Product.query.filter(
            db.or_(
                Product.style_number == bc_style,
                Product.style_number == folder_name,
            )
        ).first()
        if not product:
            continue

        # Build a map: normalised_color → {front, back} paths
        file_map: dict[str, dict] = {}
        for f in style_folder.iterdir():
            if not f.is_file():
                continue
            m = re.match(
                rf'^{re.escape(folder_name)}_(.+?)_(front|back)\.jpe?g$',
                f.name, re.IGNORECASE
            )
            if not m:
                continue
            raw_color = m.group(1).replace('_', ' ')   # "Baby_Blue" → "Baby Blue"
            side      = m.group(2).lower()               # "front" / "back"
            key       = raw_color.lower()
            if key not in file_map:
                file_map[key] = {}
            file_map[key][side] = f'/static/sanmar/{folder_name}/{f.name}'

        # Match against ProductColorVariant rows for this product
        variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
        for variant in variants:
            color_key = (variant.color_name or '').lower()
            if color_key not in file_map:
                skipped += 1
                continue

            paths = file_map[color_key]
            changed = False
            if not variant.front_image_url and paths.get('front'):
                variant.front_image_url = paths['front']
                changed = True
            if not variant.back_image_url and paths.get('back'):
                variant.back_image_url = paths['back']
                changed = True

            if changed:
                updated += 1

        # Also update Product.front_mockup_template if it's blank (use first front image found)
        if not product.front_mockup_template and file_map:
            first_front = next(
                (v['front'] for v in file_map.values() if 'front' in v), None
            )
            if first_front:
                product.front_mockup_template = first_front
        if not product.back_mockup_template and file_map:
            first_back = next(
                (v['back'] for v in file_map.values() if 'back' in v), None
            )
            if first_back:
                product.back_mockup_template = first_back

    try:
        db.session.commit()
        flash(f'Done! Linked images on {updated} color variants ({skipped} color names had no matching file).', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error saving image links: {e}', 'danger')

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


@admin_bp.route('/products/sync-sanmar-dip', methods=['POST'])
@admin_required
def sync_sanmar_dip():
    """
    Download and import the SanMar Daily Inventory & Pricing (DIP) file via SFTP.
    Runs in a background thread — response returns immediately.
    The DIP file contains inventory, pricing, images, and color variants for all
    curated styles.  This is the correct approach for getProductInfoByBrand because
    that SOAP call is *asynchronous* — it only queues a file on SanMar's FTP; it
    does not return product rows directly.
    """
    from services.sanmar_ftp import start_dip_sync_thread

    start_dip_sync_thread(current_app._get_current_object(), styles_only=True)
    flash(
        'SanMar FTP sync started! Downloading product data, inventory, and pricing '
        'from SanMar\'s SFTP server. This runs in the background — check Railway logs '
        'for progress. Products will update within a few minutes.',
        'success',
    )
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/test-sanmar', methods=['GET'])
@admin_required
def test_sanmar_api():
    """Quick diagnostic: test SanMar credentials and BC API access."""
    import os
    from services.sanmar_api import SanMarAPI, check_credentials, SanMarAuthError

    result = {'credentials': {}, 'bc_access': None, 'error': None}

    cred = check_credentials()
    result['credentials'] = cred

    if not cred['ok']:
        return jsonify(result)

    try:
        api = SanMarAPI()
        # Try fetching one page of catalog — if BC access approved we get product data
        products = api.fetch_full_catalog()
        if products:
            sample = products[0]
            result['bc_access'] = True
            result['sample'] = {
                'name': sample.get('name'),
                'style': sample.get('style_number'),
                'colors': len(sample.get('color_variants', [])),
                'front_image': (sample.get('color_variants') or [{}])[0].get('front_image'),
            }
            result['total_products'] = len(products)
        else:
            result['bc_access'] = False
            result['error'] = 'API returned no products — BC access not yet approved by SanMar'
    except SanMarAuthError as e:
        result['bc_access'] = False
        result['error'] = f'Auth failed: {e}'
    except Exception as e:
        result['bc_access'] = False
        result['error'] = str(e)

    return jsonify(result)


@admin_bp.route('/products/fix-categories', methods=['POST'])
@admin_required
def fix_product_categories():
    """
    Fix category strings that have a stray semicolon from old S&S Activewear sync.
    e.g. 'T-SHIRTS ;WOMEN\'S' → 'T-Shirts'
         'HOODIES ;MEN\'S'    → 'Hoodies'
    """
    from models import Product

    # Map raw S&S category prefixes to clean names
    _cat_map = {
        'T-SHIRT': 'T-Shirts',
        'HOODIE': 'Hoodies',
        'SWEATSHIRT': 'Sweatshirts',
        'TANK': 'Tank Tops',
        'POLO': 'Polos',
        'JACKET': 'Jackets',
        'CREW': 'Crewnecks',
        'PULLOVER': 'Pullovers',
        'ZIP': 'Zip-Ups',
        'PANT': 'Pants',
        'SHORT': 'Shorts',
        'DRESS': 'Dresses',
        'SKIRT': 'Skirts',
        'ONESIE': 'Infant/Toddler',
        'INFANT': 'Infant/Toddler',
        'TODDLER': 'Infant/Toddler',
        'YOUTH': 'Youth',
    }

    fixed = 0
    for product in Product.query.all():
        raw = (product.category or '').strip()
        if not raw:
            continue
        # Split on semicolon and take the first part
        clean = raw.split(';')[0].strip().title()
        # Map to a canonical name if we can
        upper = clean.upper()
        for prefix, canonical in _cat_map.items():
            if upper.startswith(prefix):
                clean = canonical
                break
        if clean != raw:
            product.category = clean
            fixed += 1

    db.session.commit()
    flash(f'Category cleanup complete! Fixed {fixed} product categories.', 'success')
    return redirect(url_for('admin.products'))



@admin_bp.route('/products/cleanup-old-ss', methods=['POST'])
@admin_required
def cleanup_old_ss_products():
    """Delete old non-BC-prefixed Bella+Canvas products left over from S&S sync."""
    from models import Product, db
    # Target products without a BC prefix where we can identify them as Bella+Canvas
    old_products = Product.query.filter(
        ~Product.style_number.ilike('BC%'),
        db.or_(
            Product.brand.ilike('%bella%'),
            Product.brand.ilike('%canvas%'),
            Product.name.ilike('%bella%canvas%'),
            Product.name.ilike('%BELLA+CANVAS%'),
        )
    ).all()

    # Also catch any non-BC product whose name starts with BELLA+CANVAS® (the CSV title format)
    bella_title = Product.query.filter(
        ~Product.style_number.ilike('BC%'),
        Product.name.ilike('BELLA+CANVAS%')
    ).all()
    all_old = {p.id: p for p in old_products + bella_title}

    count = len(all_old)
    for p in all_old.values():
        db.session.delete(p)
    db.session.commit()
    if count:
        flash(f'Cleaned up {count} old S&S Bella+Canvas products (no BC prefix).', 'success')
    else:
        flash('Nothing found. Old S&S products may have already been updated, or use the admin list to delete manually.', 'info')
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


@admin_bp.route('/products/test-sanmar', methods=['POST'])
@admin_required
def test_sanmar_connection():
    """Quick connectivity test — returns JSON so the modal can show results inline."""
    from services.sanmar_api import test_connection
    result = test_connection()
    return jsonify(result)


@admin_bp.route('/products/sync-all-bella-canvas', methods=['POST'])
@admin_required
def sync_all_bella_canvas():
    """Sync the FULL Bella+Canvas catalog from S&S Activewear (all styles, not just mockup folders)
    NOTE: S&S Activewear no longer carries Bella+Canvas. Use SanMar sync instead."""
    flash('Note: S&S Activewear no longer carries Bella+Canvas. Use the SanMar sync button for Bella+Canvas products.', 'warning')
    import sys
    from services.ssactivewear_api import SSActivewearAPI
    from models import ProductColorVariant
    from datetime import datetime

    print("=" * 80, file=sys.stderr, flush=True)
    print("ADMIN: SYNCING FULL BELLA+CANVAS CATALOG", file=sys.stderr, flush=True)
    print("=" * 80, file=sys.stderr, flush=True)

    try:
        api = SSActivewearAPI()
        products_data = api.sync_bella_canvas_catalog()

        if not products_data:
            flash('No products returned from S&S API. Check your API credentials.', 'error')
            return redirect(url_for('admin.products'))

        added = updated = variants_added = variants_updated = 0

        for product_data in products_data:
            color_variants_data = product_data.pop('color_variants', [])
            style_num = product_data.get('style_number', '')
            if not style_num:
                continue

            try:
                existing = Product.query.filter_by(style_number=style_num).first()
                if existing:
                    for key, value in product_data.items():
                        if hasattr(existing, key) and value is not None:
                            setattr(existing, key, value)
                    existing.is_active = True
                    product = existing
                    updated += 1
                else:
                    product_data['is_active'] = True
                    product = Product(**product_data)
                    db.session.add(product)
                    added += 1

                db.session.flush()

                for variant_data in color_variants_data:
                    color_name = variant_data.get('color_name', '')
                    if not color_name:
                        continue
                    existing_variant = ProductColorVariant.query.filter_by(
                        product_id=product.id, color_name=color_name
                    ).first()
                    if existing_variant:
                        existing_variant.front_image_url = variant_data.get('front_image') or existing_variant.front_image_url
                        existing_variant.back_image_url  = variant_data.get('back_image')  or existing_variant.back_image_url
                        existing_variant.side_image_url  = variant_data.get('side_image')  or existing_variant.side_image_url
                        existing_variant.size_inventory  = variant_data.get('size_inventory')
                        existing_variant.ss_color_id     = variant_data.get('color_id')
                        existing_variant.last_synced     = datetime.utcnow()
                        variants_updated += 1
                    else:
                        db.session.add(ProductColorVariant(
                            product_id=product.id,
                            color_name=color_name,
                            front_image_url=variant_data.get('front_image'),
                            back_image_url=variant_data.get('back_image'),
                            side_image_url=variant_data.get('side_image'),
                            size_inventory=variant_data.get('size_inventory'),
                            ss_color_id=variant_data.get('color_id'),
                            last_synced=datetime.utcnow()
                        ))
                        variants_added += 1

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                print(f"  Error on {style_num}: {e}", file=sys.stderr, flush=True)
                continue

        flash(
            f'Full sync complete! {added} products added, {updated} updated, '
            f'{variants_added} color variants added, {variants_updated} updated. '
            f'Total in DB: {Product.query.count()}',
            'success'
        )
        print(f"FULL SYNC DONE: {added} added, {updated} updated", file=sys.stderr, flush=True)

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc(file=sys.stderr)
        flash(f'Error during full sync: {str(e)}', 'error')

    return redirect(url_for('admin.products'))


@admin_bp.route('/products/backfill-images', methods=['POST'])
@admin_required
def backfill_images():
    """
    For every color variant that is missing a front or back image URL,
    fetch fresh ghost/flat images from S&S Activewear and save them.
    Uses ghost/flat images only — no model shots.
    """
    import sys
    from services.ssactivewear_api import SSActivewearAPI
    from models import ProductColorVariant
    from datetime import datetime

    print("=" * 80, file=sys.stderr, flush=True)
    print("ADMIN: BACKFILLING MISSING COLOR VARIANT IMAGES", file=sys.stderr, flush=True)
    print("=" * 80, file=sys.stderr, flush=True)

    try:
        api = SSActivewearAPI()

        # Find all products that have at least one variant missing a front image
        products_needing_images = (
            Product.query
            .join(ProductColorVariant)
            .filter(
                (ProductColorVariant.front_image_url == None) |
                (ProductColorVariant.front_image_url == '')
            )
            .distinct()
            .all()
        )

        print(f"Found {len(products_needing_images)} products with missing variant images",
              file=sys.stderr, flush=True)

        filled = 0
        skipped = 0
        errors = []

        for product in products_needing_images:
            try:
                print(f"  Fetching images for {product.style_number}...", file=sys.stderr, flush=True)
                style_data = api.fetch_style_data_by_style_number(product.style_number)
                if not style_data:
                    skipped += 1
                    continue

                # Build a lookup: color_name -> {front_image, back_image, side_image}
                image_map = {}
                for v in style_data.get('color_variants', []):
                    cname = v.get('color_name', '')
                    if cname:
                        image_map[cname] = v

                # Update only variants that are missing images
                for variant in product.color_variants:
                    if variant.front_image_url and variant.back_image_url:
                        continue  # already has both — skip

                    img_data = image_map.get(variant.color_name, {})
                    changed = False

                    if not variant.front_image_url and img_data.get('front_image'):
                        variant.front_image_url = img_data['front_image']
                        changed = True
                    if not variant.back_image_url and img_data.get('back_image'):
                        variant.back_image_url = img_data['back_image']
                        changed = True
                    if not variant.side_image_url and img_data.get('side_image'):
                        variant.side_image_url = img_data['side_image']
                        changed = True

                    if changed:
                        variant.last_synced = datetime.utcnow()
                        filled += 1

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                print(f"  Error on {product.style_number}: {e}", file=sys.stderr, flush=True)
                errors.append(product.style_number)
                continue

        msg = f'Image backfill complete! {filled} variants updated across {len(products_needing_images)} products.'
        if skipped:
            msg += f' {skipped} products skipped (not found in S&S).'
        if errors:
            msg += f' {len(errors)} products had errors.'
        flash(msg, 'success')
        print(f"BACKFILL DONE: {filled} variants filled", file=sys.stderr, flush=True)

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc(file=sys.stderr)
        flash(f'Error during image backfill: {str(e)}', 'error')

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
            is_active=request.form.get('is_active') == 'on',
            is_customer_favorite=request.form.get('is_customer_favorite') == 'on',
            available_sizes=store_json_list(request.form.get('available_sizes')),
            available_colors=store_json_list(request.form.get('available_colors')),
            print_area_config=request.form.get('print_area_config')
        )
        
        db.session.add(product)
        db.session.commit()
        
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
        product.description = request.form.get('description')
        product.base_price = base_price
        product.wholesale_cost = _form_money('wholesale_cost', 0.0)
        product.is_active = request.form.get('is_active') == 'on'
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
                filename = secure_filename(f"{product.style_number}_front_{front_file.filename}")
                upload_path = os.path.join('static/uploads/products', filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                front_file.save(upload_path)
                product.front_mockup_template = f"uploads/products/{filename}"
        
        # Handle back image upload
        if 'back_image' in request.files:
            back_file = request.files['back_image']
            if back_file and back_file.filename:
                filename = secure_filename(f"{product.style_number}_back_{back_file.filename}")
                upload_path = os.path.join('static/uploads/products', filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                back_file.save(upload_path)
                product.back_mockup_template = f"uploads/products/{filename}"
        
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
    product.is_active = not product.is_active
    db.session.commit()

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


# ===== COLLECTIONS =====

@admin_bp.route('/collections')
@admin_required
def collections():
    """Manage collections"""
    from utils.group_orders import is_deadline_passed

    collections = Collection.query.order_by(Collection.created_at.desc()).all()
    for c in collections:
        # Active = not marked inactive and order window not past deadline
        c.list_active = bool(c.is_active) and not is_deadline_passed(c)
    return render_template('admin/collections.html', collections=collections)


@admin_bp.route('/collections/add', methods=['GET', 'POST'])
@admin_required
def add_collection():
    """Add new collection"""
    if request.method == 'POST':
        from slugify import slugify
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Please enter a name for the group order.', 'error')
            return redirect(url_for('admin.add_collection'))

        try:
            slug = (request.form.get('slug') or slugify(name)).strip() or slugify(name)
            base_slug = slug
            n = 1
            while Collection.query.filter_by(slug=slug).first():
                slug = f"{base_slug}-{n}"
                n += 1
            if slug != base_slug:
                flash(f'URL slug adjusted to "{slug}" (original was already in use).', 'info')

            collection = Collection(
                name=name,
                slug=slug,
                description=request.form.get('description'),
                is_active=request.form.get('is_active') == 'on',
                pickup_address=request.form.get('pickup_address'),
                pickup_instructions=request.form.get('pickup_instructions'),
                shipping_enabled=request.form.get('shipping_enabled') == 'on',
                allow_cash_pickup=request.form.get('allow_cash_pickup') == 'on',
                tax_rate=float(current_app.config['KS_SALES_TAX_PERCENT']),
            )

            collection.restrict_options = request.form.get('restrict_options') == 'on'
            collection.allow_custom_upload = True
            from utils.group_orders import serialize_allowed_colors_from_form
            allowed_colors_json = serialize_allowed_colors_from_form(request.form.getlist('allowed_colors'))
            collection.allowed_colors = allowed_colors_json
            allowed_placements = request.form.getlist('allowed_placements')
            collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None

            from utils.privacy import selectable_group_order_design_ids
            allowed_design_ids = selectable_group_order_design_ids(
                request.form.getlist('allowed_designs'), current_user
            )
            pending_uploads = [
                f for f in request.files.getlist('design_uploads') if f and f.filename
            ]
            if allowed_design_ids:
                collection.allowed_design_ids = json.dumps(allowed_design_ids)
            if allowed_design_ids or allowed_colors_json:
                collection.restrict_options = True

            collection.back_design_font = request.form.get('back_design_font') or None
            # Uniform back-design style controls
            collection.back_design_text_color = request.form.get('back_design_text_color') or None
            collection.back_design_outline = request.form.get('back_design_outline') != 'off'
            collection.back_design_outline_color = request.form.get('back_design_outline_color') or None
            collection.lock_back_design_style = request.form.get('lock_back_design_style') == 'on'

            from utils.group_orders import apply_collection_card, apply_schedule_from_form, set_collection_products_from_form
            apply_collection_card(collection)

            password = request.form.get('password')
            if password:
                collection.set_password(password)
            ok, schedule_error = apply_schedule_from_form(collection)
            if not ok:
                flash(schedule_error, 'error')
                return redirect(url_for('admin.add_collection'))

            db.session.add(collection)
            db.session.flush()

            selected_products = set_collection_products_from_form(collection)
            if not selected_products:
                db.session.rollback()
                flash('Please pick at least one shirt style so your team has something to order.', 'error')
                return redirect(url_for('admin.add_collection'))

            db.session.commit()

            upload_count = 0
            new_upload_ids = []
            if pending_uploads:
                for f in pending_uploads:
                    try:
                        design = _save_collection_design(f, current_user.id)
                    except Exception as e:
                        current_app.logger.exception('Collection design upload failed: %s', e)
                        design = None
                    if design:
                        allowed_design_ids.append(design.id)
                        new_upload_ids.append(design.id)
                        upload_count += 1
                if upload_count:
                    collection.allowed_design_ids = json.dumps(allowed_design_ids)
                    collection.restrict_options = True

            from utils.group_orders import resolve_showcase_design_ids
            showcase_ids = resolve_showcase_design_ids(
                allowed_design_ids,
                form_showcase=request.form.getlist('showcase_designs'),
                new_upload_ids=new_upload_ids,
                showcase_new_uploads=request.form.get('showcase_new_uploads') == 'on',
            )
            collection.showcase_design_ids = json.dumps(showcase_ids) if showcase_ids else None
            if upload_count or showcase_ids:
                db.session.commit()

            msg = 'Group order created successfully'
            if upload_count:
                msg += f' with {upload_count} design(s) uploaded'
            flash(msg + '.', 'success')
            return redirect(url_for('admin.collections'))

        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.warning('Admin add_collection IntegrityError: %s', e)
            flash('A group order with that name or URL already exists. Try a different name.', 'error')
            return redirect(url_for('admin.add_collection'))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('Admin add_collection database error: %s', e)
            flash('Could not save the group order due to a server issue. Please try again.', 'error')
            return redirect(url_for('admin.add_collection'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Admin add_collection unexpected error: %s', e)
            flash('Something went wrong while creating the group order. Please try again.', 'error')
            return redirect(url_for('admin.add_collection'))
    
    from utils.product_filters import load_group_order_form_catalog
    from utils.fonts import GROUP_ORDER_FONTS
    catalog = load_group_order_form_catalog()
    return render_template(
        'admin/add_collection.html',
        products=catalog['products'],
        gallery_designs=catalog['gallery_designs'],
        all_colors=catalog.get('colors_by_brand') or catalog['all_colors'],
        back_design_fonts=GROUP_ORDER_FONTS,
        catalog_filter_opts=catalog['catalog_filter_opts'],
        catalog_filter_picker=True,
    )


@admin_bp.route('/collections/<int:collection_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_collection(collection_id):
    """Edit collection"""
    from utils.product_filters import catalog_filter_options, prepare_catalog
    from utils.group_orders import apply_collection_form, designs_for_group_order_form
    import json

    collection = Collection.query.get_or_404(collection_id)
    
    if request.method == 'POST':
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        try:
            ok, error, upload_count = apply_collection_form(
                collection, current_user, allow_slug=True, require_products=True
            )
            if not ok:
                db.session.rollback()
                flash(error, 'error')
                return redirect(url_for('admin.edit_collection', collection_id=collection.id))

            db.session.commit()
            msg = 'Group order updated successfully'
            if upload_count:
                msg += f' with {upload_count} new design(s) uploaded'
            flash(msg + '.', 'success')
            return redirect(url_for('admin.collections'))

        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.warning('Admin edit_collection IntegrityError: %s', e)
            flash('A group order with that URL slug already exists. Choose a different slug.', 'error')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('Admin edit_collection database error: %s', e)
            flash('Could not save the group order due to a server issue. Please try again.', 'error')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Admin edit_collection unexpected error: %s', e)
            flash('Something went wrong while saving the group order. Please try again.', 'error')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))
    
    products = prepare_catalog(Product.query.filter_by(is_active=True).all())
    gallery_designs = designs_for_group_order_form(collection)
    # Build colors grouped by brand from this collection's products
    colors_by_brand: dict[str, list[str]] = {}
    for p in collection.products:
        brand_key = p.brand or 'Other'
        for v in ProductColorVariant.query.filter_by(product_id=p.id).all():
            if v.color_name:
                colors_by_brand.setdefault(brand_key, set()).add(v.color_name)
    colors_by_brand = {b: sorted(c) for b, c in sorted(colors_by_brand.items())}
    collection_color_names = colors_by_brand  # passed to template as dict
    from utils.group_orders import allowed_color_form_keys
    allowed_color_keys = allowed_color_form_keys(collection)
    try:
        _raw_colors = json.loads(collection.allowed_colors) if collection.allowed_colors else []
        allowed_colors_list = _raw_colors if isinstance(_raw_colors, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        allowed_colors_list = []
    allowed_design_ids_list = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    showcase_design_ids_list = json.loads(collection.showcase_design_ids) if getattr(collection, 'showcase_design_ids', None) else []
    allowed_placements_list = json.loads(collection.allowed_placements) if collection.allowed_placements else ['center_chest', 'left_chest', 'right_chest', 'center_back']
    from utils.fonts import GROUP_ORDER_FONTS
    return render_template('admin/edit_collection.html',
                         collection=collection,
                         products=products,
                         gallery_designs=gallery_designs,
                         collection_colors=collection_color_names,
                         allowed_colors_list=allowed_colors_list,
                         allowed_color_keys=allowed_color_keys,
                         allowed_design_ids_list=allowed_design_ids_list,
                         showcase_design_ids_list=showcase_design_ids_list,
                         allowed_placements_list=allowed_placements_list,
                         back_design_fonts=GROUP_ORDER_FONTS,
                         collection_product_ids=[p.id for p in collection.products],
                         catalog_filter_opts=catalog_filter_options(products),
                         catalog_filter_picker=True)


@admin_bp.route('/collections/<int:collection_id>/delete', methods=['POST'])
@admin_required
def delete_collection(collection_id):
    """Delete a collection"""
    collection = Collection.query.get_or_404(collection_id)
    db.session.delete(collection)
    db.session.commit()
    flash('Group order deleted', 'success')
    return redirect(url_for('admin.collections'))


@admin_bp.route('/collections/<int:collection_id>/designs/<int:design_id>/remove', methods=['POST'])
@admin_required
def collection_design_remove(collection_id, design_id):
    """Remove a design from a collection's approved list and permanently delete it."""
    import json as _json
    collection = Collection.query.get_or_404(collection_id)
    design = Design.query.get_or_404(design_id)

    # Remove from allowed_design_ids
    ids = _json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    ids = [i for i in ids if i != design_id]
    collection.allowed_design_ids = _json.dumps(ids) if ids else None

    # Delete the design record and its file
    try:
        _delete_design_file(design)
    except Exception as e:
        current_app.logger.warning('Could not delete design file for design %s: %s', design_id, e)
    db.session.delete(design)

    try:
        db.session.commit()
        flash('Design removed from group order.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('collection_design_remove failed: %s', e)
        flash('Could not remove design. Please try again.', 'error')

    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


# ===== PRODUCTION CENTER =====

@admin_bp.route('/production/master')
@admin_required
def production_master():
    """Master copy: blanks + designs for orders just received or waiting on supplies."""
    from utils.ops_flow import ops_order_query
    query, stages, collection_id = ops_order_query(['order_received', 'waiting_supplies'])
    orders = query.order_by(Order.created_at).all()
    
    # Blank apparel totals
    apparel_totals = {}
    for order in orders:
        for item in order.items:
            key = (item.style_number, item.product_name, item.color, item.size)
            if key not in apparel_totals:
                apparel_totals[key] = {
                    'style_number': item.style_number,
                    'product_name': item.product_name,
                    'color': item.color,
                    'size': item.size,
                    'quantity': 0
                }
            apparel_totals[key]['quantity'] += item.quantity
    
    apparel_list = sorted(apparel_totals.values(), key=lambda x: (x['style_number'], x['color'], x['size']))
    
    # Design/logo totals (grouped by design, placement, print size)
    from utils.print_sizes import production_from_order_item, inches
    from utils.order_artwork import back_print_url
    design_groups = {}
    personal_list = []
    for order in orders:
        for item in order.items:
            prod = production_from_order_item(item, customer_name=order.full_name)
            front = (prod or {}).get('front')
            if front:
                pw = front.get('width')
                ph = front.get('height')
                key = (item.design_id, item.placement or '', inches(pw), inches(ph))
                if key not in design_groups:
                    design_groups[key] = {
                        'design': item.design,
                        'design_name': front.get('design_name'),
                        'placement': item.placement or '-',
                        'print_width': pw,
                        'print_height': ph,
                        'quantity': 0
                    }
                design_groups[key]['quantity'] += item.quantity
            back = (prod or {}).get('back')
            if back:
                back = dict(back)
                back['print_url'] = back_print_url(item)
                back['order_id'] = order.id
                back['item_id'] = item.id
                personal_list.append(back)
    
    design_list = sorted(design_groups.values(), key=lambda x: (getattr(x['design'], 'filename', '') or x.get('design_name') or '', x['placement']))
    
    collections = Collection.query.all()
    
    return render_template('admin/production_master.html',
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
    group_by = request.args.get('group', 'size')

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
            csv_query = csv_query.filter_by(collection_id=cid)
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
    """After blanks are ordered, move these orders to Ready to Press."""
    from utils.ops_flow import ops_order_query
    from utils.production_stages import apply_stage
    query, _stages, collection_id = ops_order_query(['order_received', 'waiting_supplies'])
    if request.form.get('collection') or collection_id:
        cid = request.form.get('collection') or collection_id
        query = query.filter_by(collection_id=cid)

    orders = query.all()
    count = 0
    for order in orders:
        apply_stage(order, 'ready_to_press')
        count += 1

    db.session.commit()
    flash(f'Moved {count} order(s) to Ready to Press — next up: press sheets.', 'success')
    from utils.ops_flow import ops_url
    return redirect(ops_url('admin.transfer_production', stage=['ready_to_press'], collection=collection_id))


@admin_bp.route('/production')
@admin_required
def production():
    """Production center dashboard"""
    # Get orders in production or ready for production
    orders = Order.query.filter(
        Order.status.in_(['paid', 'in_production'])
    ).order_by(Order.created_at).all()
    
    return render_template('admin/production.html', orders=orders)


@admin_bp.route('/production/blank-apparel-list')
@admin_required
def blank_apparel_list():
    """Weekly blank shopping list — nothing is purchased until you check out at S&S/SanMar."""
    from utils.ops_flow import ops_order_query
    from utils.blank_orders import build_blank_shopping_list
    query, _stages, collection_id = ops_order_query(['order_received', 'waiting_supplies'])
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


@admin_bp.route('/orders/print-labels')
@admin_required
def print_labels():
    """Generate printable order labels for sticker paper (3 columns × 10 rows = 30 per sheet)"""
    from utils.production_stages import STAGES, orders_for_stages
    collection_id = request.args.get('collection')
    order_id = request.args.get('order_id', type=int)
    stage_filter = request.args.getlist('stage') or [sid for sid, _name, _desc in STAGES]

    if order_id:
        query = Order.query.filter_by(id=order_id)
    else:
        query = orders_for_stages(stage_filter)
        if collection_id:
            query = query.filter_by(collection_id=collection_id)

    def _label_sort_key(order):
        send_home = 0 if getattr(order, 'send_home_with_child', False) else 1
        teacher = (getattr(order, 'teacher_name', None) or '').strip().lower()
        grade = (getattr(order, 'child_grade', None) or '').strip().lower()
        child = (getattr(order, 'child_name', None) or '').strip().lower()
        return (send_home, teacher, grade, child, order.created_at or datetime.min)

    orders = sorted(query.all(), key=_label_sort_key)
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
    for order in orders:
        for item in order.items:
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
    from utils.ops_flow import ops_order_query
    from utils.dtf_orders import build_dtf_shopping_list
    query, _stages, collection_id = ops_order_query(['order_received', 'waiting_supplies'])
    orders = query.order_by(Order.created_at).all()
    shopping = build_dtf_shopping_list(orders)

    if request.args.get('format') == 'csv':
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=['kind', 'design_or_name', 'placement', 'order_by', 'size_in', 'height_in', 'quantity', 'order_number'],
        )
        writer.writeheader()
        writer.writerows(shopping['csv_rows'])
        return send_file(
            BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'dtf_shopping_list_{datetime.now().strftime("%Y%m%d")}.csv',
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


# ===== DESIGNS (Library + Gallery tabs) =====

def _admin_designs_url(tab='gallery'):
    """Canonical designs page URL; tab is library|gallery."""
    tab = 'library' if tab == 'library' else 'gallery'
    return url_for('admin.designs', tab=tab)


@admin_bp.route('/designs')
@admin_required
def designs():
    """Combined Design Library (customer uploads) + Gallery (curated public designs)."""
    tab = (request.args.get('tab') or 'library').strip().lower()
    if tab not in ('library', 'gallery'):
        tab = 'library'

    library_designs = (
        Design.query
        .filter(
            Design.is_gallery == False,
            or_(Design.hidden_from_admin == False, Design.hidden_from_admin.is_(None)),
        )
        .order_by(Design.uploaded_at.desc())
        .all()
    )

    try:
        from utils.design_variants import gallery_mains_query
        gallery_designs = gallery_mains_query(Design).all()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to load admin design gallery: %s', e)
        flash('We could not load the design gallery (a database issue). '
              'If this persists, a database migration may be pending.', 'error')
        gallery_designs = []

    # Pending non-gallery uploads for promote-to-gallery (gallery tab)
    try:
        pending_designs = (
            Design.query
            .filter(
                Design.is_gallery == False,
                or_(Design.hidden_from_admin == False, Design.hidden_from_admin.is_(None)),
            )
            .order_by(Design.uploaded_at.desc())
            .limit(50)
            .all()
        )
    except Exception:
        pending_designs = []

    return render_template(
        'admin/designs.html',
        active_tab=tab,
        library_designs=library_designs,
        gallery_designs=gallery_designs,
        pending_designs=pending_designs,
    )


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
            design.title = (design.original_filename or 'Design').rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ').title()[:100]
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
    """Upload a design to the customer gallery"""
    from sqlalchemy.exc import SQLAlchemyError

    if 'file' not in request.files:
        flash('No file provided.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))

    file = request.files['file']
    if not file or not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))

    filename = secure_filename(file.filename)
    if '.' not in filename:
        flash('File must have an extension (PNG, JPG, etc.).', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))

    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_DESIGN_EXTS:
        flash('Unsupported format. Use PNG, JPG, WEBP, or HEIC.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))

    try:
        # Use _save_uploaded_design so cloud storage (R2) and background
        # removal are handled exactly the same way as every other upload path.
        design = _save_uploaded_design(file, current_user.id)
        if design is None:
            flash('Upload failed — file could not be stored. Please try again.', 'error')
            return redirect(url_for('admin.designs', tab='gallery'))

        # Override defaults with values from the form
        title = (request.form.get('title') or '').strip()
        if title:
            design.title = title
        folder = (request.form.get('folder') or 'custom_orders').strip()
        design.folder = folder
        sku = (request.form.get('sku') or '').strip()
        if sku:
            design.sku = sku

        # Optional: upload as a color variant of an existing main design
        from utils.design_variants import ensure_not_nested_parent
        parent_id = request.form.get('parent_design_id', type=int)
        variant_label = (request.form.get('variant_label') or '').strip()[:80]
        if parent_id:
            parent = Design.query.get(parent_id)
            parent = ensure_not_nested_parent(parent)
            if parent and parent.is_gallery and parent.id != design.id:
                design.parent_design_id = parent.id
                design.variant_label = variant_label or 'Color'
                if not (parent.variant_label or '').strip():
                    parent.variant_label = 'Default'
                if not title:
                    design.title = parent.title or parent.original_filename
                if not sku and parent.sku:
                    design.sku = parent.sku
                design.folder = parent.folder or design.folder
                design.is_gallery = True

        db.session.commit()
        if design.parent_design_id:
            flash(
                f'Color "{design.variant_label}" added to '
                f'"{design.parent_design.title or design.parent_design.original_filename}".',
                'success',
            )
        else:
            flash(f'Design "{design.title or design.original_filename}" added to gallery!', 'success')
        return redirect(url_for('admin.designs', tab='gallery'))

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception('design_gallery_upload DB error: %s', e)
        flash('The design could not be saved — a database error occurred. '
              'If this keeps happening, run the database migration script.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('design_gallery_upload unexpected error: %s', e)
        flash('Something went wrong while uploading the design. Please try again.', 'error')
        return redirect(url_for('admin.designs', tab='gallery'))


@admin_bp.route('/design-gallery/<int:design_id>/edit', methods=['POST'])
@admin_required
def design_gallery_edit(design_id):
    """Update gallery design metadata (and optionally replace the image file)."""
    from sqlalchemy.exc import SQLAlchemyError

    design = Design.query.get_or_404(design_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    GALLERY_FOLDERS = {
        'custom_orders', 'evergreen', 'school', 'holiday',
        'sports', 'funny', 'luxury_basics',
    }

    title = (request.form.get('title') or '').strip()
    folder = (request.form.get('folder') or '').strip() or design.folder or 'custom_orders'
    if folder not in GALLERY_FOLDERS:
        folder = 'custom_orders'
    sku = (request.form.get('sku') or '').strip()
    variant_label = (request.form.get('variant_label') or '').strip()[:80]

    try:
        if title:
            design.title = title[:200]
        design.folder = folder
        design.sku = sku[:50] if sku else None
        design.variant_label = variant_label or design.variant_label

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
            'sku': design.sku or '',
            'image_url': resolve_image_url(design.file_path) if design.file_path else '',
        },
    }
    if is_ajax:
        return jsonify(payload)
    flash(payload['message'], 'success')
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


# ===== PUBLIC GALLERY APPROVAL QUEUE =====

def _design_validation_meta(design):
    """Best-effort transparency/background check for a queued design, used to
    help admins verify the cutout before publishing. Reads the local file when
    available; otherwise falls back to the stored transparency flag."""
    meta = {
        'has_transparency': bool(getattr(design, 'has_transparency', False)),
        'validation': None,
    }
    try:
        fp = design.file_path or ''
        data = None
        if not fp.startswith('http'):
            p = Path('static') / fp
            if p.exists():
                data = p.read_bytes()
        if data:
            from services.image_processing import process_artwork_bytes, issue_messages
            res = process_artwork_bytes(data, mode='none')
            meta['has_transparency'] = bool(res.get('has_transparency'))
            v = res.get('validation') or {}
            meta['validation'] = {
                'issues': v.get('issues', []),
                'messages': issue_messages(v),
                'metrics': v.get('metrics', {}),
            }
    except Exception:
        pass
    return meta


@admin_bp.route('/gallery-queue')
@admin_required
def gallery_queue():
    """Review queue: customer designs awaiting approval before publication."""
    try:
        pending = (Design.query
                   .filter(Design.gallery_status.in_(['pending', 'changes_requested']))
                   .order_by(Design.uploaded_at.desc())
                   .all())
        recent = (Design.query
                  .filter(Design.gallery_status.in_(['approved', 'rejected']))
                  .order_by(Design.uploaded_at.desc())
                  .limit(24).all())
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to load gallery approval queue: %s', e)
        flash('We could not load the approval queue (a database issue). '
              'If this persists, a database migration may be pending.', 'error')
        pending, recent = [], []

    # Build per-design validation metadata defensively — a single bad record or
    # unreadable image must never crash the whole queue.
    queue = []
    for d in pending:
        try:
            meta = _design_validation_meta(d)
        except Exception as e:
            current_app.logger.exception('Validation meta failed for design %s: %s', getattr(d, 'id', '?'), e)
            meta = {'has_transparency': False, 'validation': None}
        queue.append({'design': d, 'meta': meta})
    return render_template('admin/gallery_queue.html', queue=queue, recent=recent)


def _review_design(design_id):
    design = Design.query.get_or_404(design_id)
    return design


def _commit_review(design, success_msg):
    """Commit a review action, returning a JSON/redirect response. Handles
    failures gracefully so a single bad action never 500s the admin."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Gallery review action failed for design %s: %s',
                                     getattr(design, 'id', '?'), e)
        err = 'Could not save this action due to a server issue. Please try again.'
        if is_ajax:
            return jsonify({'ok': False, 'error': err}), 500
        flash(err, 'error')
        return redirect(url_for('admin.gallery_queue'))
    if is_ajax:
        return jsonify({'ok': True, 'message': success_msg})
    flash(success_msg, 'success')
    return redirect(url_for('admin.gallery_queue'))


@admin_bp.route('/gallery-queue/<int:design_id>/approve', methods=['POST'])
@admin_required
def gallery_approve(design_id):
    """Approve a submitted design and publish it to the public gallery."""
    design = _review_design(design_id)
    design.gallery_status = 'approved'
    design.gallery_submitted = True
    design.is_gallery = True            # now visible on public-facing pages
    design.gallery_rejection_reason = None
    design.gallery_reviewed_at = datetime.utcnow()
    design.gallery_reviewed_by_id = current_user.id
    if not design.folder:
        design.folder = request.form.get('folder') or 'custom_orders'
    name = design.title or design.original_filename or 'Design'
    return _commit_review(design, f'"{name}" approved and published to the gallery.')


@admin_bp.route('/gallery-queue/<int:design_id>/reject', methods=['POST'])
@admin_required
def gallery_reject(design_id):
    """Reject a submitted design. It stays hidden from the public gallery."""
    design = _review_design(design_id)
    reason = (request.form.get('reason') or '').strip()
    design.gallery_status = 'rejected'
    design.is_gallery = False           # ensure it is not public
    design.gallery_rejection_reason = reason or 'Did not meet gallery guidelines.'
    design.gallery_reviewed_at = datetime.utcnow()
    design.gallery_reviewed_by_id = current_user.id
    name = design.title or design.original_filename or 'Design'
    return _commit_review(design, f'"{name}" rejected and kept hidden.')


@admin_bp.route('/gallery-queue/<int:design_id>/request-changes', methods=['POST'])
@admin_required
def gallery_request_changes(design_id):
    """Ask the submitter for changes. Design stays hidden until re-reviewed."""
    design = _review_design(design_id)
    reason = (request.form.get('reason') or '').strip()
    design.gallery_status = 'changes_requested'
    design.is_gallery = False
    design.gallery_rejection_reason = reason or 'Changes requested before publication.'
    design.gallery_reviewed_at = datetime.utcnow()
    design.gallery_reviewed_by_id = current_user.id
    name = design.title or design.original_filename or 'Design'
    return _commit_review(design, f'Changes requested for "{name}".')


@admin_bp.context_processor
def _inject_gallery_pending_count():
    """Expose the pending-review count to admin templates (nav badge)."""
    count = 0
    try:
        count = (Design.query
                 .filter(Design.gallery_status.in_(['pending', 'changes_requested']))
                 .count())
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        count = 0
    return {'gallery_pending_count': count}


# ===== RECREATE REQUESTS (Have Us Recreate) =====

@admin_bp.route('/custom-design-requests')
@admin_required
def custom_design_requests():
    """List all custom design requests from customers"""
    status_filter = request.args.get('status', 'pending')
    query = CustomDesignRequest.query.order_by(CustomDesignRequest.created_at.desc())
    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)
    requests = query.all()
    return render_template('admin/custom_design_requests.html', requests=requests, status_filter=status_filter)


@admin_bp.route('/custom-design-requests/<int:request_id>', methods=['GET', 'POST'])
@admin_required
def custom_design_request_detail(request_id):
    """View request and upload completed design for customer"""
    req = CustomDesignRequest.query.get_or_404(request_id)

    if request.method == 'POST':
        try:
            return _handle_design_request_post(req)
        except Exception as e:
            current_app.logger.exception(
                'custom design request %s POST failed: %s', request_id, e,
            )
            try:
                db.session.rollback()
            except Exception:
                pass
            flash('Something went wrong. Please refresh and try again.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=request_id))

    try:
        return render_template('admin/custom_design_request_detail.html', req=req)
    except Exception as e:
        current_app.logger.exception(
            'custom design request %s GET render failed: %s', request_id, e,
        )
        flash('The design was saved. Refresh this page to see it.', 'info')
        return redirect(url_for('admin.custom_design_requests'))


def _handle_design_request_post(req):
    action = request.form.get('action')
    if action == 'upload_design':
        if req.status == 'completed' and req.created_design_id:
            flash('This request already has a design on the customer profile.', 'info')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        file = request.files.get('design_file')
        title = request.form.get('title', '').strip() or (
            req.description[:50] + '...' if len(req.description or '') > 50 else req.description
        )
        design_fee = request.form.get('design_fee', '0')
        if not file or not file.filename:
            flash('Please select a design file to upload.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        try:
            design, local_path, r2_prefix = _save_design_for_user(
                file, req.user_id, title=title or None, design_fee=design_fee,
            )
        except DesignUploadError:
            db.session.rollback()
            flash('The image could not be stored. Please try uploading it again.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        if design is None:
            flash('Unsupported file type. Use PNG, JPG, WEBP, or HEIC.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        req.created_design_id = design.id
        req.status = 'completed'
        req.design_fee = float(design_fee or 0)
        req.admin_notes = (req.admin_notes or '') + (
            f"\n[Design uploaded: {design.filename}, fee: ${design.design_fee:.0f}]"
        )
        customer_name = getattr(getattr(req, 'user', None), 'full_name', None) or 'the customer'
        db.session.commit()

        try:
            from utils.background import run_in_background
            app_obj = current_app._get_current_object()
            run_in_background(app_obj, _promote_design_to_r2, design.id, local_path, r2_prefix)
            run_in_background(app_obj, _email_design_request_decision, req.id, 'completed')
        except Exception:
            current_app.logger.exception('background follow-up failed after design upload')
        flash(
            f"Image added to {customer_name}'s profile. It's in their My Designs now.",
            'success',
        )
        return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

    if action == 'add_notes':
        req.admin_notes = request.form.get('admin_notes', '')
        db.session.commit()
        flash('Notes saved', 'success')
    elif action == 'decline':
        reason = (request.form.get('decline_reason') or '').strip()
        req.status = 'declined'
        req.admin_notes = (req.admin_notes or '') + '\n' + (reason or 'Declined')
        db.session.commit()
        from utils.background import run_in_background
        run_in_background(
            current_app._get_current_object(),
            _email_design_request_decision,
            req.id, 'declined', reason or None,
        )
        flash('Request declined and customer notified by email.', 'info')
    elif action == 'delete':
        db.session.delete(req)
        db.session.commit()
        flash('Request permanently deleted.', 'info')
        return redirect(url_for('admin.custom_design_requests'))
    return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))


def _send_design_request_decision_email(req, decision, reason=None):
    """Email the customer when their design request is approved or declined."""
    try:
        from flask_mail import Message as MailMessage
        mail = current_app.extensions.get('mail')
        if not mail:
            return False
        cfg = current_app.config
        if not (cfg.get('MAIL_SERVER') and cfg.get('MAIL_USERNAME') and cfg.get('MAIL_PASSWORD')):
            current_app.logger.warning('design request email skipped — mail not configured')
            return False

        user = req.user
        email = getattr(user, 'email', None)
        if not email:
            return False

        from utils.mailer import sender as _sender_tuple
        app_obj = current_app._get_current_object()
        first = getattr(user, 'first_name', None) or 'there'
        sender = _sender_tuple(app_obj)

        if decision == 'completed':
            subject = "Your custom design is ready! — Purposefully Made KC"
            body = (
                f"Hi {first},\n\n"
                f"Great news — your custom design request has been completed!\n\n"
                f"Your design is now in your My Designs. Log in and head to "
                f"My Account → My Designs to find it. From there you can apply "
                f"it to any shirt style, color, or size.\n\n"
                f"https://purposefullymadekc.com/account\n\n"
                f"Questions? Reply here or email purposefullymadekc@gmail.com\n\n"
                f"— Purposefully Made KC"
            )
        else:
            subject = "Update on your design request — Purposefully Made KC"
            reason_line = f"\n\nReason: {reason}" if reason else ""
            body = (
                f"Hi {first},\n\n"
                f"Unfortunately we're unable to complete your design request at this time.{reason_line}\n\n"
                f"If you have questions or would like to submit a different request, "
                f"feel free to reach out at purposefullymadekc@gmail.com or submit a new request "
                f"at https://purposefullymadekc.com/custom-design/submit\n\n"
                f"— Purposefully Made KC"
            )

        from utils.mailer import send as _send_mail
        msg = MailMessage(
            subject=subject,
            recipients=[email],
            body=body,
            sender=sender,
            reply_to='purposefullymadekc@gmail.com',
        )
        return _send_mail(
            app_obj, msg,
            description=f'design request {decision} notice for request {req.id}',
        )
    except Exception as e:
        current_app.logger.exception('design request decision email failed for request %s: %s', req.id, e)
        return False


@admin_bp.route('/designs/<int:design_id>/delete', methods=['POST'])
@admin_required
def design_delete(design_id):
    """Remove a design from the admin Design Library.

    Customer-owned designs are soft-hidden so My Designs (and the file) stay
    intact. Orphan / admin-only designs with no order or request links are
    hard-deleted. Always returns quickly with JSON for the AJAX modal.
    """
    design = Design.query.get_or_404(design_id)
    name = design.title or design.original_filename or 'Design'
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _json_or_redirect(payload, *, ok=True, flash_msg=None, flash_cat='success'):
        if flash_msg:
            flash(flash_msg, flash_cat)
        if is_ajax:
            status = 200 if ok else 400
            return jsonify(payload), status
        return redirect(url_for('admin.designs', tab='library'))

    try:
        # Customer copy must survive admin cleanup of the library list.
        if design.uploaded_by_user_id:
            design.hidden_from_admin = True
            db.session.commit()
            return _json_or_redirect(
                {
                    'ok': True,
                    'message': f'"{name}" removed from admin library. Customer still has their copy.',
                },
                flash_msg='Removed from admin library (customer copy kept)',
            )

        # Linked to orders or recreate requests — never destroy the file/row.
        try:
            in_orders = design.order_items.count() > 0
        except Exception:
            in_orders = False
        linked_request = None
        try:
            from models import CustomDesignRequest
            linked_request = CustomDesignRequest.query.filter_by(
                created_design_id=design.id
            ).first()
        except Exception:
            linked_request = None

        if in_orders or linked_request:
            design.hidden_from_admin = True
            db.session.commit()
            reason = 'linked to orders' if in_orders else 'linked to a recreate request'
            return _json_or_redirect(
                {
                    'ok': True,
                    'message': f'"{name}" hidden from admin library ({reason}; file kept).',
                },
                flash_msg=f'Hidden from library ({reason})',
            )

        # Safe hard delete for orphan admin uploads
        file_path = design.file_path
        db.session.delete(design)
        db.session.commit()
        # Unlink after commit so a stuck disk op never blocks the UI response path
        # for future soft-hides; for hard delete we still try briefly.
        if file_path:
            try:
                full_path = Path('static') / file_path
                if full_path.exists():
                    full_path.unlink()
            except OSError:
                pass

        return _json_or_redirect(
            {'ok': True, 'message': f'"{name}" permanently deleted'},
            flash_msg='Design deleted permanently',
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to delete design %s: %s', design_id, e)
        return _json_or_redirect(
            {'ok': False, 'error': 'Could not delete the design. Please try again.'},
            ok=False,
            flash_msg='Could not delete the design. Please try again.',
            flash_cat='error',
        )


def _delete_design_file(design):
    """Remove design file from disk if it exists"""
    if design and design.file_path:
        full_path = Path('static') / design.file_path
        if full_path.exists():
            try:
                full_path.unlink()
            except OSError:
                pass


# ===== OPERATIONS: INVENTORY =====

@admin_bp.route('/operations/inventory')
@admin_required
def inventory():
    """Inventory management - apparel, transfers, supplies"""
    apparel = ApparelInventory.query.order_by(ApparelInventory.brand, ApparelInventory.color).all()
    transfers = TransferInventory.query.order_by(TransferInventory.design_name).all()
    supplies = Supply.query.order_by(Supply.category, Supply.name).all()
    vendors = Vendor.query.order_by(Vendor.name).all()
    return render_template('admin/operations/inventory.html',
                         apparel=apparel, transfers=transfers, supplies=supplies, vendors=vendors)


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
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory/apparel/<int:id>/update', methods=['POST'])
@admin_required
def update_apparel_inventory(id):
    inv = ApparelInventory.query.get_or_404(id)
    inv.quantity = int(request.form.get('quantity') or 0)
    inv.cost_per_unit = _form_money('cost_per_unit', 0.0) or None
    inv.reorder_threshold = int(request.form.get('reorder_threshold') or 5)
    db.session.commit()
    flash('Apparel updated', 'success')
    return redirect(url_for('admin.inventory'))


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
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory/supply/<int:id>/update', methods=['POST'])
@admin_required
def update_supply(id):
    s = Supply.query.get_or_404(id)
    s.quantity = int(request.form.get('quantity') or 0)
    s.cost_per_unit = _form_money('cost_per_unit', 0.0) or None
    s.reorder_threshold = int(request.form.get('reorder_threshold') or 0)
    db.session.commit()
    flash('Supply updated', 'success')
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory/transfer/add', methods=['POST'])
@admin_required
def add_transfer_inventory():
    t = TransferInventory(design_name=request.form.get('design_name'), size=request.form.get('size'),
                          quantity=int(request.form.get('quantity') or 0),
                          cost_per_sheet=_form_money('cost_per_sheet', 0.0) or None,
                          vendor_id=int(request.form.get('vendor_id')) if request.form.get('vendor_id') else None,
                          delivery_time=request.form.get('delivery_time'))
    db.session.add(t)
    db.session.commit()
    flash('Transfer added', 'success')
    return redirect(url_for('admin.inventory'))


# ===== OPERATIONS: VENDORS =====

@admin_bp.route('/operations/vendors')
@admin_required
def vendors():
    vendors_list = Vendor.query.order_by(Vendor.name).all()
    return render_template('admin/operations/vendors.html', vendors=vendors_list)


@admin_bp.route('/operations/vendors/add', methods=['GET', 'POST'])
@admin_required
def add_vendor():
    if request.method == 'POST':
        v = Vendor(name=request.form.get('name'), contact_name=request.form.get('contact_name'),
                   contact_email=request.form.get('contact_email'), contact_phone=request.form.get('contact_phone'),
                   website=request.form.get('website'), website_login=request.form.get('website_login'),
                   lead_time_days=int(request.form.get('lead_time_days') or 0) or None,
                   moq=int(request.form.get('moq') or 0) or None,
                   pricing_tier=request.form.get('pricing_tier'),
                   quality_rating=int(request.form.get('quality_rating') or 0) or None,
                   notes=request.form.get('notes'))
        db.session.add(v)
        db.session.commit()
        flash('Vendor added', 'success')
        return redirect(url_for('admin.vendors'))
    return render_template('admin/operations/vendor_form.html', vendor=None)


@admin_bp.route('/operations/vendors/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_vendor(id):
    v = Vendor.query.get_or_404(id)
    if request.method == 'POST':
        v.name = request.form.get('name')
        v.contact_name = request.form.get('contact_name')
        v.contact_email = request.form.get('contact_email')
        v.contact_phone = request.form.get('contact_phone')
        v.website = request.form.get('website')
        v.website_login = request.form.get('website_login')
        v.lead_time_days = int(request.form.get('lead_time_days') or 0) or None
        v.moq = int(request.form.get('moq') or 0) or None
        v.pricing_tier = request.form.get('pricing_tier')
        v.quality_rating = int(request.form.get('quality_rating') or 0) or None
        v.notes = request.form.get('notes')
        db.session.commit()
        flash('Vendor updated', 'success')
        return redirect(url_for('admin.vendors'))
    return render_template('admin/operations/vendor_form.html', vendor=v)


# ===== OPERATIONS: PRODUCTION WORKFLOW (KANBAN) =====

@admin_bp.route('/operations/workflow')
@admin_required
def production_workflow():
    """5-stage Kanban: Order Received → Waiting Supplies → Ready to Press → Pressed → Packaged Ready"""
    from utils.production_stages import STAGES, orders_for_stage
    from utils.ops_flow import current_collection
    from sqlalchemy.orm import joinedload
    stages = STAGES
    collection_id = current_collection() or None
    orders_by_stage = {}
    for sid, _name, _desc in stages:
        query = orders_for_stage(sid).options(joinedload(Order.collection))
        if collection_id:
            query = query.filter_by(collection_id=collection_id)
        orders_by_stage[sid] = query.order_by(Order.created_at).all()
    from datetime import datetime
    return render_template('admin/operations/workflow.html', stages=stages, orders_by_stage=orders_by_stage, now=datetime.utcnow())


@admin_bp.route('/orders/<int:order_id>/update-stage', methods=['POST'])
@admin_required
def update_order_stage(order_id):
    from utils.production_stages import apply_stage
    order = Order.query.get_or_404(order_id)
    stage = request.form.get('stage')
    apply_stage(order, stage)
    db.session.commit()
    flash('Stage updated', 'success')
    return redirect(request.referrer or url_for('admin.production_workflow'))


# ===== OPERATIONS: FINANCIAL =====

@admin_bp.route('/operations/financial')
@admin_required
def financial():
    orders = Order.query.filter(Order.payment_status == 'paid').all()
    total_revenue = sum(o.total for o in orders if not getattr(o, 'is_refunded', False))
    total_profit = sum(o.profit or 0 for o in orders if o.profit)
    entries = FinancialEntry.query.order_by(FinancialEntry.entry_date.desc()).limit(100).all()
    return render_template('admin/operations/financial.html',
                         total_revenue=total_revenue, total_profit=total_profit,
                         entries=entries)


@admin_bp.route('/operations/financial/entry/add', methods=['POST'])
@admin_required
def add_financial_entry():
    e = FinancialEntry(category=request.form.get('category'), amount=_form_money('amount', 0.0),
                       description=request.form.get('description'))
    db.session.add(e)
    db.session.commit()
    flash('Entry added', 'success')
    return redirect(url_for('admin.financial'))


# ===== OPERATIONS: EQUIPMENT =====

# ===== OPERATIONS: GROWTH DASHBOARD =====

@admin_bp.route('/operations/growth')
@admin_required
def growth():
    metrics = GrowthMetric.query.order_by(GrowthMetric.week_start.desc()).limit(12).all()
    return render_template('admin/operations/growth.html', metrics=metrics)


@admin_bp.route('/operations/growth/sync', methods=['POST'])
@admin_required
def sync_growth_metrics():
    """Auto-sync weekly metrics from orders & collections"""
    try:
        from services.growth_sync import sync_all_recent_weeks
        results = sync_all_recent_weeks(weeks=4)
        updated = sum(1 for _, a in results if a == 'updated')
        created = sum(1 for _, a in results if a == 'created')
        flash(f'Auto-synced: {created} new, {updated} updated (units, revenue, events, wholesale from your data)', 'success')
    except Exception as e:
        flash(f'Sync failed: {str(e)}', 'error')
    return redirect(url_for('admin.growth'))


@admin_bp.route('/operations/growth/add', methods=['POST'])
@admin_required
def add_growth_metric():
    m = GrowthMetric(week_start=datetime.fromisoformat(request.form.get('week_start')),
                     units_sold=int(request.form.get('units_sold') or 0),
                     revenue=_form_money('revenue', 0.0),
                     website_traffic=int(request.form.get('website_traffic') or 0),
                     events_booked=int(request.form.get('events_booked') or 0),
                     wholesale_inquiries=int(request.form.get('wholesale_inquiries') or 0),
                     social_reach=int(request.form.get('social_reach') or 0),
                     notes=request.form.get('notes'))
    db.session.add(m)
    db.session.commit()
    flash('Weekly metric added', 'success')
    return redirect(url_for('admin.growth'))


@admin_bp.route('/operations/growth/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_growth_metric(id):
    m = GrowthMetric.query.get_or_404(id)
    if request.method == 'POST':
        m.week_start = datetime.fromisoformat(request.form.get('week_start'))
        m.units_sold = int(request.form.get('units_sold') or 0)
        m.revenue = _form_money('revenue', 0.0)
        m.website_traffic = int(request.form.get('website_traffic') or 0)
        m.events_booked = int(request.form.get('events_booked') or 0)
        m.wholesale_inquiries = int(request.form.get('wholesale_inquiries') or 0)
        m.social_reach = int(request.form.get('social_reach') or 0)
        m.notes = request.form.get('notes') or None
        db.session.commit()
        flash('Weekly metric updated', 'success')
        return redirect(url_for('admin.growth'))
    return render_template('admin/operations/growth_edit.html', metric=m)



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
    # Repeat customers: users with 2+ orders
    repeat_query = db.session.query(User, func.count(Order.id).label('order_count')).join(
        Order, User.id == Order.user_id
    ).group_by(User.id).having(func.count(Order.id) >= 2).all()
    repeat_customers = [{'user': u, 'order_count': c} for u, c in repeat_query]
    # Collections (school/team/event)
    collections = Collection.query.filter_by(is_active=True).order_by(Collection.name).all()
    return render_template('admin/operations/customers.html',
                         repeat_customers=repeat_customers,
                         collections=collections)


# ===== MEDIA LIBRARY IMAGE IMPORT =====

@admin_bp.route('/products/import-media-library-images', methods=['POST'])
@admin_required
def import_media_library_images():
    """
    Receive flat image URLs extracted from the SanMar Media Library (Widen).
    Expects JSON body:
      { "images": [{"style": "BC3001", "color": "Black", "front_url": "...", "back_url": "..."}, ...] }
    Updates ProductColorVariant.front_image_url / back_image_url for matching records.
    Creates new variants if none exist for that style+color.
    """
    data = request.get_json(force=True, silent=True)
    if not data or 'images' not in data:
        return jsonify({'error': 'No images payload'}), 400

    images = data['images']  # list of {style, color, front_url, back_url}
    updated = created = skipped = 0

    for item in images:
        style = (item.get('style') or '').strip()
        color = (item.get('color') or '').strip()
        front_url = (item.get('front_url') or '').strip()
        back_url  = (item.get('back_url') or '').strip()

        if not style or not color or not (front_url or back_url):
            skipped += 1
            continue

        # Find product — try exact style_number, then with BC prefix
        product = Product.query.filter_by(style_number=style).first()
        if not product:
            alt = 'BC' + style if not style.upper().startswith('BC') else style[2:]
            product = Product.query.filter_by(style_number=alt).first()
        if not product:
            skipped += 1
            continue

        # Find variant by color name (case-insensitive)
        variant = ProductColorVariant.query.filter(
            ProductColorVariant.product_id == product.id,
            db.func.lower(ProductColorVariant.color_name) == color.lower()
        ).first()

        if variant:
            if front_url:
                variant.front_image_url = front_url
            if back_url:
                variant.back_image_url = back_url
            variant.last_synced = datetime.utcnow()
            updated += 1
        else:
            db.session.add(ProductColorVariant(
                product_id=product.id,
                color_name=color,
                front_image_url=front_url,
                back_image_url=back_url,
                last_synced=datetime.utcnow(),
            ))
            created += 1

        # Set front_mockup_template on product if blank
        if front_url and not product.front_mockup_template:
            product.front_mockup_template = front_url
        if back_url and not product.back_mockup_template:
            product.back_mockup_template = back_url

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'ok': True,
        'updated': updated,
        'created': created,
        'skipped': skipped,
        'total': len(images)
    })


@admin_bp.route('/products/apply-ml-cache', methods=['GET', 'POST'])
@admin_required
def apply_ml_cache():
    """
    Read services/ml_images_cache.json (populated by scripts/populate_ml_images.py)
    and apply all image URLs to the database.
    GET  → show status / trigger button
    POST → run the import
    """
    import re as _re
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'services', 'ml_images_cache.json'
    )

    if request.method == 'GET':
        exists = os.path.isfile(cache_path)
        size   = os.path.getsize(cache_path) if exists else 0
        return jsonify({
            'cache_exists': exists,
            'cache_size_kb': round(size / 1024, 1),
            'instruction': 'POST to this URL to apply the cache to the database.'
        })

    # POST — run the import
    if not os.path.isfile(cache_path):
        return jsonify({'error': 'Cache file not found. Run scripts/populate_ml_images.py first.'}), 404

    with open(cache_path) as f:
        all_images = json.load(f)

    ACCOUNT_ID = '47526418'
    EMBED_BASE = f'https://embed.widencdn.net/img/{ACCOUNT_ID}'

    updated = created = skipped = 0

    for style, colors in all_images.items():
        product = Product.query.filter_by(style_number=style).first()
        if not product:
            skipped += len(colors)
            continue

        first_front = first_back = None

        for color, sides in colors.items():
            # sides may be {"front": url, "back": url}  (from script)
            # or compact {"fu": uuid, "bu": uuid}        (legacy)
            front_url = sides.get('front', '')
            back_url  = sides.get('back', '')

            if not front_url and not back_url:
                skipped += 1
                continue

            variant = ProductColorVariant.query.filter(
                ProductColorVariant.product_id == product.id,
                db.func.lower(ProductColorVariant.color_name) == color.lower()
            ).first()

            if variant:
                if front_url: variant.front_image_url = front_url
                if back_url:  variant.back_image_url  = back_url
                variant.last_synced = datetime.utcnow()
                updated += 1
            else:
                db.session.add(ProductColorVariant(
                    product_id=product.id,
                    color_name=color,
                    front_image_url=front_url,
                    back_image_url=back_url,
                    last_synced=datetime.utcnow(),
                ))
                created += 1

            if not first_front and front_url: first_front = front_url
            if not first_back  and back_url:  first_back  = back_url

        if first_front and not product.front_mockup_template:
            product.front_mockup_template = first_front
        if first_back and not product.back_mockup_template:
            product.back_mockup_template = first_back

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'ok': True,
        'updated': updated,
        'created': created,
        'skipped': skipped,
        'styles_processed': len(all_images)
    })
