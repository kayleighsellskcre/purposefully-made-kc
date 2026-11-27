from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from functools import wraps
from models import db, Product, Order, Design, User, CustomDesignRequest, SiteError
from werkzeug.utils import secure_filename
from datetime import datetime
import json
import os
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
        from utils.design_metadata import clean_filename_title, color_label_from_metadata, is_generic_title, unique_variant_label

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
    pass
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
from routes import admin_orders  # noqa: E402,F401   (order list and detail, status, artwork previews, exports)
from routes.admin_orders import (  # noqa: E402,F401  (used by the production sheets and by tests)
    _collect_order_productions, _collect_press_shirts, _sort_press_shirts, _transfer_csv_response, preview_item_artwork,
)
from routes import admin_production  # noqa: E402,F401   (production sheets, receipts and packing slips, invoices, labels)
from routes import admin_designs  # noqa: E402,F401   (design library, review, organize, matches, tags, categories)
from routes import admin_collections  # noqa: E402,F401   (group stores: products, designs, sections, settings)
from routes import admin_products  # noqa: E402,F401   (product list, add and edit, colors, images, sync)
from routes.admin_designs import _admin_designs_url  # noqa: E402,F401  (used by the old gallery address)
from routes.admin_design_requests import _delete_design_file, _send_design_request_decision_email  # noqa: E402,F401  (also used by other admin sections and routes/org.py)
from routes import admin_tools  # noqa: E402,F401   (search box, emails that did not send)
from routes import admin_backroom  # noqa: E402,F401
from routes import admin_artwork_pack  # noqa: E402,F401
# School district setup, QR codes and reports.
from routes import admin_districts  # noqa: E402,F401
# Kansas Sales Tax: deadlines, the portal's three parts, filing record and reminders.
from routes import admin_kansas_tax  # noqa: E402,F401
# Design proof approval: send a proof, the list of proofs out, approve for the customer.
from routes import admin_proofs  # noqa: E402,F401
