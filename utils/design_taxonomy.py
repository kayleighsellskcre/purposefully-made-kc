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


COLLECTIONS = (
    Collection('kansas-city', 'Kansas City', ('kc',), _subs(
        'KC Chiefs', 'KC Royals', 'KC Current', 'Sporting KC', 'Other KC Teams', 'Kansas City Pride')),
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

COLLECTION_BY_KEY = {c.key: c for c in COLLECTIONS}
COLLECTION_LABELS = {c.key: c.label for c in COLLECTIONS}

# Storage values the site already writes to Design.folder / extra_categories -> new collection key.
# 'evergreen' / 'custom_orders' (Fan Favorites) intentionally map to nothing: that collection is automatic now.
LEGACY_TO_COLLECTION = {}
for _c in COLLECTIONS:
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
