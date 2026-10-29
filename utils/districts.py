"""School district stores: District > Level > School > Stores.

A district is a ``District`` row. Each school is an ``Organization`` (so the existing
deadline reminders, autopilot emails, My Group Orders and org pages work for it with
no changes) and each store is a ``Collection`` linked to the school by an ``OrgSection``.
Every school gets a "School Spirit" store automatically; sports and activities are added
after it, and an optional Staff store goes last.

Short links (``/desoto/mill-valley/volleyball``) and QR codes are built from the
``short_slug`` columns, which are set once when a row is created and never edited,
so printed flyers keep working after a rename.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta

from slugify import slugify

from models import (Collection, District, Order, OrderItem, Organization, OrgSection, Product,
                    ProductColorVariant, db)

LEVELS = [('high', 'High Schools'), ('middle', 'Middle Schools'), ('elementary', 'Elementary Schools')]
LEVEL_ONE = {'high': 'High School', 'middle': 'Middle School', 'elementary': 'Elementary School'}
LEVEL_KEYS = [k for k, _ in LEVELS]

# What a school's stores can be. School Spirit is always first; the rest are grouped in this order on the school page.
STORE_KINDS = [
    ('sport', 'Sports', 'Sport'),
    ('activity', 'Activities and clubs', 'Activity or club'),
    ('event', 'Events', 'Event'),
    ('family', 'Classes and family', 'Class or family'),
    ('teacher', 'Teachers and classrooms', 'Teacher or classroom'),
    ('staff', 'Staff', 'Staff'),
]
KIND_KEYS = [k for k, _h, _l in STORE_KINDS]
KIND_HEADING = {k: h for k, h, _l in STORE_KINDS}
KIND_LABEL = {k: l for k, _h, l in STORE_KINDS}
_ACTIVITY_WORDS = ('band', 'choir', 'orchestra', 'drama', 'theater', 'theatre', 'musical', 'chess', 'robotics', 'yearbook',
                   'newspaper', 'council', 'club', 'debate', 'forensics', 'honor', 'fbla', 'fccla', 'art', 'color guard',
                   'science', 'quiz', 'scholars', 'student')
_EVENT_WORDS = ('festival', 'carnival', 'field day', 'dance', 'fun run', 'walk', 'night', 'fundraiser', 'picnic',
                'graduation', 'homecoming', 'prom', 'spirit week', 'reunion', 'field trip', 'camp')
_FAMILY_WORDS = ('senior', 'family', 'families', 'alumni', 'class of', 'parent', 'grandparent', 'booster', 'supporter', 'fan wear')
_TEACHER_WORDS = ('mr.', 'mrs.', 'ms.', 'miss ', 'dr.', 'class', 'classroom', 'grade', 'teacher')
KIND_PREFIXES = {'sport': 'sport', 'sports': 'sport', 'activity': 'activity', 'club': 'activity', 'activities': 'activity',
                 'event': 'event', 'events': 'event', 'family': 'family', 'families': 'family', 'teacher': 'teacher',
                 'class': 'teacher', 'classroom': 'teacher',
                 'staff': 'staff'}

SPIRIT_LABEL = 'School Spirit'
STAFF_LABEL = 'Staff'
SPIRIT_TAGLINE = 'Wear it for anything.'

# Words that are dropped when a short link piece is made from a name
_SHORT_DROP = {'usd', 'isd', 'school', 'schools', 'district', 'unified', 'public', 'high', 'middle',
               'elementary', 'hs', 'ms', 'es', 'the', 'of', 'r', 'sd', 'cusd'}

# First path pieces that the site already uses (a district short link may not take them)
_RESERVED = {'admin', 'org', 'c', 'shop', 'cart', 'checkout', 'account', 'auth', 'login', 'logout', 'api',
             'static', 'uploads', 'about', 'contact', 'faq', 'privacy', 'terms', 'reviews', 'review',
             'size-guide', 'status', 'sitemap.xml', 'robots.txt', 'design', 'favorites', 'pay', 'sponsored',
             'custom-request', 'custom', 'register', 'signup', 'group-orders', 'invoice', 'share', 'qr',
             'flyer', 'manage', 'new', 'favicon.ico'}


# ── names, slugs and links ────────────────────────────────────────────────────────────────

def _short_from(name, fallback):
    words = [w for w in slugify(name or '').split('-') if w and not w.isdigit() and w not in _SHORT_DROP]
    return '-'.join(words[:3]) or slugify(name or '') or fallback


def school_nickname(school):
    """"Mill Valley High" -> "Mill Valley": the name used on store names and flyers."""
    words = [w for w in re.split(r'\s+', (school.name or '').strip()) if w]
    while len(words) > 1 and words[-1].lower().strip('.') in {'high', 'middle', 'elementary', 'school', 'hs', 'ms', 'es'}:
        words.pop()
    return ' '.join(words)


def reserved_words():
    from flask import current_app
    found = set(_RESERVED)
    try:
        for rule in current_app.url_map.iter_rules():
            first = rule.rule.strip('/').split('/')[0]
            if first and not first.startswith('<'):
                found.add(first.lower())
    except Exception:
        pass
    return found


def _unique(base, taken):
    base = base or 'item'
    candidate, n = base, 2
    while candidate in taken:
        candidate = f'{base}-{n}'
        n += 1
    return candidate


def new_district_short(name):
    taken = reserved_words() | {d.short_slug for d in District.query.all()}
    return _unique(_short_from(name, 'district'), taken)


def new_district_slug(name):
    taken = {d.slug for d in District.query.all()} | {o.slug for o in Organization.query.all()}
    return _unique(slugify(name) or 'district', taken)


def _school_slug_taken(district):
    return {s.school_slug for s in district.schools.all() if s.school_slug}


def new_school_short(district, name):
    taken = {s.short_slug for s in district.schools.all() if s.short_slug}
    return _unique(_short_from(name, 'school'), taken)


def new_store_short(school, label):
    taken = {c.short_slug for c in stores_of(school, include_inactive=True) if c.short_slug}
    return _unique(slugify(label) or 'store', taken)


def short_path(obj, school=None):
    """Permanent short path: /desoto, /desoto/mill-valley or /desoto/mill-valley/volleyball."""
    if isinstance(obj, District):
        return f'/{obj.short_slug}'
    if isinstance(obj, Organization):
        return f'/{obj.district.short_slug}/{obj.short_slug}'
    school = school or school_for_store(obj)
    if school is None or not obj.short_slug:        # a store outside any district: its ordinary store link
        return f'/c/{obj.slug}'
    return f'{short_path(school)}/{obj.short_slug}'


def base_url():
    from flask import current_app
    from utils.mailer import admin_base_url
    return admin_base_url(current_app._get_current_object())


def short_url(obj, school=None):
    return base_url() + short_path(obj, school)


def short_display(obj, school=None):
    """The link written out without https://, as printed on a flyer."""
    return short_url(obj, school).split('://', 1)[-1]


def district_url(d):
    return f'/org/{d.slug}'


def school_url(s):
    return f'/org/{s.district.slug}/{s.school_slug}'


# ── structure ─────────────────────────────────────────────────────────────────────────────

def school_for_store(store):
    sec = OrgSection.query.filter_by(collection_id=store.id).first()
    org = sec.organization if sec else None
    return org if org is not None and org.district_id else None


def stores_of(school, include_inactive=False):
    """The school's stores in display order (School Spirit first, Staff last)."""
    out = []
    for sec in school.sections.order_by(OrgSection.sort_order, OrgSection.id).all():
        if sec.collection and (include_inactive or sec.collection.is_active):
            sec.collection._label = sec.label
            out.append(sec.collection)
    return out


def is_live(store):
    """A store parents can see: switched on and holding at least one product."""
    return bool(store.is_active and store.products)


def live_stores(school):
    return [s for s in stores_of(school) if is_live(s)]


def store_label(store):
    sec = OrgSection.query.filter_by(collection_id=store.id).first()
    return (sec.label if sec else None) or store.name


def spirit_store(school):
    return next((s for s in stores_of(school, include_inactive=True) if s.store_kind == 'spirit'), None)


def schools_by_level(district, public=True):
    """[(level key, heading, [schools])] with empty levels left out.

    For visitors a school with nothing live is hidden. The owner (public=False) sees every school.
    """
    out = []
    for key, heading in LEVELS:
        schools = [s for s in district.schools.all() if s.is_active and s.level == key]
        if public:
            schools = [s for s in schools if live_stores(s)]
        if schools:
            out.append((key, heading, schools))
    return out


def school_deadline(school, stores=None):
    """The date shown on a school card: the soonest upcoming store deadline, else the school's or district's window."""
    now = datetime.utcnow()
    dates = [real_deadline(s.order_deadline) for s in (stores if stores is not None else live_stores(school))]
    dates = [d for d in dates if d]
    upcoming = sorted(d for d in dates if d >= now)
    if upcoming:
        return upcoming[0]
    return real_deadline(school.order_deadline) or real_deadline(school.district.order_deadline) or (max(dates) if dates else None)


def level_heading(school):
    return dict(LEVELS).get(school.level, 'Schools')


def _first_color(value, default):
    value = (value or '').strip()
    return value if re.fullmatch(r'#[0-9a-fA-F]{3,8}', value) else default


def accent(school):
    return _first_color(school.primary_color, '#B87C6F')


def accent2(school):
    return _first_color(school.secondary_color, '#E8D0B1')


# ── creating things ───────────────────────────────────────────────────────────────────────

class DistrictError(ValueError):
    """A message the admin can read as it is."""


def _parse_dt(value):
    if isinstance(value, (datetime, type(None))):
        return value
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], '%Y-%m-%d').replace(hour=23, minute=59)
    except ValueError:
        raise DistrictError('Dates look like 2026-11-15.')


def create_district(name, *, description=None, logo_url=None, opens=None, deadline=None):
    name = (name or '').strip()
    if not name:
        raise DistrictError('Give the district a name.')
    d = District(name=name[:200], slug=new_district_slug(name), short_slug=new_district_short(name),
                 description=(description or '').strip() or None, logo_url=logo_url or None,
                 order_opens_at=_parse_dt(opens), order_deadline=_parse_dt(deadline), is_active=True)
    db.session.add(d)
    db.session.flush()
    return d


SCHOOL_FIELDS = ('mascot', 'primary_color', 'secondary_color', 'organizer_name', 'delivery_mode')


def apply_school_settings(school, data):
    """Copy the school settings from a form or dict. Never touches slugs."""
    for key in SCHOOL_FIELDS:
        if key in data:
            setattr(school, key, (data.get(key) or '').strip() or None)
    if school.delivery_mode not in (None, 'send_home', 'pickup'):
        school.delivery_mode = 'send_home'
    if 'organizer_email' in data:
        school.pending_organizer_email = (data.get('organizer_email') or '').strip()[:120] or None
    if 'order_deadline' in data:
        school.order_deadline = _parse_dt(data.get('order_deadline'))
    if 'fundraiser' in data:
        raw = (data.get('fundraiser') or '').strip().lstrip('$')
        try:
            school.fundraiser_cents = max(0, int(round(float(raw) * 100))) if raw else 0
        except ValueError:
            raise DistrictError('The fundraiser amount per item is a number like 2 or 2.50.')
    if 'description' in data:
        school.description = (data.get('description') or '').strip() or None
    if data.get('logo_url'):
        school.logo_url = data.get('logo_url')


def add_school(district, name, level, **settings):
    name = (name or '').strip()
    if not name:
        raise DistrictError('Give the school a name.')
    if level not in LEVEL_KEYS:
        raise DistrictError('Choose High, Middle or Elementary.')
    school_slug = _unique(slugify(name) or 'school', _school_slug_taken(district))
    taken_global = {o.slug for o in Organization.query.all()} | {d.slug for d in District.query.all()}
    org_slug = school_slug if school_slug not in taken_global else _unique(f'{district.short_slug}-{school_slug}', taken_global)
    school = Organization(name=name[:200], slug=org_slug, district_id=district.id, level=level,
                          school_slug=school_slug, short_slug=new_school_short(district, name),
                          delivery_mode='send_home', is_active=True,
                          sort_order=district.schools.count())
    apply_school_settings(school, settings)
    db.session.add(school)
    db.session.flush()
    ensure_spirit(school)
    return school


def _store_from_school(school, label, kind, slug_hint):
    """A fresh store that starts from the school's delivery, deadline and organizer settings."""
    nick = school_nickname(school)
    if kind in ('teacher', 'event') and nick.lower() not in label.lower():
        name = f'{label} at {nick}'.strip()          # "Mrs. Johnson's Class at Riverview", "Fall Festival at Riverview"
    else:
        name = f'{nick} {label}'.strip()
    base = slugify(f'{school.district.short_slug}-{nick}-{label}') or 'school-store'
    slug = _unique(base, {c.slug for c in Collection.query.filter(Collection.slug.like(f'{base}%')).all()})
    sends_home = (school.delivery_mode or 'send_home') == 'send_home'
    store = Collection(
        name=name[:200], slug=slug, is_active=True, group_kind='school' if sends_home else 'other',
        store_kind=kind, short_slug=new_store_short(school, slug_hint or label),
        order_opens_at=school.district.order_opens_at,
        order_deadline=school.order_deadline or school.district.order_deadline,
        pending_organizer_email=school.pending_organizer_email,
        show_in_directory=False, payment_mode='each_pays',
        shipping_enabled=not sends_home,
        pickup_instructions=None if sends_home else 'Pickup at the school.',
    )
    db.session.add(store)
    db.session.flush()
    store.products = district_styles(school.district)        # styles come from the district
    _follow_school_colors(store, school)                     # colors come from the school
    _apply_school_logos(store, [], school_logo_id_list(school))   # main logos come from the school
    return store


def _next_sort(school, kind):
    secs = school.sections.all()
    if kind == 'spirit':
        return -1
    if kind == 'staff':
        return 10_000
    return max([s.sort_order or 0 for s in secs if (s.sort_order or 0) < 10_000] + [0]) + 1


def ensure_spirit(school):
    existing = spirit_store(school)
    if existing:
        return existing
    store = _store_from_school(school, SPIRIT_LABEL, 'spirit', 'school-spirit')
    db.session.add(OrgSection(organization_id=school.id, collection_id=store.id, label=SPIRIT_LABEL,
                              icon='✨', sort_order=-1))
    db.session.flush()
    return store


def guess_kind(label):
    """A sensible type for a store name, so most lines need no label: Football is a sport, Band an activity."""
    text = (label or '').strip().lower()
    if text == STAFF_LABEL.lower():
        return 'staff'
    if any(w in text for w in _FAMILY_WORDS):
        return 'family'
    if any(w in text for w in _TEACHER_WORDS):
        return 'teacher'
    if any(w in text for w in _EVENT_WORDS):
        return 'event'
    from utils.group_org import sport_icon
    if sport_icon(label) != DEFAULT_ICON and not any(w in text for w in ('band', 'choir')):
        return 'sport'
    if any(w in text for w in _ACTIVITY_WORDS):
        return 'activity'
    return 'sport'


def parse_store_entry(entry):
    """'teacher:Mrs. Johnson' gives ('teacher', 'Mrs. Johnson'); a bare name gets a guessed type."""
    entry = (entry or '').strip()
    if ':' in entry:
        head, _sep, rest = entry.partition(':')
        kind = KIND_PREFIXES.get(head.strip().lower())
        if kind and rest.strip():
            return kind, rest.strip()
    return guess_kind(entry), entry


DEFAULT_ICON = '\U0001F3F7\ufe0f'
_KIND_ICON = {'teacher': '\U0001F34E', 'event': '\U0001F389', 'activity': '\U0001F3AD', 'family': '\u2764\ufe0f', 'staff': DEFAULT_ICON}


def add_store(school, label, *, kind=None):
    label = (label or '').strip()
    if not label:
        raise DistrictError('Give the store a name, like Volleyball.')
    kind = kind if kind in KIND_KEYS else guess_kind(label)
    if label.lower() in (SPIRIT_LABEL.lower(), 'spirit'):
        raise DistrictError('School Spirit is already there. It is added for every school.')
    if label.lower() in {store_label(s).lower() for s in stores_of(school, include_inactive=True)}:
        raise DistrictError(f'{school.name} already has a {label} store.')
    store = _store_from_school(school, label, kind, label)
    from utils.group_org import sport_icon
    icon = _KIND_ICON.get(kind) or sport_icon(label)
    if kind == 'activity' and icon == DEFAULT_ICON:
        icon = _KIND_ICON['activity']
    db.session.add(OrgSection(organization_id=school.id, collection_id=store.id, label=label[:100],
                              icon=icon, sort_order=_next_sort(school, kind)))
    db.session.flush()
    return store


def effective_kind(store):
    """The group a store is shown in. A store still filed under Sports whose name says Seniors or Family is shown with the classes."""
    kind = store.store_kind or 'sport'
    if kind in ('sport', 'teacher') and any(w in store_label(store).lower() for w in _FAMILY_WORDS):
        return 'family'
    return kind


def real_deadline(value):
    """A deadline worth showing: one that is set and not a far-off placeholder (over 13 months away)."""
    if not value:
        return None
    return value if value <= datetime.utcnow() + timedelta(days=400) else None


def store_sections(stores):
    """[(kind, heading, [stores])] in page order, leaving out types with nothing in them. School Spirit is not in here."""
    out = []
    for kind, heading, _label in STORE_KINDS:
        group = [st for st in stores if effective_kind(st) == kind]
        if group:
            out.append((kind, heading, group))
    return out


def set_up_district(name, schools, *, description=None, opens=None, deadline=None, logo_url=None):
    """One screen to a whole district. ``schools`` is [(school name, level, [store names], settings)]."""
    d = create_district(name, description=description, logo_url=logo_url, opens=opens, deadline=deadline)
    for school_name, level, store_names, settings in schools:
        school = add_school(d, school_name, level, **(settings or {}))
        for entry in store_names:
            kind, label = parse_store_entry(entry)
            if label and label.lower() not in (SPIRIT_LABEL.lower(), 'spirit'):
                add_store(school, label, kind=kind)
    return d


def push_deadline(school_or_district, deadline, opens=None):
    """Apply a window to every store under a school or district (a button, never automatic)."""
    deadline, opens = _parse_dt(deadline), _parse_dt(opens)
    schools = [school_or_district] if isinstance(school_or_district, Organization) else school_or_district.schools.all()
    n = 0
    for school in schools:
        if isinstance(school_or_district, Organization):
            school.order_deadline = deadline
        for store in stores_of(school, include_inactive=True):
            store.order_deadline = deadline
            if opens:
                store.order_opens_at = opens
            store.deadline_reminder_sent_at = store.progress_sent_at = store.two_day_sent_at = None
            n += 1
    return n


def sync_school_delivery(school):
    """Make every store follow the school's delivery choice (send home with the child, or pickup)."""
    sends_home = (school.delivery_mode or 'send_home') == 'send_home'
    for store in stores_of(school, include_inactive=True):
        store.group_kind = 'school' if sends_home else 'other'
        store.shipping_enabled = not sends_home
        if not sends_home and not store.pickup_instructions:
            store.pickup_instructions = 'Pickup at the school.'


# ── styles (district) and shirt colors (school, with a store override) ────────────────────

def _ids(raw):
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [int(i) for i in value if str(i).isdigit()] if isinstance(value, list) else []


def district_style_ids(district):
    return _ids(district.style_ids)


def district_styles(district):
    ids = district_style_ids(district)
    if not ids:
        return []
    by_id = {p.id: p for p in Product.query.filter(Product.id.in_(ids), Product.is_active.is_(True)).all()}
    return [by_id[i] for i in ids if i in by_id]


def set_district_styles(district, product_ids):
    """Choose the district's styles. Stores that were using the old list (or had none) switch to the new one.

    A store whose styles someone changed by hand is left alone. Returns how many stores were updated.
    """
    old = set(district_style_ids(district))
    ids = []
    for raw in product_ids:
        if str(raw).isdigit() and int(raw) not in ids:
            ids.append(int(raw))
    district.style_ids = json.dumps(ids) if ids else None
    new_products = district_styles(district)
    updated = 0
    for school in district.schools.all():
        for store in stores_of(school, include_inactive=True):
            current = {p.id for p in store.products}
            if not current or current == old:
                store.products = list(new_products)
                updated += 1
    return updated


def school_color_names(school):
    try:
        value = json.loads(school.garment_colors) if school.garment_colors else []
    except (TypeError, ValueError):
        return []
    return [str(c) for c in value] if isinstance(value, list) else []


def _color_json(names):
    return json.dumps(list(names)) if names else None


def _follow_school_colors(store, school):
    store.colors_custom = False
    store.allowed_colors = _color_json(school_color_names(school))
    store.restrict_options = True


def school_logo_id_list(school):
    return _ids(school.school_logo_ids) if school is not None else []


def school_logos(school):
    """The school's main logos as [{id, url, title}], in the order they were added."""
    from models import Design
    from utils.cloud_storage import image_url
    ids = school_logo_id_list(school)
    if not ids:
        return []
    by_id = {d.id: d for d in Design.query.filter(Design.id.in_(ids)).all()}
    return [{'id': i, 'url': image_url(by_id[i].file_path), 'title': by_id[i].title or by_id[i].original_filename or 'Logo'}
            for i in ids if i in by_id]


def _apply_school_logos(store, old_ids, new_ids):
    """Swap the school's old main logos for its new ones in a store, keeping the store's own extra logos."""
    old = set(old_ids)
    allowed = [i for i in _ids(store.allowed_design_ids) if i not in old]
    allowed = list(dict.fromkeys(list(new_ids) + allowed))
    show = [i for i in _ids(store.showcase_design_ids) if i not in old]
    show = list(dict.fromkeys(list(new_ids)[:4] + show))
    store.allowed_design_ids = json.dumps(allowed) if allowed else None
    store.showcase_design_ids = json.dumps(show) if show else None


def set_school_logos(school, design_ids):
    """Choose the school's main logos. Every store of the school offers them, next to its own extras."""
    old = school_logo_id_list(school)
    new = list(dict.fromkeys(int(i) for i in design_ids if str(i).isdigit()))
    school.school_logo_ids = json.dumps(new) if new else None
    n = 0
    for store in stores_of(school, include_inactive=True):
        _apply_school_logos(store, old, new)
        n += 1
    return n


def move_logo_to_store(school, design_id, store):
    """Take a logo off the school's main logos (so every other store stops offering it) and keep it in one store."""
    design_id = int(design_id)
    main = school_logo_id_list(school)
    if design_id not in main:
        raise DistrictError('That logo is not one of the main logos.')
    set_school_logos(school, [i for i in main if i != design_id])
    from utils.group_designs import attach
    attach(store, [design_id], show_at_top=True)


def available_colors(district):
    """Colors the district's styles come in: [{name, label, hex, swatch}], by name.

    A color a style does not come in is simply not offered for that style (the store page already hides it).
    """
    from utils.color_names import display_color_name
    ids = district_style_ids(district)
    if not ids:
        return []
    found = {}
    rows = ProductColorVariant.query.filter(ProductColorVariant.product_id.in_(ids)).order_by(ProductColorVariant.id).all()
    for row in rows:
        name = (row.color_name or '').strip()
        label = display_color_name(name) if name else None
        if not name or not label:
            continue
        entry = found.setdefault(name, {'name': name, 'label': label, 'hex': None, 'swatch': None, 'styles': 0})
        entry['hex'] = entry['hex'] or row.color_hex
        entry['swatch'] = entry['swatch'] or row.color_swatch_url
        entry['styles'] += 1
    return sorted(found.values(), key=lambda c: c['label'].lower())


def set_school_colors(school, names):
    """Choose a school's colors. Every store that has not picked its own follows."""
    keep = {c['name'] for c in available_colors(school.district)}
    names = [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip()) if n in keep]
    school.garment_colors = _color_json(names)
    n = 0
    for store in stores_of(school, include_inactive=True):
        if not store.colors_custom:
            _follow_school_colors(store, school)
            n += 1
    return n


def set_store_colors(store, names):
    """One store picks its own colors (for example Cheer adds Pink)."""
    school = school_for_store(store)
    keep = {c['name'] for c in available_colors(school.district)} if school else None
    names = [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip()) if keep is None or n in keep]
    store.allowed_colors = _color_json(names)
    store.restrict_options = True
    store.colors_custom = bool(names)
    if not names and school:
        _follow_school_colors(store, school)


def reset_store_colors(store):
    """"Go back to school colors"."""
    school = school_for_store(store)
    if school:
        _follow_school_colors(store, school)


def colors_source(store, school=None):
    """Where a store's colors come from, in words: 'from Mill Valley High (3)' or 'custom for this store (4)'."""
    school = school or school_for_store(store)
    if store.colors_custom:
        from utils.group_orders import parse_allowed_colors_by_brand
        n = sum(len(v) for v in parse_allowed_colors_by_brand(store.allowed_colors).values())
        return f'custom for this store ({n})'
    n = len(school_color_names(school)) if school else 0
    return f'from {school.name} ({n})' if n else f'from {school.name} (all colors, none chosen yet)'


# ── copy a store's styles and settings to other schools ───────────────────────────────────

_NOT_COPIED = {'allowed_design_ids', 'showcase_design_ids', 'allowed_colors', 'colors_custom', 'id', 'name', 'slug', 'share_token', 'created_at', 'updated_at', 'card_title', 'expected_count',
               'deadline_reminder_sent_at', 'progress_sent_at', 'two_day_sent_at', 'closed_summary_sent_at',
               'order_opens_at', 'order_deadline', 'short_slug', 'store_kind', 'pending_organizer_email',
               'created_by_user_id', 'description', 'cover_image', 'group_kind', 'shipping_enabled',
               'pickup_address', 'pickup_instructions', 'is_active'}


def copy_store_to_schools(source, school_ids):
    """Give each chosen school the same store (same label) with this store's products, colors and rules.

    A school that has no store with that name gets one. Names, links, deadlines, delivery and the
    organizer stay the school's own. Returns (created, updated).
    """
    label = store_label(source)
    kind = source.store_kind or 'sport'
    created = updated = 0
    for school in Organization.query.filter(Organization.id.in_(school_ids or [])).all():
        if not school.district_id:
            continue
        target = next((s for s in stores_of(school, include_inactive=True)
                       if store_label(s).lower() == label.lower()), None)
        if target is source:
            continue
        if target is None:
            target = add_store(school, label, kind=kind) if kind != 'spirit' else ensure_spirit(school)
            created += 1
        else:
            updated += 1
        for col in Collection.__table__.columns:
            if col.name not in _NOT_COPIED:
                setattr(target, col.name, getattr(source, col.name))
        target.products = list(source.products)       # the styles travel with the store...
        _follow_school_colors(target, school)         # ...the colors are the new school's own
        source_school = school_for_store(source)      # ...and so are the main logos; the store's own extra logos travel
        own = [i for i in _ids(source.allowed_design_ids) if i not in set(school_logo_id_list(source_school))]
        own_show = [i for i in _ids(source.showcase_design_ids) if i in own]
        mine = school_logo_id_list(school)
        target.allowed_design_ids = json.dumps(list(dict.fromkeys(mine + own))) if (mine or own) else None
        target.showcase_design_ids = json.dumps(list(dict.fromkeys(mine[:4] + own_show))) if (mine or own_show) else None
    db.session.flush()
    return created, updated


# ── filters for blanks, press sheets, labels ──────────────────────────────────────────────

def scope_options():
    """[(token, label)] for the order filters: districts, levels, schools."""
    out = []
    for d in District.query.order_by(District.name).all():
        out.append((f'd:{d.id}', f'All of {d.name}'))
        for key, heading in LEVELS:
            if any(s.level == key for s in d.schools.all()):
                out.append((f'l:{d.id}:{key}', f'{d.name}: {heading}'))
        for s in d.schools.all():
            out.append((f's:{s.id}', f'{d.name}: {s.name}'))
    return out


def collection_ids_for_scope(token):
    """Store ids for 'd:3' (district), 'l:3:high' (level), 's:7' (school); None when not a scope token."""
    token = str(token or '')
    if ':' not in token:
        return None
    parts = token.split(':')
    schools = []
    try:
        if parts[0] == 'd':
            schools = Organization.query.filter_by(district_id=int(parts[1])).all()
        elif parts[0] == 'l':
            schools = Organization.query.filter_by(district_id=int(parts[1]), level=parts[2]).all()
        elif parts[0] == 's':
            schools = Organization.query.filter_by(id=int(parts[1])).all()
        else:
            return None
    except (ValueError, IndexError):
        return []
    return [s.id for school in schools for s in stores_of(school, include_inactive=True)]


# ── reports ───────────────────────────────────────────────────────────────────────────────

def _store_numbers(store):
    from utils.group_orders import orders_for_collection
    orders = orders_for_collection(store.id).filter(Order.payment_status == 'paid',
                                                    db.or_(Order.is_refunded.is_(None), Order.is_refunded.is_(False))).all()
    items = revenue = 0
    for order in orders:
        for item in order.items:
            owner = item.collection_id if item.collection_id is not None else order.collection_id
            if owner == store.id:
                items += item.quantity or 0
                revenue += item.subtotal or 0
    return len(orders), items, round(revenue, 2)


def school_report(school):
    rows, orders, items, revenue = [], 0, 0, 0.0
    for store in stores_of(school, include_inactive=True):
        o, i, r = _store_numbers(store)
        rows.append({'store': store, 'label': store_label(store), 'orders': o, 'items': i, 'revenue': r})
        orders += o
        items += i
        revenue += r
    owed = (school.fundraiser_cents or 0) * items
    paid = school.fundraiser_paid_cents or 0
    return {'school': school, 'rows': rows, 'orders': orders, 'items': items, 'revenue': round(revenue, 2),
            'owed_cents': owed, 'paid_cents': paid, 'balance_cents': max(0, owed - paid)}


def district_report(district):
    schools = [school_report(s) for s in district.schools.all()]
    return {'district': district, 'schools': schools,
            'orders': sum(s['orders'] for s in schools), 'items': sum(s['items'] for s in schools),
            'revenue': round(sum(s['revenue'] for s in schools), 2),
            'owed_cents': sum(s['owed_cents'] for s in schools),
            'balance_cents': sum(s['balance_cents'] for s in schools)}


def blanks_total(district):
    """{(product name, color, size): quantity} across every school, for bulk blank buying."""
    ids = collection_ids_for_scope(f'd:{district.id}') or []
    totals = {}
    if not ids:
        return totals
    from utils.group_orders import filter_orders_to_collection
    orders = filter_orders_to_collection(Order.query.filter(Order.payment_status == 'paid'), f'd:{district.id}').all()
    for order in orders:
        for item in order.items:
            owner = item.collection_id if item.collection_id is not None else order.collection_id
            if owner in ids:
                key = (item.product_name or item.style_number or 'Item', item.color or '', item.size or '')
                totals[key] = totals.get(key, 0) + (item.quantity or 0)
    return totals


# ── tax exemption for the school itself ───────────────────────────────────────────────────

def school_exempt(school, today=None):
    if school is None or not school.tax_exempt:
        return False
    today = today or date.today()
    return not (school.tax_expires_on and school.tax_expires_on < today)


def store_exempt_when_school_pays(store):
    """True only when the school itself pays (the organizer places one bulk order) and its certificate is good.

    Parents who order from a store pay tax as normal.
    """
    if store is None or getattr(store, 'payment_mode', None) != 'organizer_pays':
        return False
    return school_exempt(school_for_store(store))


# ── QR codes, flyer, zip ──────────────────────────────────────────────────────────────────

def qr_png(url):
    from utils.invoice_pay import qr_png as make
    return make(url)


def _file_safe(text):
    return re.sub(r'[^\w\- ]+', '', text or '').strip() or 'qr'


def flyer_pdf(obj, school=None, style=None):
    """One letter-size page in one of three styles (collage, showcase, bold): logos, shirts, a small QR, the link and the deadline."""
    from utils.flyer import build
    return build(obj, school, style)


def flyer_png(obj, school=None, style=None):
    """The same flyer as a PNG image (None when the image renderer is not installed)."""
    from utils.flyer import build_png
    return build_png(obj, school, style)


def qr_zip(obj):
    """A zip of QR PNGs named by store, for a school or a whole district."""
    schools = [obj] if isinstance(obj, Organization) else obj.schools.all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        if isinstance(obj, District):
            z.writestr(f'{_file_safe(obj.name)}.png', qr_png(short_url(obj)))
        for school in schools:
            folder = f'{_file_safe(school.name)}/' if isinstance(obj, District) else ''
            z.writestr(f'{folder}{_file_safe(school.name)}.png', qr_png(short_url(school)))
            for store in stores_of(school, include_inactive=True):
                z.writestr(f'{folder}{_file_safe(store.name)}.png', qr_png(short_url(store, school)))
    return buf.getvalue()


def share_info(obj, school=None):
    """What the Share box needs: link, QR and flyer addresses."""
    path = short_path(obj, school)
    return {'url': short_url(obj, school), 'display': short_display(obj, school),
            'qr': f'{path}/qr.png', 'flyer': f'{path}/flyer.pdf'}


def resolve_short(d_short, s_short=None, store_short=None):
    """The object a short link points at, or None."""
    d = District.query.filter_by(short_slug=d_short, is_active=True).first()
    if d is None:
        return None
    if s_short is None:
        return d
    school = Organization.query.filter_by(district_id=d.id, short_slug=s_short, is_active=True).first()
    if school is None:
        return None
    if store_short is None:
        return school
    for store in stores_of(school, include_inactive=True):
        if store.short_slug == store_short:
            return store
    return None
