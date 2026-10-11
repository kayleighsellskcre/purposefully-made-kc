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
    if getattr(collection, 'payment_mode', None) == 'organizer_pays':
        # One bulk order placed by the organizer; nothing goes home per child.
        return False
    kind = normalize_group_kind(getattr(collection, 'group_kind', None))
    if not kind:
        # Older group orders had no type. Treat them like a team so checkout
        # still offers send-home, but without school-only grade.
        return True
    return kind in ('school', 'team')


def collection_asks_grade(collection):
    return normalize_group_kind(getattr(collection, 'group_kind', None)) == 'school'


def _pickup_text(collection):
    if not collection:
        return '', ''
    instructions = (getattr(collection, 'pickup_instructions', None) or '').strip()
    address = (getattr(collection, 'pickup_address', None) or '').strip()
    return instructions, address


def group_has_custom_pickup(collection):
    instructions, address = _pickup_text(collection)
    return bool(instructions or address)


def group_uses_organizer_fulfillment(collection):
    """True when this store is not promising PMKC shop pickup."""
    if not collection:
        return False
    if group_has_custom_pickup(collection):
        return True
    return not bool(getattr(collection, 'shipping_enabled', True))


def _as_sentence(text):
    text = (text or '').strip()
    if text and text[-1] not in '.!?':
        text += '.'
    return text


def group_fulfillment_customer_note(collection=None):
    """Line under Add to Cart / product price. Always includes the 2-3 week wait."""
    wait = 'Please allow 2 to 3 weeks.'
    if not collection:
        return f'Shipping is $11. Pickup is available at checkout. {wait}'
    shipping = bool(getattr(collection, 'shipping_enabled', True))
    instructions, address = _pickup_text(collection)
    bits = []
    if shipping:
        bits.append('Shipping is $11.')
    if instructions:
        bits.append(_as_sentence(instructions))
    elif address:
        bits.append(_as_sentence(f'Pickup is at {address}'))
    elif shipping:
        bits.append('Pickup is available at checkout.')
    else:
        bits.append('Your organizer will have this order.')
    bits.append(wait)
    return ' '.join(bits)


def group_pickup_heading(collection=None):
    if group_uses_organizer_fulfillment(collection):
        return "We'll get this to your group"
    return 'Local Pickup'


def group_pickup_details(collection=None):
    """Body lines under the checkout pickup option."""
    instructions, address = _pickup_text(collection)
    lines = []
    if address:
        lines.append(address)
    if instructions:
        lines.append(instructions)
    if lines:
        return lines
    if group_uses_organizer_fulfillment(collection):
        return ['Your organizer will have this order.']
    return ['Free - Pick up at our location']


def group_pickup_next_step(collection=None):
    if group_uses_organizer_fulfillment(collection):
        return "We'll get this to your group when it's ready."
    return "We'll contact you when it's ready for pickup!"


def group_shipping_offered(collection=None, family_promo_active=False):
    if family_promo_active:
        return False
    if collection and not getattr(collection, 'shipping_enabled', True):
        return False
    return True


# Color picks are scoped per shirt: form value "p:12||Navy" → JSON {"p:12": ["Navy"]}.
# Older stores were scoped per brand: "Port & Company||Navy" → {"Port & Company": ["Navy"]}.
ALLOWED_COLOR_SEP = '||'
PRODUCT_COLOR_PREFIX = 'p:'


def product_color_key(product_id):
    return f'{PRODUCT_COLOR_PREFIX}{product_id}'


def serialize_allowed_colors_from_form(raw_values):
    """Turn checkbox values into JSON for Collection.allowed_colors.

    Accepts per-shirt "p:<id>||Color" values (what the form sends now),
    brand-scoped "Brand||Color" values, or legacy bare color names. Returns
    None when nothing was selected.
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
    product_key = product_color_key(getattr(product, 'id', None))
    if product_key in by_brand:
        return set(by_brand[product_key]) or None
    if any(str(key).startswith(PRODUCT_COLOR_PREFIX) for key in by_brand):
        # Picks were saved per shirt and this shirt was left alone → all its colors.
        return None
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


def fan_color_checked_keys(collection, products, colors_by_product):
    """'p:<id>||Color' values to pre-check in the per-shirt color picker.

    Works for stores saved per shirt, per brand, or as a flat list, so an older
    store opens with the same colors picked and saves per shirt from then on.
    """
    if collection is None or not collection_has_color_restrictions(collection):
        return []
    from utils.color_names import color_in_allowed_set

    checked = []
    for product in products or []:
        allowed = allowed_colors_for_product(product, collection)
        if allowed is None:
            continue
        key = product_color_key(product.id)
        for label in colors_by_product.get(str(product.id)) or []:
            if color_in_allowed_set(label, allowed):
                checked.append(f'{key}{ALLOWED_COLOR_SEP}{label}')
    return checked


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
    # Optional: which uniform styles carry each kit. Lets a team use one
    # jersey style for Home and a different one for Away. Empty means every
    # uniform style offers that kit (the original behavior).
    kit_product_ids = {}
    for kit in ('home', 'away'):
        raw_kit_ids = uniform.get(f'{kit}_product_ids')
        cleaned = []
        if isinstance(raw_kit_ids, list):
            for value in raw_kit_ids:
                pid = _as_int(value)
                if pid and pid in product_ids and pid not in cleaned:
                    cleaned.append(pid)
        kit_product_ids[kit] = cleaned if enabled else []
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
            'home_product_ids': kit_product_ids['home'],
            'away_product_ids': kit_product_ids['away'],
        },
        'fan_product_ids': cleaned_fan,
        'fan_personalization_enabled': bool(
            parsed.get('fan_personalization_enabled', False)
        ),
        # True = jersey logo appears as an option on fan wear customizer (default).
        # Set to False in team_store_config JSON to hide the jersey logo from fans.
        'fan_show_jersey_logo': bool(
            parsed.get('fan_show_jersey_logo', True)
        ),
    }


def uniform_kit_offered(uniform, product_id, kit):
    """True when this uniform style is sold in this kit (home/away)."""
    if not uniform.get(f'{kit}_color'):
        return False
    limited = uniform.get(f'{kit}_product_ids') or []
    return not limited or product_id in limited


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


def _size_span(sizes):
    sizes = [s for s in sizes or [] if s]
    if len(sizes) > 2:
        return f'{sizes[0]}\u2013{sizes[-1]}'
    return ', '.join(sizes)


def _carousel_color_set(product):
    return {
        (v.get('color_name') or '').strip().lower()
        for v in getattr(product, 'carousel_colors', None) or []
        if (v.get('color_name') or '').strip()
    }


def describe_age_family(members):
    """Card facts for one style shown in several ages (members[0] leads)."""
    from utils.product_filters import _age_of, age_label

    lead = members[0]
    lead_colors = _carousel_color_set(lead)
    member_colors = [_carousel_color_set(m) for m in members]
    shared = set.intersection(*member_colors) if member_colors else set()
    prices = [
        getattr(m, 'listed_price', None) if getattr(m, 'listed_price', None) is not None
        else (m.base_price or 0)
        for m in members
    ]
    return {
        'labels': ' + '.join(age_label(m) for m in members),
        'ages': ' '.join(_age_of(m) for m in members),
        'sizes': ' \u00b7 '.join(
            span for span in (_size_span(getattr(m, 'available_sizes_list', None)) for m in members) if span
        ),
        'price_from': min(prices) if prices else 0,
        'price_varies': len({round(p, 2) for p in prices}) > 1,
        'colors_match': bool(lead_colors) and all(lead_colors <= colors for colors in member_colors[1:]),
        'shared_colors': len(shared),
    }


def build_store_cards(products):
    """Return each product as its own card — adult and youth are shown separately
    so shoppers can clearly see and choose what they are ordering.

    Returns (cards, matching_note). matching_note is always None here since we
    no longer fold age groups together.
    """
    for product in products:
        product.age_family = None
    return products, None


def store_age_family(collection, product):
    """Other ages of this style offered in the store's fan wear, adult first."""
    from utils.product_filters import age_families

    config = team_store_config(collection)
    products = visible_store_products(collection)
    if config['configured']:
        fan_ids = set(config['fan_product_ids'] or [])
        products = [p for p in products if p.id in fan_ids]
    if product.id not in {p.id for p in products}:
        return []
    for members in age_families(products):
        if any(m.id == product.id for m in members):
            return members if len(members) > 1 else []
    return []


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
        if not uniform_kit_offered(uniform, product_id, kit):
            return None, None, None, f'That style is not the {kit.title()} uniform for this team.'
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
    # Multi-team wizard with a different jersey per team: the per-team cards
    # carry the jerseys (utils/group_org.py), not the single uniform fields.
    per_team_org = (
        request.form.get('org_action') == 'new'
        and request.form.get('org_style_mode') == 'different'
    )
    uniform_enabled = (
        configured and not per_team_org
        and request.form.get('uniform_enabled') == 'on'
    )
    uniform_ids = []
    home_ids = []
    away_ids = []
    home_color = ''
    away_color = ''
    home_design_id = None
    away_design_id = None
    if uniform_enabled:
        for raw in request.form.getlist('uniform_product_ids'):
            pid = _as_int(raw)
            if pid and pid not in home_ids:
                home_ids.append(pid)
        if not home_ids:
            main_id = _as_int(request.form.get('uniform_product_id'))
            if main_id:
                home_ids.append(main_id)
        youth_id = _as_int(request.form.get('uniform_youth_product_id'))
        if youth_id and youth_id not in home_ids:
            home_ids.append(youth_id)
        if not home_ids:
            return [], 'Choose at least one apparel style for the player uniform.'
        home_color = (request.form.get('uniform_home_color') or '').strip()
        away_color = (request.form.get('uniform_away_color') or '').strip()
        if not home_color:
            return [], 'Choose a Home color for the player uniform.'
        away_main = _as_int(request.form.get('uniform_away_product_id'))
        away_youth = _as_int(request.form.get('uniform_away_youth_product_id'))
        if away_color:
            if away_main or away_youth:
                away_ids = [pid for pid in (away_main or home_ids[0], away_youth or youth_id) if pid]
                away_ids = list(dict.fromkeys(away_ids))
            else:
                away_ids = list(home_ids)
            if away_color == home_color and away_ids == home_ids:
                return [], 'Choose a different Away color, or leave Away blank.'
        uniform_ids = list(dict.fromkeys(home_ids + away_ids))
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
        for pid in home_ids:
            if home_color not in (colors_by_product.get(pid) or set()):
                return [], 'The selected Home color is not available for every Home uniform style. Pick a color both youth and adult come in, or choose one style.'
        for pid in away_ids:
            if away_color not in (colors_by_product.get(pid) or set()):
                return [], 'The selected Away color is not available for every Away uniform style. Pick a color both youth and adult come in, or leave Away blank.'
        fan_ids = [pid for pid in fan_ids if pid not in uniform_ids]
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

    # Per-team org mode: the first team's jersey lives on this (main) store so
    # the "choose a uniform or fan wear" check passes; utils/group_org.py then
    # writes the full per-team setup (colors, away jersey, logos) for every team.
    elif configured and per_team_org:
        team_pids = request.form.getlist('org_team_uniform_product_id[]')
        team_youth_pids = request.form.getlist('org_team_youth_product_id[]')
        for raw in (team_pids[:1] + team_youth_pids[:1]):
            pid = _as_int(raw)
            if pid and pid not in uniform_ids:
                uniform_ids.append(pid)
        home_ids = list(uniform_ids)
        if uniform_ids:
            team_home_colors = request.form.getlist('org_team_home_color[]')
            home_color = team_home_colors[0].strip() if team_home_colors else ''
        fan_ids = [pid for pid in fan_ids if pid not in uniform_ids]

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
                'home_product_ids': home_ids,
                'away_product_ids': away_ids,
            },
            'fan_product_ids': [pid for pid in fan_ids if pid in by_id],
            'fan_personalization_enabled': (
                request.form.get('fan_personalization_enabled') == 'on'
            ),
            # True = jersey logo appears as a design choice on fan wear (default on).
            # Coaches can uncheck to hide it so fans see only other uploaded designs.
            'fan_show_jersey_logo': (
                request.form.get('fan_show_jersey_logo') == 'on'
                if 'fan_show_jersey_logo' in request.form
                else True
            ),
            # Design IDs the admin wants EXCLUDED from the sibling Fan Wear store.
            # Each checked "Jersey only" box sends this design's ID in the form.
            'fanwear_excluded_ids': [
                int(x) for x in request.form.getlist('fanwear_excluded_ids')
                if str(x).strip().isdigit()
            ],
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


def fanwear_excluded_ids(collection):
    """Design IDs the admin marked as jersey-only (excluded from Fan Wear) for this collection."""
    raw = getattr(collection, 'team_store_config', None) or ''
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except (TypeError, ValueError, AttributeError):
        parsed = {}
    excluded = parsed.get('fanwear_excluded_ids') or []
    result = []
    for x in excluded:
        try:
            result.append(int(x))
        except (TypeError, ValueError):
            continue
    return result


def org_fanwear_design_ids(fan_collection):
    """Return merged allowed_design_ids for a Fan Wear collection in an org.

    Pulls allowed_design_ids from every non-fan sibling collection in the same
    org, strips designs the admin flagged jersey-only on that sibling, then
    appends the Fan Wear collection's own allowed_design_ids at the end.
    De-duped, preserving order.
    """
    try:
        from models import OrgSection
        section = OrgSection.query.filter_by(collection_id=fan_collection.id).first()
        if not section or 'fan' not in (section.label or '').lower():
            return allowed_design_ids(fan_collection)
        org = section.organization
        if not org:
            return allowed_design_ids(fan_collection)
        seen = set()
        merged = []
        for sib in org.sections.all():
            if sib.id == section.id:
                continue
            if 'fan' in (sib.label or '').lower():
                continue
            sibling_coll = sib.collection
            if not sibling_coll or not sibling_coll.is_active:
                continue
            excluded = set(fanwear_excluded_ids(sibling_coll))
            for did in allowed_design_ids(sibling_coll):
                if did not in seen and did not in excluded:
                    seen.add(did)
                    merged.append(did)
        # Fan Wear collection's own designs come last
        for did in allowed_design_ids(fan_collection):
            if did not in seen:
                seen.add(did)
                merged.append(did)
        return merged
    except Exception:
        return allowed_design_ids(fan_collection)


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


def _normalize_person_name(value):
    return ' '.join((value or '').split()).lower()


def find_organizer_account(raw):
    """Match an account by email or full name.

    Returns (user, pending_email, error). An email with no account becomes a
    pending claim so they get the store when they register or sign in. A
    first name alone is refused: it could hand the store, and its order list,
    to the wrong customer.
    """
    from models import User

    text = ' '.join((raw or '').split())
    if not text:
        return None, None, None

    if '@' in text:
        email = text.lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user:
            return user, None, None
        return None, email, None

    needle = _normalize_person_name(text)
    if ' ' not in needle:
        return None, None, (
            f'Please use their full name or email so we pass {text} the right store.'
        )
    users = User.query.filter(
        User.first_name.isnot(None), User.last_name.isnot(None)
    ).all()
    matches = [
        u for u in users
        if _normalize_person_name(f'{u.first_name} {u.last_name}') == needle
    ]
    if len(matches) == 1:
        return matches[0], None, None
    if len(matches) > 1:
        return None, None, 'More than one account matches that name. Use their email instead.'
    return None, None, (
        f'We could not find an account for {text}. '
        'Use their email instead, and the store will be waiting when they register.'
    )


def assign_collection_organizer(collection, raw):
    """Move this store to an organizer account, or hold it for their email."""
    user, pending, error = find_organizer_account(raw)
    if error:
        return False, error, None
    if user:
        if collection.created_by_user_id == user.id and not collection.pending_organizer_email:
            return True, None, None
        collection.created_by_user_id = user.id
        collection.pending_organizer_email = None
        name = f'{user.first_name or ""} {user.last_name or ""}'.strip()
        label = f'{name} ({user.email})' if name else user.email
        return True, None, (
            f'This store now belongs to {label}. '
            'They can finish it from My Group Orders.'
        )
    if pending:
        if collection.pending_organizer_email == pending:
            return True, None, None
        collection.pending_organizer_email = pending
        return True, None, (
            f'We will move this store to {pending} when they sign in or create an account.'
        )
    return True, None, None


def apply_organizer_from_form(collection, user=None):
    """Admin-only organizer field. Empty leaves the current owner in place."""
    from flask import request
    from flask_login import current_user

    user = current_user if user is None else user
    if not getattr(user, 'is_admin', False):
        return True, None, None
    if 'organizer' not in request.form:
        return True, None, None
    raw = (request.form.get('organizer') or '').strip()
    if not raw:
        return True, None, None
    return assign_collection_organizer(collection, raw)


def claim_pending_group_orders(user):
    """Give this user any stores waiting on their email. Does not commit."""
    email = (getattr(user, 'email', None) or '').strip().lower()
    if not email:
        return []
    rows = Collection.query.filter(
        db.func.lower(Collection.pending_organizer_email) == email
    ).all()
    for collection in rows:
        collection.created_by_user_id = user.id
        collection.pending_organizer_email = None
    return rows


def apply_locked_back_design(collection, user=None):
    """Store organizer artwork that prints only on the back.

    The id is kept off allowed_design_ids so shoppers cannot place it on the
    front. Instant /design/upload posts set a hidden back_design_id; a file
    input is the fallback when JavaScript does not run.
    """
    import json
    from flask import request

    if request.form.get('clear_back_design') == 'on':
        collection.back_design_id = None
        return None

    raw = (request.form.get('back_design_id') or '').strip()
    if raw:
        try:
            did = int(raw)
        except (TypeError, ValueError):
            did = None
        if did:
            design = Design.query.get(did)
            if design:
                collection.back_design_id = did

    f = request.files.get('back_design_upload') if request.files else None
    if f and getattr(f, 'filename', None):
        from routes.admin import _save_collection_design
        uid = getattr(user, 'id', None)
        try:
            design = _save_collection_design(f, uid)
        except Exception:
            design = None
        if design:
            collection.back_design_id = design.id

    locked_id = getattr(collection, 'back_design_id', None)
    if not locked_id:
        return None
    ids = allowed_design_ids(collection)
    if locked_id in ids:
        ids = [i for i in ids if i != locked_id]
        collection.allowed_design_ids = json.dumps(ids) if ids else None
    return locked_id


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
    from utils.group_roster import apply_payment_mode_from_form, roster_item_error
    ok, payment_error = apply_payment_mode_from_form(collection)
    if not ok:
        return False, payment_error, 0
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

    apply_locked_back_design(collection, user)

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
    roster_error = roster_item_error(collection)
    if roster_error:
        return False, roster_error, 0

    ok, organizer_error, organizer_notice = apply_organizer_from_form(collection, user)
    if not ok:
        return False, organizer_error, 0
    if organizer_notice:
        from flask import flash
        flash(organizer_notice, 'success')

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
    from utils.group_roster import is_organizer_pays
    if is_organizer_pays(collection):
        # The link only collects sizes. Only the organizer (or admin) checks
        # out, once, for the whole roster, and that can happen after the
        # deadline closes the size form.
        if not user_can_manage_collection(collection):
            return ('This group order is paid for by the organizer. '
                    'Use the group link to send your size instead.')
        return None
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
