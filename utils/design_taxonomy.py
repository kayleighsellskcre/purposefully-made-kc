"""The design gallery's organization: main collections and their subcategories.

Structure customers see: Main collection -> Subcategory -> Designs. Anything more
specific (sport, recipient, style, color) is a tag or filter, never another level.

The ten collections are the eight from the plan plus School Spirit and Luxury
Basics, which already exist on the site and matter to the business. "Fan Favorites"
is no longer a folder; it is an automatic collection built from real activity.

Each collection keeps the storage key the site already uses (`legacy_keys`), so no
existing design, folder or URL is touched.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Subcategory:
    key: str
    label: str


@dataclass(frozen=True)
class Collection:
    key: str
    label: str
    legacy_keys: tuple          # folder / extra_categories values the site already stores
    subcategories: tuple = ()


def _subs(*labels):
    return tuple(Subcategory(label.lower().replace('&', 'and').replace("'", '').replace('  ', ' ')
                             .replace(' ', '-'), label) for label in labels)


DEFAULT_COLLECTIONS = (
    Collection('kansas-city', 'Kansas City', ('kc',), _subs(
        'KC Chiefs', 'KC Royals', 'KC Current', 'Sporting KC', 'Other KC Teams')),
    Collection('faith-inspiration', 'Faith & Inspiration', ('faith',), _subs(
        'Faith-Based', 'Scripture & Biblical Sayings', 'Encouragement', 'Inspirational', 'Positive Affirmations')),
    Collection('sports-game-day', 'Sports & Game Day', ('sports',), _subs(
        'Football', 'Baseball & Softball', 'Soccer', 'Basketball', 'Volleyball', 'Cheer & Dance', 'General Sports')),
    Collection('school-spirit', 'School Spirit', ('school',), _subs(
        'Elementary', 'Middle & High School', 'College', 'Mascots', 'Teachers & Staff')),
    Collection('music-entertainment', 'Music & Entertainment', ('music',), _subs(
        'Country Music', 'Rock & Retro', 'Concert & Tour Inspired', 'Music Lovers', 'Pop Culture')),
    Collection('funny-sarcastic', 'Funny & Sarcastic', ('funny',), _subs(
        'Funny Sayings', 'Sarcasm & Sass', 'Mom & Dad Humor', 'Adult Humor', 'Everyday Humor')),
    Collection('family-relationships', 'Family & Relationships', ('couples', 'family'), _subs(
        'Moms', 'Dads', 'Grandparents', 'Kids & Babies', 'Aunts & Uncles', 'Siblings', 'Friends & Besties')),
    Collection('lifestyle-interests', 'Lifestyle & Interests', (), _subs(
        'Coffee & Drinks', 'Outdoors & Adventure', 'Animals & Pet Lovers', 'Books & Reading',
        'Western & Country', 'Hobbies & Interests')),
    Collection('holidays-seasons', 'Holidays & Seasons', ('holiday', 'seasonal'), _subs(
        'Christmas', 'Halloween', 'Fall & Thanksgiving', "Valentine's Day", 'Easter & Spring',
        'Summer & Patriotic', 'Other Holidays')),
    Collection('luxury-basics', 'Luxury Basics', ('luxury_basics', 'luxury'), ()),
)

# The live structure. These two objects are changed in place when you edit your categories, so every
# module that imported them sees the change.
COLLECTIONS = list(DEFAULT_COLLECTIONS)
COLLECTION_BY_KEY = {c.key: c for c in COLLECTIONS}
COLLECTION_LABELS = {c.key: c.label for c in COLLECTIONS}

# Storage values the site already writes to Design.folder / extra_categories -> new collection key.
# 'evergreen' / 'custom_orders' (Fan Favorites) intentionally map to nothing: that collection is automatic now.
LEGACY_TO_COLLECTION = {}
for _c in DEFAULT_COLLECTIONS:
    for _k in _c.legacy_keys:
        LEGACY_TO_COLLECTION[_k] = _c.key


def collection_for_legacy(value):
    """New collection key for a folder value the site already uses, or ''."""
    return LEGACY_TO_COLLECTION.get((value or '').strip().lower(), '')


def legacy_key_for(collection_key):
    """The storage key the existing gallery uses for this collection, or ''."""
    c = COLLECTION_BY_KEY.get(collection_key)
    return c.legacy_keys[0] if c and c.legacy_keys else ''


def subcategory_keys(collection_key):
    c = COLLECTION_BY_KEY.get(collection_key)
    return [s.key for s in c.subcategories] if c else []


def is_valid_pair(collection_key, subcategory_key=None):
    """True for a known collection, and (when given) one of its own subcategories."""
    if collection_key not in COLLECTION_BY_KEY:
        return False
    return not subcategory_key or subcategory_key in subcategory_keys(collection_key)


def label_for(collection_key, subcategory_key=None):
    c = COLLECTION_BY_KEY.get(collection_key)
    if not c:
        return ''
    if subcategory_key:
        for s in c.subcategories:
            if s.key == subcategory_key:
                return s.label
        return ''
    return c.label


# -- Your own changes: add, rename and remove categories ----------------------------------------
#
# Stored as a small list of changes on top of the built-in structure (so nothing built in is ever lost):
#   {"hide_subs": ["coll:sub"], "hide_collections": ["coll"], "rename": {"coll": "Label", "coll:sub": "Label"},
#    "add_subs": {"coll": [{"key": "...", "label": "..."}]}, "add_collections": [{"key", "label", "subs": [...]}]}

import json as _json
import re as _re
import time as _time

OVERRIDES_KEY = 'design_taxonomy_overrides'
_state = {'raw': None, 'checked': 0.0}


def _slug(text):
    return _re.sub(r"[^a-z0-9]+", '-', (text or '').lower().replace("'", '').replace('&', 'and')).strip('-')[:40]


def empty_overrides():
    return {'hide_subs': [], 'hide_collections': [], 'rename': {}, 'add_subs': {}, 'add_collections': []}


def build(overrides):
    """The effective list of collections: built-ins with your changes applied."""
    o = {**empty_overrides(), **(overrides or {})}
    out = []
    for c in DEFAULT_COLLECTIONS:
        if c.key in o['hide_collections']:
            continue
        subs = [Subcategory(s.key, o['rename'].get(f'{c.key}:{s.key}', s.label)) for s in c.subcategories
                if f'{c.key}:{s.key}' not in o['hide_subs']]
        subs += [Subcategory(a['key'], o['rename'].get(f"{c.key}:{a['key']}", a['label'])) for a in o['add_subs'].get(c.key, [])
                 if f"{c.key}:{a['key']}" not in o['hide_subs']]
        out.append(Collection(c.key, o['rename'].get(c.key, c.label), c.legacy_keys, tuple(subs)))
    for a in o['add_collections']:
        if a['key'] in o['hide_collections']:
            continue
        subs = tuple(Subcategory(x['key'], o['rename'].get(f"{a['key']}:{x['key']}", x['label'])) for x in a.get('subs', [])
                     if f"{a['key']}:{x['key']}" not in o['hide_subs'])
        out.append(Collection(a['key'], o['rename'].get(a['key'], a['label']), (), subs))
    return out


def apply_overrides(overrides):
    """Make the live structure match these changes (in place)."""
    built = build(overrides)
    COLLECTIONS[:] = built
    COLLECTION_BY_KEY.clear()
    COLLECTION_BY_KEY.update({c.key: c for c in built})
    COLLECTION_LABELS.clear()
    COLLECTION_LABELS.update({c.key: c.label for c in built})


def load_overrides():
    """The saved changes, or an empty set. Never raises (the shop must work even if this cannot be read)."""
    try:
        from models import SystemSettings
        row = SystemSettings.query.filter_by(key=OVERRIDES_KEY).first()
        data = _json.loads(row.value) if row and row.value else {}
        return {**empty_overrides(), **data} if isinstance(data, dict) else empty_overrides()
    except Exception:
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass
        return empty_overrides()


def save_overrides(overrides):
    from models import SystemSettings, db
    row = SystemSettings.query.filter_by(key=OVERRIDES_KEY).first()
    if row is None:
        row = SystemSettings(key=OVERRIDES_KEY, description='Your changes to the design collections and categories')
        db.session.add(row)
    row.value = _json.dumps(overrides)
    db.session.commit()
    _state['raw'] = row.value
    apply_overrides(overrides)


def refresh(force=False, every=10.0):
    """Pick up changes made by another worker. At most one tiny query every few seconds."""
    now = _time.monotonic()
    if not force and now - _state['checked'] < every:
        return
    _state['checked'] = now
    try:
        from models import SystemSettings
        row = SystemSettings.query.filter_by(key=OVERRIDES_KEY).first()
        raw = row.value if row else None
    except Exception:
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass
        return
    if raw != _state['raw'] or force:
        _state['raw'] = raw
        try:
            apply_overrides(_json.loads(raw) if raw else {})
        except Exception:
            apply_overrides({})


def unique_key(label, taken):
    base = _slug(label) or 'category'
    key, n = base, 2
    while key in taken:
        key, n = f'{base}-{n}', n + 1
    return key
