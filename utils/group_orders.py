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
