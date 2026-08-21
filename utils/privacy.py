"""Account isolation helpers.

Customers can only see their own profile, orders, addresses, and private
designs. Public gallery art is admin-approved. Group-order logos are visible
only on that team's share link after the organizer (or admin) attached them.
"""
from flask import session
from flask_login import current_user


def is_admin_user(user=None):
    user = _user(user)
    return bool(
        user is not None
        and getattr(user, 'is_authenticated', False)
        and getattr(user, 'is_admin', False)
    )


def user_can_view_order(order, user=None, sess=None):
    """Thank-you page / receipt access. Never leak another customer's order."""
    if not order:
        return False
    user = _user(user)
    sess = session if sess is None else sess
    if user is not None and getattr(user, 'is_authenticated', False):
        if getattr(user, 'is_admin', False):
            return True
        return bool(order.user_id) and order.user_id == user.id
    return sess.get('checkout_success_order') == order.order_number


def user_can_use_design(design, user=None, collection=None):
    """True when this shopper may print this design on a shirt."""
    if not design:
        return False
    user = _user(user)
    if is_admin_user(user):
        return True
    if collection is not None:
        from utils.group_orders import allowed_design_ids, design_allowed_for_collection
        if design_allowed_for_collection(design, collection):
            return True
        ids = allowed_design_ids(collection)
        locked = bool(
            getattr(collection, 'restrict_options', False)
            and ids
            and not getattr(collection, 'allow_custom_upload', True)
        )
        if locked:
            return False
    if getattr(design, 'is_gallery', False):
        return True
    if user is not None and getattr(user, 'is_authenticated', False):
        return design.uploaded_by_user_id == user.id
    return False


def selectable_group_order_design_ids(raw_ids, user=None, keep_ids=None):
    """Drop another customer's private artwork from a group-order form post.

    Allowed: public gallery, the current user's own uploads, designs already
    on this collection, and anything an admin attaches.
    """
    from models import Design

    user = _user(user)
    keep = set(keep_ids or [])

    # Parse all IDs first (deduplicated, in order)
    parsed = []
    seen = set()
    for did in raw_ids or []:
        try:
            did = int(did)
        except (TypeError, ValueError):
            continue
        if did not in seen:
            seen.add(did)
            parsed.append(did)

    # IDs already on the collection are always kept — no DB lookup needed
    keep_only = [did for did in parsed if did in keep]
    need_lookup = [did for did in parsed if did not in keep]

    out = list(keep_only)

    if not need_lookup:
        return out

    # Single bulk query instead of one query per ID
    designs_by_id = {
        d.id: d
        for d in Design.query.filter(Design.id.in_(need_lookup)).all()
    }

    admin = is_admin_user(user)
    user_id = getattr(user, 'id', None) if (user and getattr(user, 'is_authenticated', False)) else None

    for did in need_lookup:
        design = designs_by_id.get(did)
        if not design:
            continue
        if getattr(design, 'is_gallery', False) or admin:
            out.append(did)
        elif user_id and design.uploaded_by_user_id == user_id:
            out.append(did)

    return out


def _user(user):
    return current_user if user is None else user
