"""Shared group-order helpers: deadline, session, product/design rules."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from flask import session
from models import Collection, Design, collection_products, db
from utils.json_fields import parse_json_list

CHICAGO = ZoneInfo('America/Chicago')
UTC = ZoneInfo('UTC')


def parse_order_deadline(date_str):
    """Inclusive end of the chosen calendar day in Kansas City time, stored as naive UTC."""
    raw = (date_str or '').strip()
    if not raw:
        return None
    day = datetime.strptime(raw[:10], '%Y-%m-%d').date()
    local_end = datetime.combine(day, time(23, 59, 59), tzinfo=CHICAGO)
    return local_end.astimezone(UTC).replace(tzinfo=None)


def is_deadline_passed(collection):
    if not collection or not collection.order_deadline:
        return False
    deadline = collection.order_deadline
    if deadline.tzinfo is not None:
        deadline = deadline.astimezone(UTC).replace(tzinfo=None)
    # Date-only values used to be stored as midnight, which closed the order
    # at the start of the deadline day. Keep that calendar day open in KC.
    if deadline.hour == 0 and deadline.minute == 0 and deadline.second == 0:
        local_end = datetime.combine(deadline.date(), time(23, 59, 59), tzinfo=CHICAGO)
        deadline = local_end.astimezone(UTC).replace(tzinfo=None)
    return deadline < datetime.utcnow()


def allowed_design_ids(collection):
    ids = []
    for raw in parse_json_list(getattr(collection, 'allowed_design_ids', None) or ''):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def product_in_collection(collection, product_id):
    if not collection or not product_id:
        return False
    row = (
        db.session.query(collection_products.c.product_id)
        .filter(
            collection_products.c.collection_id == collection.id,
            collection_products.c.product_id == int(product_id),
        )
        .first()
    )
    return row is not None


def collection_has_products(collection):
    if not collection:
        return False
    return db.session.query(collection_products.c.product_id).filter(
        collection_products.c.collection_id == collection.id
    ).first() is not None


def load_collection_designs(collection):
    """Designs the team can pick, including private uploads (not just the public gallery)."""
    ids = allowed_design_ids(collection)
    if not ids:
        return []
    designs = Design.query.filter(Design.id.in_(ids)).all()
    by_id = {d.id: d for d in designs}
    ordered = [by_id[i] for i in ids if i in by_id]
    from utils.cloud_storage import image_url as resolve_image_url
    return [
        {
            'id': d.id,
            'url': resolve_image_url(d.file_path),
            'title': (d.title or d.original_filename or 'Design'),
        }
        for d in ordered
    ]


def design_allowed_for_collection(design, collection):
    if not design:
        return False
    if getattr(design, 'is_gallery', False):
        ids = allowed_design_ids(collection)
        if not ids:
            return True
        return design.id in ids
    return design.id in allowed_design_ids(collection)


def session_collection_id():
    try:
        cid = session.get('collection_id')
        return int(cid) if cid is not None else None
    except (TypeError, ValueError):
        return None


def collection_id_from_cart(cart):
    for item in cart or []:
        if not isinstance(item, dict):
            continue
        try:
            cid = item.get('collection_id')
            if cid is not None:
                return int(cid)
        except (TypeError, ValueError):
            continue
    return session_collection_id()


def get_active_collection(cart=None):
    cid = collection_id_from_cart(cart) if cart is not None else session_collection_id()
    if not cid:
        return None
    collection = Collection.query.get(cid)
    if not collection or not collection.is_active:
        session.pop('collection_id', None)
        return None
    return collection


def attach_collection(collection):
    if collection and collection.is_active and not is_deadline_passed(collection):
        session['collection_id'] = collection.id
        session.modified = True
        return True
    session.pop('collection_id', None)
    session.modified = True
    return False


def leave_group_order():
    session.pop('collection_id', None)
    session.modified = True


def user_can_manage_collection(collection, user=None):
    """True if this user created the group order or is a site admin."""
    from flask_login import current_user
    user = current_user if user is None else user
    if not collection or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_admin', False):
        return True
    return collection.created_by_user_id == user.id


def apply_collection_form(collection, user, *, allow_slug=False, require_products=True):
    """Save create/edit group-order fields from the current request.

    Returns (ok, error_message, upload_count). On failure the caller should
    rollback; this function does not commit.
    """
    from flask import request
    from models import Product
    from utils.privacy import selectable_group_order_design_ids
    import json

    name = (request.form.get('name') or '').strip()
    if not name:
        return False, 'Please enter a name for your group order.', 0
    collection.name = name

    if allow_slug:
        new_slug = (request.form.get('slug') or '').strip()
        if new_slug:
            existing = Collection.query.filter_by(slug=new_slug).first()
            if existing and existing.id != collection.id:
                return False, f'URL slug "{new_slug}" is already used by another group order.', 0
            collection.slug = new_slug

    collection.description = request.form.get('description')
    collection.pickup_address = request.form.get('pickup_address')
    collection.pickup_instructions = request.form.get('pickup_instructions')
    collection.shipping_enabled = request.form.get('shipping_enabled') == 'on'
    try:
        collection.tax_rate = float(request.form.get('tax_rate') or 0)
    except (TypeError, ValueError):
        collection.tax_rate = 0.0

    collection.is_active = request.form.get('is_active') == 'on'

    collection.restrict_options = request.form.get('restrict_options') == 'on'
    collection.allow_custom_upload = True
    allowed_colors = request.form.getlist('allowed_colors')
    collection.allowed_colors = json.dumps(allowed_colors) if allowed_colors else None
    allowed_placements = request.form.getlist('allowed_placements')
    collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None

    keep_design_ids = allowed_design_ids(collection)
    design_ids = selectable_group_order_design_ids(
        request.form.getlist('allowed_designs'),
        user,
        keep_ids=keep_design_ids,
    )
    upload_count = 0
    from routes.admin import _save_collection_design
    for f in request.files.getlist('design_uploads'):
        if f and f.filename:
            try:
                design = _save_collection_design(f, user.id)
            except Exception:
                design = None
            if design:
                design_ids.append(design.id)
                upload_count += 1
    collection.allowed_design_ids = json.dumps(design_ids) if design_ids else None
    if design_ids or allowed_colors:
        collection.restrict_options = True

    collection.back_design_font = request.form.get('back_design_font') or None
    collection.back_design_text_color = request.form.get('back_design_text_color') or None
    collection.back_design_outline = request.form.get('back_design_outline') != 'off'
    collection.back_design_outline_color = request.form.get('back_design_outline_color') or None
    collection.lock_back_design_style = request.form.get('lock_back_design_style') == 'on'

    password = (request.form.get('password') or '').strip()
    if request.form.get('password_protected') == 'on':
        if password:
            collection.set_password(password)
    else:
        collection.is_password_protected = False
        collection.password_hash = None

    deadline_str = (request.form.get('order_deadline') or '').strip()
    if deadline_str:
        try:
            collection.order_deadline = parse_order_deadline(deadline_str)
        except ValueError:
            return False, 'The order deadline date is invalid. Please pick a valid date.', 0
    else:
        collection.order_deadline = None

    selected_products = []
    collection.products = []
    for product_id in request.form.getlist('products'):
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            continue
        product = Product.query.get(pid)
        if product:
            selected_products.append(product)
            collection.products.append(product)
    if require_products and not selected_products:
        return False, 'Please pick at least one shirt style so your team has something to order.', 0

    return True, None, upload_count


def designs_for_group_order_form(collection, user=None):
    """Gallery designs plus logos already on this store (and the organizer's uploads)."""
    from flask_login import current_user
    from models import Design

    user = current_user if user is None else user
    gallery = Design.query.filter_by(is_gallery=True).order_by(Design.uploaded_at.desc()).all()
    by_id = {d.id: d for d in gallery}
    for did in allowed_design_ids(collection):
        if did not in by_id:
            d = Design.query.get(did)
            if d:
                by_id[d.id] = d
    if user is not None and getattr(user, 'is_authenticated', False):
        own = Design.query.filter(
            Design.uploaded_by_user_id == user.id,
            Design.is_gallery == False,
        ).order_by(Design.uploaded_at.desc()).limit(40).all()
        for d in own:
            by_id.setdefault(d.id, d)
    return list(by_id.values())


def ordering_blocked(collection, product_id=None):
    """Human-readable reason this group order cannot accept this item, or None."""
    if not collection:
        return None
    if not collection.is_active:
        return 'This group order is no longer active.'
    if is_deadline_passed(collection):
        deadline = collection.order_deadline
        label = deadline.strftime('%B %d, %Y') if deadline else 'the deadline'
        return f'This group order closed on {label}. Ordering is no longer available.'
    if product_id and collection_has_products(collection) and not product_in_collection(collection, product_id):
        return 'That style is not part of this group order. Please pick from the styles on the group store.'
    return None
