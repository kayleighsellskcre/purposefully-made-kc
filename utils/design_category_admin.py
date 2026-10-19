"""Add, rename and remove your own collections and categories, safely.

Rules that keep your library safe:
* Built-in categories are only hidden when removed (and can be restored); nothing is ever hard-deleted.
* Removing a category keeps every design in its collection: they just lose that one sub-label.
* A collection that still has designs cannot be removed. Move its designs first.
"""
from models import Design, DesignCategoryLink, db
from utils import design_taxonomy as tax

MAX_LABEL = 60


def _clean(label):
    return ' '.join((label or '').split())[:MAX_LABEL]


def _load():
    return tax.load_overrides()


def _save(o):
    tax.save_overrides(o)


def counts():
    """({collection: designs}, {(collection, sub): designs}) for live main designs."""
    base = (db.session.query(DesignCategoryLink.category_key, DesignCategoryLink.subcategory_key,
                             db.func.count(db.distinct(DesignCategoryLink.design_id)))
            .join(Design, Design.id == DesignCategoryLink.design_id)
            .filter(Design.parent_design_id.is_(None)).group_by(DesignCategoryLink.category_key,
                                                                 DesignCategoryLink.subcategory_key).all())
    per_sub = {(c, s): n for c, s, n in base if s}
    per_coll = {}
    rows = (db.session.query(DesignCategoryLink.category_key, db.func.count(db.distinct(DesignCategoryLink.design_id)))
            .join(Design, Design.id == DesignCategoryLink.design_id).filter(Design.parent_design_id.is_(None))
            .group_by(DesignCategoryLink.category_key).all())
    for c, n in rows:
        per_coll[c] = n
    return per_coll, per_sub


def add_subcategory(coll_key, label):
    label = _clean(label)
    if coll_key not in tax.COLLECTION_BY_KEY or not label:
        return False, 'Type a name for the new category.'
    coll = tax.COLLECTION_BY_KEY[coll_key]
    if label.lower() in {s.label.lower() for s in coll.subcategories}:
        return False, f'"{label}" is already in {coll.label}.'
    o = _load()
    taken = {s.key for s in coll.subcategories} | {a['key'] for a in o['add_subs'].get(coll_key, [])}
    hidden_match = next((h for h in o['hide_subs'] if h.startswith(coll_key + ':')
                         and tax._slug(label) == h.split(':', 1)[1]), None)
    if hidden_match:                                                  # bringing back one you removed
        o['hide_subs'].remove(hidden_match)
        _save(o)
        return True, f'"{label}" is back in {coll.label}.'
    key = tax.unique_key(label, taken)
    o['add_subs'].setdefault(coll_key, []).append({'key': key, 'label': label})
    _save(o)
    return True, f'Added "{label}" to {coll.label}.'


def add_collection(label):
    label = _clean(label)
    if not label:
        return False, 'Type a name for the new collection.'
    if label.lower() in {c.label.lower() for c in tax.COLLECTIONS}:
        return False, f'"{label}" already exists.'
    o = _load()
    taken = set(tax.COLLECTION_BY_KEY) | {c.key for c in tax.DEFAULT_COLLECTIONS} | {a['key'] for a in o['add_collections']}
    o['add_collections'].append({'key': tax.unique_key(label, taken), 'label': label, 'subs': []})
    _save(o)
    return True, f'Added the "{label}" collection. Add categories inside it if you like.'


def rename(target, label):
    """target is a collection key or 'collection:sub'."""
    label = _clean(label)
    coll_key, _, sub = target.partition(':')
    coll = tax.COLLECTION_BY_KEY.get(coll_key)
    if not coll or not label or (sub and sub not in {s.key for s in coll.subcategories}):
        return False, 'Nothing to rename.'
    o = _load()
    o['rename'][target] = label
    _save(o)
    return True, f'Renamed to "{label}".'


def remove_subcategory(coll_key, sub):
    coll = tax.COLLECTION_BY_KEY.get(coll_key)
    if not coll or sub not in {s.key for s in coll.subcategories}:
        return False, 'That category was not found.'
    label = tax.label_for(coll_key, sub)
    moved = 0
    for link in DesignCategoryLink.query.filter_by(category_key=coll_key, subcategory_key=sub).all():
        moved += 1
        twin = DesignCategoryLink.query.filter_by(design_id=link.design_id, category_key=coll_key, subcategory_key=None).first()
        if twin is not None:
            if link.is_primary:
                twin.is_primary = True
            db.session.delete(link)
        else:
            link.subcategory_key = None
    o = _load()
    custom = o['add_subs'].get(coll_key, [])
    if any(a['key'] == sub for a in custom):
        o['add_subs'][coll_key] = [a for a in custom if a['key'] != sub]       # your own: just gone
    elif f'{coll_key}:{sub}' not in o['hide_subs']:
        o['hide_subs'].append(f'{coll_key}:{sub}')                            # built in: hidden, can be restored
    o['rename'].pop(f'{coll_key}:{sub}', None)
    _save(o)
    note = f' {moved} design{"" if moved == 1 else "s"} stayed in {coll.label}.' if moved else ''
    return True, f'Removed "{label}".' + note


def remove_collection(key):
    coll = tax.COLLECTION_BY_KEY.get(key)
    if not coll:
        return False, 'That collection was not found.'
    n = DesignCategoryLink.query.filter_by(category_key=key).count()
    if n:
        return False, (f'"{coll.label}" still has {n} design{"" if n == 1 else "s"}. Move them to another collection first '
                       '(Find & Bulk Edit makes that quick), then remove it.')
    o = _load()
    if any(a['key'] == key for a in o['add_collections']):
        o['add_collections'] = [a for a in o['add_collections'] if a['key'] != key]
    elif key not in o['hide_collections']:
        o['hide_collections'].append(key)
    o['rename'].pop(key, None)
    _save(o)
    return True, f'Removed "{coll.label}".'


def removed_items():
    """Built-in categories you removed, so you can bring them back."""
    o = _load()
    out = []
    for c in tax.DEFAULT_COLLECTIONS:
        if c.key in o['hide_collections']:
            out.append({'kind': 'collection', 'key': c.key, 'label': c.label})
        for s in c.subcategories:
            if f'{c.key}:{s.key}' in o['hide_subs'] and c.key not in o['hide_collections']:
                out.append({'kind': 'sub', 'key': f'{c.key}:{s.key}', 'label': f'{c.label} / {s.label}'})
    return out


def restore(kind, key):
    o = _load()
    if kind == 'collection' and key in o['hide_collections']:
        o['hide_collections'].remove(key)
    elif kind == 'sub' and key in o['hide_subs']:
        o['hide_subs'].remove(key)
    else:
        return False, 'Nothing to restore.'
    _save(o)
    return True, 'Restored.'
