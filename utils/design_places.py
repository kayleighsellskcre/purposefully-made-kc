"""One way to say where a design belongs: Collection, then optionally a Subcategory.

Every collection works the same way (Music is no longer special). A "place" is either "collection" or
"collection:subcategory". The old folder fields on a design are kept in step so the rest of the site keeps working.
"""
from models import DesignCategoryLink, db
from utils.design_taxonomy import COLLECTION_BY_KEY, COLLECTIONS, collection_for_legacy, is_valid_pair, label_for, legacy_key_for

# Music genres used to be a separate admin-only list. Each one now lives where it belongs in the one structure.
LEGACY_GENRE_PLACES = {
    'country': ('music-entertainment', 'country-music'),
    'rock': ('music-entertainment', 'rock-and-retro'),
    'vintage': ('music-entertainment', 'rock-and-retro'),
    'pop': ('music-entertainment', 'pop-culture'),
    'soul': ('music-entertainment', 'music-lovers'),
    'reggae': ('music-entertainment', 'music-lovers'),
    'gospel': ('faith-inspiration', 'faith-based'),
}


def parse_places(form):
    """[(collection, sub or None)] from the 'place' fields of a form, valid and de-duplicated, in the order given."""
    raw = []
    getter = getattr(form, 'getlist', None)
    values = getter('place') if callable(getter) else str(form.get('place') or '').split(',')
    for value in values:
        key, _, sub = (value or '').strip().partition(':')
        key, sub = key.strip().lower(), (sub.strip().lower() or None)
        if key in COLLECTION_BY_KEY and is_valid_pair(key, sub) and (key, sub) not in raw:
            raw.append((key, sub))
    with_subs = {k for k, s in raw if s}
    return [(k, s) for k, s in raw if s or k not in with_subs]        # "Sports" is implied by "Sports / Football"


def places_to_storage_keys(places):
    """The old folder keys for these places (the first one is the primary folder)."""
    keys = []
    for coll, _sub in places:
        key = legacy_key_for(coll) or 'evergreen'
        if key not in keys:
            keys.append(key)
    return keys


def current_places(design, links=None):
    """Where a design belongs now. Uses its saved places; an older design falls back to its old folders and genres."""
    rows = links if links is not None else DesignCategoryLink.query.filter_by(design_id=design.id).order_by(
        DesignCategoryLink.is_primary.desc(), DesignCategoryLink.id).all()
    places = []
    for l in rows:
        pair = (l.category_key, l.subcategory_key)
        if l.category_key in COLLECTION_BY_KEY and pair not in places:
            places.append(pair)
    if places:
        return places
    for value in [design.folder] + (design.extra_categories or '').split(','):
        value = (value or '').strip()
        coll = collection_for_legacy(value)
        if coll and (coll, None) not in places:
            places.append((coll, None))
        genre = LEGACY_GENRE_PLACES.get(value.lower())
        if genre and genre not in places:
            places.append(genre)
    return places


def places_attr(places):
    return '|'.join(f'{c}:{s}' if s else c for c, s in places)


def places_label(places):
    """'Sports & Game Day / Football, Kansas City' for a small card."""
    out = []
    for coll, sub in places:
        out.append(label_for(coll, sub) and (f'{label_for(coll)} / {label_for(coll, sub)}' if sub else label_for(coll)))
    return ', '.join(x for x in out if x)


def describe_many(designs):
    """{design id: {'attr', 'label'}} for a page of designs (two queries, not one per design)."""
    ids = [d.id for d in designs] or [0]
    links = {}
    for l in DesignCategoryLink.query.filter(DesignCategoryLink.design_id.in_(ids)).order_by(
            DesignCategoryLink.is_primary.desc(), DesignCategoryLink.id).all():
        links.setdefault(l.design_id, []).append(l)
    out = {}
    for d in designs:
        places = current_places(d, links.get(d.id, []))
        out[d.id] = {'attr': places_attr(places), 'label': places_label(places)}
    return out


def apply_places(design, places, user_id=None, remember=True):
    """Save these places as your own choice (manual, locked, remembered) and keep the old folder fields in step."""
    from utils.design_categories import compose_extra_categories, public_extra_storage_keys, stored_music_genres
    from utils.design_tags import record_correction
    before = places_label(current_places(design)) or 'none'
    DesignCategoryLink.query.filter_by(design_id=design.id).delete()
    for i, (coll, sub) in enumerate(places):
        db.session.add(DesignCategoryLink(design_id=design.id, category_key=coll, subcategory_key=sub,
                                          is_primary=(i == 0), source='manual', locked=True))
    keys = places_to_storage_keys(places)
    if keys:
        design.folder = keys[0]
        design.extra_categories = compose_extra_categories(keys[1:], stored_music_genres(design.extra_categories)) or None
    db.session.flush()
    after = places_label(places) or 'none'
    if remember and after != before:
        record_correction(design, 'categories', before, after, 'categories_changed', user_id=user_id)
    return places
