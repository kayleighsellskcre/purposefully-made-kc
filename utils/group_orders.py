"""Shared group-order helpers: deadline, session, product/design rules."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from flask import session
from models import Collection, Design, collection_products, db
from utils.json_fields import parse_json_list, parse_json_object

CHICAGO = ZoneInfo('America/Chicago')
UTC = ZoneInfo('UTC')

GROUP_KINDS = ('school', 'team', 'other')


def normalize_group_kind(value):
    kind = (value or '').strip().lower()
    return kind if kind in GROUP_KINDS else ''


def apply_collection_visibility(collection, form=None):
    """Public vs link-only. Link only is the default for new and existing stores."""
    from flask import request

    form = request.form if form is None else form
    vis = (form.get('visibility') or '').strip().lower().replace('-', '_')
    if vis == 'public':
        collection.show_in_directory = True
    elif vis in ('link_only', 'private'):
        collection.show_in_directory = False
    elif 'show_in_directory' in form:
        collection.show_in_directory = form.get('show_in_directory') == 'on'
    elif getattr(collection, 'show_in_directory', None) is None:
        collection.show_in_directory = False


def publicly_listed_collections():
    """Active stores the owner chose to show on public listings."""
    return Collection.query.filter_by(is_active=True, show_in_directory=True)


def apply_group_kind(collection, *, required=False):
    """Save school / team / other from the current form."""
    from flask import request

    kind = normalize_group_kind(request.form.get('group_kind'))
    if kind:
        collection.group_kind = kind
        return True, None
    if required:
        return False, 'Please choose whether this group order is for a school, a team, or something else.'
    return True, None


def collection_allows_send_home(collection):
    kind = normalize_group_kind(getattr(collection, 'group_kind', None))
    if not kind:
        # Older group orders had no type. Treat them like a team so checkout
        # still offers send-home, but without school-only grade.
        return True
    return kind in ('school', 'team')


def collection_asks_grade(collection):
    return normalize_group_kind(getattr(collection, 'group_kind', None)) == 'school'

# Brand-scoped color picks: form value "Port & Company||Navy" → JSON {"Port & Company": ["Navy"]}
ALLOWED_COLOR_SEP = '||'


def serialize_allowed_colors_from_form(raw_values):
    """Turn checkbox values into JSON for Collection.allowed_colors.

    Accepts brand-scoped "Brand||Color" values (preferred) or legacy bare color
    names. Returns None when nothing was selected.
    """
    import json
    from collections import defaultdict

    by_brand = defaultdict(list)
    legacy = []
    seen_brand = set()
    seen_legacy = set()
    for raw in raw_values or []:
        text = (raw or '').strip()
        if not text:
            continue
        if ALLOWED_COLOR_SEP in text:
            brand, color = text.split(ALLOWED_COLOR_SEP, 1)
            brand = brand.strip()
            color = color.strip()
            if not brand or not color:
                continue
            key = (brand, color)
            if key in seen_brand:
                continue
            seen_brand.add(key)
            by_brand[brand].append(color)
        else:
            if text in seen_legacy:
                continue
            seen_legacy.add(text)
            legacy.append(text)
    if by_brand:
        # Brand-scoped wins when any scoped value is present.
        return json.dumps(dict(by_brand), separators=(',', ':'))
    if legacy:
        return json.dumps(legacy, separators=(',', ':'))
    return None


def parse_allowed_colors_by_brand(raw):
    """Return {brand: [colors]} or {None: [colors]} for legacy flat lists.

    Empty dict means no color restriction was stored.
    """
    import json

    if raw is None or raw == '':
        return {}
    if isinstance(raw, dict):
        out = {}
        for brand, colors in raw.items():
            if isinstance(colors, (list, tuple)):
                cleaned = [str(c).strip() for c in colors if str(c).strip()]
            elif colors:
                cleaned = [str(colors).strip()]
            else:
                cleaned = []
            out[str(brand)] = cleaned
        return out
    text = str(raw).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {None: parse_json_list(text)}
    if isinstance(parsed, dict):
        return parse_allowed_colors_by_brand(parsed)
    if isinstance(parsed, list):
        from collections import defaultdict
        scoped = defaultdict(list)
        legacy = []
        has_scoped = False
        for item in parsed:
            s = str(item).strip()
            if not s:
                continue
            if ALLOWED_COLOR_SEP in s:
                has_scoped = True
                brand, color = s.split(ALLOWED_COLOR_SEP, 1)
                brand = brand.strip()
                color = color.strip()
                if brand and color and color not in scoped[brand]:
                    scoped[brand].append(color)
            else:
                if s not in legacy:
                    legacy.append(s)
        if has_scoped:
            return dict(scoped)
        return {None: legacy} if legacy else {}
    return {}


def collection_has_color_restrictions(collection):
    by_brand = parse_allowed_colors_by_brand(getattr(collection, 'allowed_colors', None))
    return any(bool(colors) for colors in by_brand.values())


def allowed_colors_for_product(product, collection_or_raw):
    """Color names allowed for this product, or None if unrestricted.

    Brand-scoped restrictions only apply to matching brands — picking Navy under
    Port & Company must not hide Bella+Canvas Navy (or force it).
    Legacy flat lists still apply to every product.
    """
    raw = collection_or_raw
    if collection_or_raw is not None and hasattr(collection_or_raw, 'allowed_colors'):
        raw = collection_or_raw.allowed_colors
    by_brand = parse_allowed_colors_by_brand(raw)
    if not by_brand:
        return None
    if None in by_brand and len(by_brand) == 1:
        colors = by_brand[None]
        return set(colors) if colors else None
    brand = (getattr(product, 'brand', None) or 'Other').strip() or 'Other'
    if brand not in by_brand:
        # Other brands were restricted; this brand was left alone → all its colors.
        return None
    return set(by_brand[brand])


def allowed_color_form_keys(collection_or_raw):
    """Checkbox values that should render checked: 'Brand||Color' and legacy bare names."""
    raw = collection_or_raw
    if collection_or_raw is not None and hasattr(collection_or_raw, 'allowed_colors'):
        raw = collection_or_raw.allowed_colors
    by_brand = parse_allowed_colors_by_brand(raw)
    from utils.color_names import display_color_name

    keys = set()
    for brand, colors in by_brand.items():
        names = list(colors)
        for color in colors:
            label = display_color_name(color)
            if label and label not in names:
                names.append(label)
        if brand is None:
            keys.update(names)
        else:
            for color in names:
                keys.add(f'{brand}{ALLOWED_COLOR_SEP}{color}')
                keys.add(color)
    return keys


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def team_store_config(collection):
    """Normalized two-lane config; legacy collections are fan-wear only."""
    import json

    raw = getattr(collection, 'team_store_config', None) if collection else None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    parsed = parsed if isinstance(parsed, dict) else {}
    uniform = parsed.get('uniform')
    uniform = uniform if isinstance(uniform, dict) else {}
    fan_ids = parsed.get('fan_product_ids')
    if not isinstance(fan_ids, list):
        fan_ids = []
        if collection is not None:
            fan_ids = [p.id for p in getattr(collection, 'products', [])]

    cleaned_fan = []
    for value in fan_ids:
        pid = _as_int(value)
        if pid and pid not in cleaned_fan:
            cleaned_fan.append(pid)
    uniform_pid = _as_int(uniform.get('product_id'))
    product_ids = []
    raw_ids = uniform.get('product_ids')
    if isinstance(raw_ids, list):
        for value in raw_ids:
            pid = _as_int(value)
            if pid and pid not in product_ids:
                product_ids.append(pid)
    if uniform_pid and uniform_pid not in product_ids:
        product_ids.insert(0, uniform_pid)
    enabled = bool(uniform.get('enabled') and product_ids)
    return {
        'version': 1,
        'configured': bool(parsed),
        'uniform': {
            'enabled': enabled,
            'product_id': product_ids[0] if enabled else None,
            'product_ids': product_ids if enabled else [],
            'home_color': (uniform.get('home_color') or '').strip(),
            'away_color': (uniform.get('away_color') or '').strip(),
            'home_design_id': _as_int(uniform.get('home_design_id')),
            'away_design_id': _as_int(uniform.get('away_design_id')),
        },
        'fan_product_ids': cleaned_fan,
        'fan_personalization_enabled': bool(
            parsed.get('fan_personalization_enabled', False)
        ),
    }


def visible_store_products(collection):
    """Products the group store actually offers, not every attached catalog row."""
    config = team_store_config(collection)
    attached = [p for p in (collection.products or []) if getattr(p, 'is_active', True)]
    by_id = {p.id: p for p in attached}
    if not config['configured']:
        return attached
    ids = []
    if config['uniform']['enabled']:
        ids.extend(config['uniform'].get('product_ids') or [])
        if config['uniform'].get('product_id'):
            ids.insert(0, config['uniform']['product_id'])
    ids.extend(config['fan_product_ids'] or [])
    seen = set()
    products = []
    for pid in ids:
        product = by_id.get(pid)
        if not product or pid in seen:
            continue
        seen.add(pid)
        products.append(product)
    return products


def visible_store_product_count(collection):
    from flask import has_app_context
    from utils.mockups import product_has_shop_image

    products = visible_store_products(collection)
    if has_app_context():
        from flask import current_app
        products = [p for p in products if product_has_shop_image(p, current_app)]
    return len(products)


def resolve_uniform_design_id(collection, kit='home'):
    """Jersey logo locked onto Home or Away, falling back to the first allowed design."""
    allowed = allowed_design_ids(collection)
    if not allowed:
        return None
    allowed_set = set(allowed)
    uniform = team_store_config(collection)['uniform']

    def _valid(raw):
        did = _as_int(raw)
        return did if did in allowed_set else None

    kit = (kit or 'home').strip().lower()
    if kit == 'away':
        return (
            _valid(uniform.get('away_design_id'))
            or _valid(uniform.get('home_design_id'))
            or allowed[0]
        )
    return _valid(uniform.get('home_design_id')) or allowed[0]


def load_design_dict(design_id):
    """Small {id, url, title} payload for a design, or None."""
    did = _as_int(design_id)
    if not did:
        return None
    design = Design.query.get(did)
    if not design:
        return None
    from utils.cloud_storage import image_url as resolve_image_url
    return {
        'id': design.id,
        'url': resolve_image_url(design.file_path),
        'title': (design.title or design.original_filename or 'Design'),
    }


def team_store_choice(collection, product_id, section=None, kit=None):
    """Validate/infer a product lane and return (section, kit, color, error)."""
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return None, None, None, 'That item is not part of this group order.'
    config = team_store_config(collection)
    uniform = config['uniform']
    section = (section or '').strip().lower()
    kit = (kit or '').strip().lower()

    if not config['configured']:
        return 'fan', None, None, None
    uniform_ids = set(uniform.get('product_ids') or [])
    if uniform.get('product_id'):
        uniform_ids.add(uniform['product_id'])
    if not section:
        section = (
            'uniform'
            if uniform['enabled'] and product_id in uniform_ids
            else 'fan'
        )
    if section == 'uniform':
        if not uniform['enabled'] or product_id not in uniform_ids:
            return None, None, None, 'That item is not offered as a player uniform.'
        if kit not in ('home', 'away'):
            return None, None, None, 'Choose the Home or Away uniform.'
        color = uniform[f'{kit}_color']
        if not color:
            return None, None, None, f'This group order does not offer an {kit.title()} uniform.'
        return 'uniform', kit, color, None
    if section != 'fan' or product_id not in config['fan_product_ids']:
        return None, None, None, 'That item is not offered in Family & Fan Wear.'
    return 'fan', None, None, None


def parse_order_deadline(date_str):
    """Inclusive end of the chosen calendar day in Kansas City time, stored as naive UTC."""
    raw = (date_str or '').strip()
    if not raw:
        return None
    day = datetime.strptime(raw[:10], '%Y-%m-%d').date()
    local_end = datetime.combine(day, time(23, 59, 59), tzinfo=CHICAGO)
    return local_end.astimezone(UTC).replace(tzinfo=None)


def parse_order_opens(date_str):
    """Start of the chosen calendar day in Kansas City time, stored as naive UTC."""
    raw = (date_str or '').strip()
    if not raw:
        return None
    day = datetime.strptime(raw[:10], '%Y-%m-%d').date()
    local_start = datetime.combine(day, time(0, 0, 0), tzinfo=CHICAGO)
    return local_start.astimezone(UTC).replace(tzinfo=None)


def _as_naive_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def schedule_date_input(dt):
    """YYYY-MM-DD for date inputs, in Kansas City time."""
    if not dt:
        return ''
    naive = _as_naive_utc(dt)
    if naive.hour == 0 and naive.minute == 0 and naive.second == 0:
        return naive.strftime('%Y-%m-%d')
    from utils.local_time import to_central
    local = to_central(dt)
    return local.strftime('%Y-%m-%d') if local else ''


def format_schedule_date(dt, fmt='%B %d, %Y'):
    if not dt:
        return ''
    naive = _as_naive_utc(dt)
    if naive.hour == 0 and naive.minute == 0 and naive.second == 0:
        return naive.strftime(fmt)
    from utils.local_time import format_central
    return format_central(dt, fmt)


def is_deadline_passed(collection):
    if not collection or not collection.order_deadline:
        return False
    deadline = _as_naive_utc(collection.order_deadline)
    # Date-only values used to be stored as midnight, which closed the order
    # at the start of the deadline day. Keep that calendar day open in KC.
    if deadline.hour == 0 and deadline.minute == 0 and deadline.second == 0:
        local_end = datetime.combine(deadline.date(), time(23, 59, 59), tzinfo=CHICAGO)
        deadline = local_end.astimezone(UTC).replace(tzinfo=None)
    return deadline < datetime.utcnow()


def is_not_yet_open(collection):
    if not collection or not getattr(collection, 'order_opens_at', None):
        return False
    opens = _as_naive_utc(collection.order_opens_at)
    return datetime.utcnow() < opens


def apply_schedule_from_form(collection):
    """Set order_opens_at and order_deadline from the current request.

    Returns (ok, error_message).
    """
    from flask import request

    opens_str = (request.form.get('order_opens_at') or '').strip()
    deadline_str = (request.form.get('order_deadline') or '').strip()
    try:
        opens = parse_order_opens(opens_str) if opens_str else None
    except ValueError:
        return False, 'The order start date is invalid. Please pick a valid date.'
    try:
        deadline = parse_order_deadline(deadline_str) if deadline_str else None
    except ValueError:
        return False, 'The order deadline date is invalid. Please pick a valid date.'
    if opens and deadline and opens > deadline:
        return False, 'The start date needs to be on or before the deadline.'
    collection.order_opens_at = opens
    collection.order_deadline = deadline
    return True, None


def set_collection_products_from_form(collection):
    """Save fan/uniform configuration and replace the union product relation.

    Returns ``(selected_products, error_message)``.
    """
    import json
    from flask import request
    from models import Product, ProductColorVariant

    fan_ids = []
    seen = set()
    for raw in request.form.getlist('products'):
        pid = _as_int(raw)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        fan_ids.append(pid)

    configured = request.form.get('team_store_present') == '1'
    uniform_enabled = configured and request.form.get('uniform_enabled') == 'on'
    uniform_ids = []
    home_color = ''
    away_color = ''
    home_design_id = None
    away_design_id = None
    if uniform_enabled:
        seen_uniform = set()
        for raw in request.form.getlist('uniform_product_ids'):
            pid = _as_int(raw)
            if pid and pid not in seen_uniform:
                seen_uniform.add(pid)
                uniform_ids.append(pid)
        if not uniform_ids:
            main_id = _as_int(request.form.get('uniform_product_id'))
            if main_id:
                uniform_ids.append(main_id)
        youth_id = _as_int(request.form.get('uniform_youth_product_id'))
        if youth_id and youth_id not in uniform_ids:
            uniform_ids.append(youth_id)
        if not uniform_ids:
            return [], 'Choose at least one apparel style for the player uniform.'
        home_color = (request.form.get('uniform_home_color') or '').strip()
        away_color = (request.form.get('uniform_away_color') or '').strip()
        if not home_color:
            return [], 'Choose a Home color for the player uniform.'
        if away_color and away_color == home_color:
            return [], 'Choose a different Away color, or leave Away blank.'
        color_rows = db.session.query(
            ProductColorVariant.product_id, ProductColorVariant.color_name
        ).filter(
            ProductColorVariant.product_id.in_(uniform_ids),
            ProductColorVariant.color_name.isnot(None),
        ).all()
        colors_by_product = {}
        for pid, color in color_rows:
            if not color:
                continue
            colors_by_product.setdefault(pid, set()).add(color)
        for pid in uniform_ids:
            valid_colors = colors_by_product.get(pid) or set()
            if home_color not in valid_colors:
                return [], 'The selected Home color is not available for every uniform style. Pick a color both youth and adult come in, or choose one style.'
            if away_color and away_color not in valid_colors:
                return [], 'The selected Away color is not available for every uniform style. Pick a color both youth and adult come in, or leave Away blank.'
        fan_ids = [pid for pid in fan_ids if pid not in seen_uniform and pid not in uniform_ids]
        allowed_logo_ids = set(allowed_design_ids(collection))
        for raw in request.form.getlist('allowed_designs'):
            did = _as_int(raw)
            if did:
                allowed_logo_ids.add(did)
        home_design_id = _as_int(request.form.get('uniform_home_design_id'))
        away_design_id = _as_int(request.form.get('uniform_away_design_id'))
        if home_design_id not in allowed_logo_ids:
            home_design_id = None
        if away_design_id not in allowed_logo_ids:
            away_design_id = None
        if away_design_id and away_design_id == home_design_id:
            away_design_id = None

    ids = list(fan_ids)
    for pid in reversed(uniform_ids):
        if pid not in ids:
            ids.insert(0, pid)
    if not ids:
        collection.products = []
        if configured:
            collection.team_store_config = json.dumps({
                'version': 1,
                'uniform': {'enabled': False},
                'fan_product_ids': [],
                'fan_personalization_enabled': False,
            })
        return [], None

    found = Product.query.filter(Product.id.in_(ids), Product.is_active == True).all()
    from utils.mockups import product_has_shop_image
    found = [p for p in found if product_has_shop_image(p)]
    by_id = {p.id: p for p in found}
    selected = [by_id[i] for i in ids if i in by_id]
    missing_uniform = [pid for pid in uniform_ids if pid not in by_id]
    if missing_uniform:
        return [], 'The selected uniform style is not currently available.'
    collection.products = selected
    if configured:
        primary = uniform_ids[0] if uniform_ids else None
        collection.team_store_config = json.dumps({
            'version': 1,
            'uniform': {
                'enabled': bool(primary),
                'product_id': primary,
                'product_ids': uniform_ids,
                'home_color': home_color,
                'away_color': away_color,
                'home_design_id': home_design_id,
                'away_design_id': away_design_id,
            },
            'fan_product_ids': [pid for pid in fan_ids if pid in by_id],
            'fan_personalization_enabled': (
                request.form.get('fan_personalization_enabled') == 'on'
            ),
        }, separators=(',', ':'))
    else:
        collection.team_store_config = None
    return selected, None


_COVER_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


def apply_collection_card(collection):
    """Save directory card title and optional cover photo from the request."""
    from pathlib import Path
    from flask import current_app, request
    from werkzeug.utils import secure_filename
    from utils.cloud_storage import upload_image

    title = (request.form.get('card_title') or '').strip()
    collection.card_title = title[:200] if title else None

    if request.form.get('remove_cover') == 'on':
        collection.cover_image = None

    cover = request.files.get('cover_image')
    if not cover or not cover.filename:
        return
    ext = Path(secure_filename(cover.filename)).suffix.lower()
    if ext not in _COVER_EXTS:
        return
    path = upload_image(
        cover, current_app,
        subfolder='group-covers',
        public_id_prefix='cover',
        process_artwork=False,
    )
    if path:
        collection.cover_image = path


def allowed_design_ids(collection):
    ids = []
    for raw in parse_json_list(getattr(collection, 'allowed_design_ids', None) or ''):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def showcase_design_ids(collection):
    """Design IDs chosen as hero logos at the top of the group-order page."""
    ids = []
    for raw in parse_json_list(getattr(collection, 'showcase_design_ids', None) or ''):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def load_showcase_designs(collection):
    """Ordered design dicts for the storefront logo strip (subset of allowed designs)."""
    allowed = set(allowed_design_ids(collection))
    ids = [i for i in showcase_design_ids(collection) if i in allowed]
    if not ids:
        return []
    designs = Design.query.filter(Design.id.in_(ids)).all()
    by_id = {d.id: d for d in designs}
    from utils.cloud_storage import image_url as resolve_image_url
    out = []
    for i in ids:
        d = by_id.get(i)
        if not d:
            continue
        out.append({
            'id': d.id,
            'url': resolve_image_url(d.file_path),
            'title': (d.title or d.original_filename or 'Design'),
        })
    return out


def resolve_showcase_design_ids(design_ids, form_showcase=None, new_upload_ids=None, showcase_new_uploads=False):
    """Build showcase ID list: form picks ∩ allowed, optionally plus new uploads."""
    allowed_set = set(design_ids or [])
    showcase_ids = []
    seen = set()
    for raw in form_showcase or []:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid in allowed_set and sid not in seen:
            showcase_ids.append(sid)
            seen.add(sid)
    if showcase_new_uploads:
        for sid in new_upload_ids or []:
            if sid in allowed_set and sid not in seen:
                showcase_ids.append(sid)
                seen.add(sid)
    return showcase_ids


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
    from flask import current_app, request
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
    ok, kind_error = apply_group_kind(collection, required=False)
    if not ok:
        return False, kind_error, 0
    apply_collection_card(collection)
    collection.pickup_address = request.form.get('pickup_address')
    collection.pickup_instructions = request.form.get('pickup_instructions')
    collection.shipping_enabled = request.form.get('shipping_enabled') == 'on'
    collection.allow_cash_pickup = request.form.get('allow_cash_pickup') == 'on'
    apply_collection_visibility(collection)
    # Tax is fixed at KS 9.5% — ignore any form value so it cannot be adjusted.
    collection.tax_rate = float(current_app.config['KS_SALES_TAX_PERCENT'])

    collection.is_active = request.form.get('is_active') == 'on'

    collection.restrict_options = True  # always restricted — checkbox removed from UI
    collection.allow_custom_upload = True
    allowed_colors_json = serialize_allowed_colors_from_form(request.form.getlist('allowed_colors'))
    collection.allowed_colors = allowed_colors_json
    allowed_colors = bool(allowed_colors_json)
    allowed_placements = request.form.getlist('allowed_placements')
    collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None

    keep_design_ids = allowed_design_ids(collection)
    design_ids = selectable_group_order_design_ids(
        request.form.getlist('allowed_designs'),
        user,
        keep_ids=keep_design_ids,
    )
    upload_count = 0
    new_upload_ids = []
    from routes.admin import _save_collection_design
    for f in request.files.getlist('design_uploads'):
        if f and f.filename:
            try:
                design = _save_collection_design(f, user.id)
            except Exception:
                design = None
            if design:
                design_ids.append(design.id)
                new_upload_ids.append(design.id)
                upload_count += 1
    collection.allowed_design_ids = json.dumps(design_ids) if design_ids else None
    if design_ids or allowed_colors:
        collection.restrict_options = True

    # Hero logos at the top of the storefront — must be in allowed_design_ids.
    showcase_ids = resolve_showcase_design_ids(
        design_ids,
        form_showcase=request.form.getlist('showcase_designs'),
        new_upload_ids=new_upload_ids,
        showcase_new_uploads=request.form.get('showcase_new_uploads') == 'on',
    )
    collection.showcase_design_ids = json.dumps(showcase_ids) if showcase_ids else None

    collection.back_design_font = request.form.get('back_design_font') or None
    # Create sends these; edit does not. Only overwrite when the form has them
    # so a successful admin save cannot blank the organizer's style lock.
    if 'back_design_text_color' in request.form:
        collection.back_design_text_color = request.form.get('back_design_text_color') or None
    if 'back_design_outline' in request.form:
        collection.back_design_outline = request.form.get('back_design_outline') != 'off'
    if 'back_design_outline_color' in request.form:
        collection.back_design_outline_color = request.form.get('back_design_outline_color') or None
    if (
        'back_style_controls_present' in request.form
        or 'lock_back_design_style' in request.form
    ):
        collection.lock_back_design_style = request.form.get('lock_back_design_style') == 'on'

    # Back design permissions
    bdt = request.form.get('back_design_type', 'both')
    if bdt == 'none':
        collection.allow_back_design = False
        collection.back_design_type  = 'both'   # stored default; irrelevant when disabled
    else:
        collection.allow_back_design = True
        collection.back_design_type  = bdt if bdt in ('name_number', 'image', 'both') else 'both'
        name_part = (request.form.get('back_design_name_part') or 'last').strip().lower()
        collection.back_design_name_part = name_part if name_part in ('first', 'last') else 'last'

    password = (request.form.get('password') or '').strip()
    if request.form.get('password_protected') == 'on':
        if password:
            collection.set_password(password)
    else:
        collection.is_password_protected = False
        collection.password_hash = None

    ok, error = apply_schedule_from_form(collection)
    if not ok:
        return False, error, 0

    selected_products, product_error = set_collection_products_from_form(collection)
    if product_error:
        return False, product_error, 0
    if require_products and not selected_products:
        return False, 'Please choose a uniform or at least one shirt style for fan wear.', 0

    return True, None, upload_count


def designs_for_group_order_form(collection, user=None):
    """Only artwork already assigned to this group order.

    Organizers upload store-specific artwork; the general design library is
    deliberately excluded from group-order setup.
    """
    from models import Design

    ids = allowed_design_ids(collection)
    if not ids:
        return []
    by_id = {
        design.id: design
        for design in Design.query.filter(Design.id.in_(ids)).all()
    }
    return [by_id[did] for did in ids if did in by_id]


def ordering_blocked(collection, product_id=None):
    """Human-readable reason this group order cannot accept this item, or None."""
    if not collection:
        return None
    if not collection.is_active:
        return 'This group order is no longer active.'
    if is_deadline_passed(collection):
        deadline = collection.order_deadline
        label = format_schedule_date(deadline) if deadline else 'the deadline'
        return f'This group order closed on {label}. Ordering is no longer available.'
    if is_not_yet_open(collection):
        label = format_schedule_date(collection.order_opens_at)
        return f'This group order opens on {label}. Ordering is not available yet.'
    if product_id and collection_has_products(collection) and not product_in_collection(collection, product_id):
        return 'That style is not part of this group order. Please pick from the styles on the group store.'
    return None
