"""Admin: find any design in the whole library (hidden ones too) and change many at once.

Bulk edits count as your own choices: they are saved as manual, remembered as corrections and never
overwritten by the automation afterwards.
"""
from sqlalchemy import or_

from models import Design, DesignCategoryLink, DesignTag, DesignTagLink, db
from utils.design_tags import _norm, record_correction, search_terms, set_manual_tags, vocabulary
from utils.design_taxonomy import COLLECTION_BY_KEY, is_valid_pair, label_for, legacy_key_for

PAGE_SIZE = 40
STATUSES = (('', 'All designs'), ('live', 'Live'), ('held', 'Not live'), ('review', 'Needs review'),
            ('errors', 'Processing errors'), ('unfiled', 'Not filed'))


def _text_filter(query, text):
    tags = vocabulary(active_only=False)
    for word in [w for w in _norm(text).split() if w]:
        terms = search_terms(word)['exact'] | {word}
        tag_ids = [t.id for t in tags.values()
                   if {_norm(t.label), _norm(t.slug.replace('-', ' '))} & terms]
        conds = []
        for term in terms:
            like = f'%{term}%'
            conds += [Design.title.ilike(like), Design.sku.ilike(like), Design.keywords.ilike(like),
                      Design.art_text.ilike(like), Design.audience.ilike(like), Design.style.ilike(like),
                      Design.original_filename.ilike(like)]
        if tag_ids:
            conds.append(Design.id.in_(db.session.query(DesignTagLink.design_id).filter(DesignTagLink.tag_id.in_(tag_ids))))
        query = query.filter(or_(*conds))
    return query


def find(args):
    """(designs for this page, total, page, filters used). Main designs only: colorways travel with their main."""
    q = Design.query.filter(Design.parent_design_id.is_(None), Design.hidden_from_admin != True)  # noqa: E712
    q = q.filter(or_(Design.is_gallery == True, Design.ai_status.isnot(None), Design.sku.isnot(None)))  # noqa: E712
    text = (args.get('q') or '').strip()
    if text:
        q = _text_filter(q, text)
    coll = (args.get('collection') or '').strip()
    if coll in COLLECTION_BY_KEY:
        q = q.filter(Design.id.in_(db.session.query(DesignCategoryLink.design_id).filter_by(category_key=coll)))
    tag = (args.get('tag') or '').strip()
    if tag:
        q = q.filter(Design.id.in_(db.session.query(DesignTagLink.design_id)
                                   .join(DesignTag, DesignTag.id == DesignTagLink.tag_id).filter(DesignTag.slug == tag)))
    color = (args.get('color') or '').strip().lower()
    if color:
        q = q.filter(Design.color_families.ilike(f'%{color}%'))
    status = (args.get('status') or '').strip()
    if status == 'live':
        q = q.filter(Design.is_gallery == True)  # noqa: E712
    elif status == 'held':
        q = q.filter(or_(Design.is_gallery == False, Design.is_gallery.is_(None)))  # noqa: E712
    elif status == 'review':
        q = q.filter(or_(Design.ai_status == 'needs_review', Design.ip_status == 'review'))
    elif status == 'errors':
        q = q.filter(Design.ai_status == 'error')
    elif status == 'unfiled':
        q = q.filter(~Design.id.in_(db.session.query(DesignCategoryLink.design_id)))
    total = q.count()
    page = max(1, int(args.get('page') or 1))
    rows = q.order_by(Design.uploaded_at.desc(), Design.id.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    used = {k: v for k, v in (('q', text), ('collection', coll), ('tag', tag), ('color', color), ('status', status)) if v}
    return rows, total, page, used


def describe(rows):
    """Collections and tag names for the rows on one page (two queries)."""
    ids = [d.id for d in rows] or [0]
    places, tags = {}, {}
    for l in DesignCategoryLink.query.filter(DesignCategoryLink.design_id.in_(ids)).all():
        places.setdefault(l.design_id, []).append(label_for(l.category_key, l.subcategory_key) or l.category_key)
    for slug_label, design_id in (db.session.query(DesignTag.label, DesignTagLink.design_id)
                                  .join(DesignTagLink, DesignTagLink.tag_id == DesignTag.id)
                                  .filter(DesignTagLink.design_id.in_(ids), DesignTag.tag_type != 'control').all()):
        tags.setdefault(design_id, []).append(slug_label)
    return places, tags


# -- Bulk actions -------------------------------------------------------------------------------

def _tag_slugs(design):
    return [s for (s,) in db.session.query(DesignTag.slug).join(DesignTagLink, DesignTagLink.tag_id == DesignTag.id)
            .filter(DesignTagLink.design_id == design.id).all()]


def bulk_apply(ids, action, value, user_id=None):
    """Apply one change to many designs. Returns (changed count, message)."""
    designs = Design.query.filter(Design.id.in_(ids or [0])).all()
    changed = 0
    if action == 'add_collection':
        key, _, sub = (value or '').partition(':')
        sub = sub or None
        if key not in COLLECTION_BY_KEY or not is_valid_pair(key, sub):
            return 0, 'Pick a collection first.'
        from utils.design_categories import compose_extra_categories, public_extra_storage_keys, stored_music_genres
        for d in designs:
            if DesignCategoryLink.query.filter_by(design_id=d.id, category_key=key, subcategory_key=sub).first():
                continue
            before = ', '.join(l.category_key for l in DesignCategoryLink.query.filter_by(design_id=d.id)) or 'none'
            first = not DesignCategoryLink.query.filter_by(design_id=d.id, is_primary=True).first()
            db.session.add(DesignCategoryLink(design_id=d.id, category_key=key, subcategory_key=sub,
                                              is_primary=first, source='manual', locked=True))
            legacy = legacy_key_for(key)
            if first and not d.folder:
                d.folder = legacy or 'evergreen'
            elif legacy and legacy != d.folder:
                keys = public_extra_storage_keys(d.extra_categories)
                if legacy not in keys:
                    d.extra_categories = compose_extra_categories(keys + [legacy], stored_music_genres(d.extra_categories))
            record_correction(d, 'categories', before, before + ', ' + key, 'categories_changed', user_id=user_id)
            changed += 1
        return changed, f'Added to {label_for(key, sub)}: {changed} design{"" if changed == 1 else "s"}.'
    if action in ('add_tag', 'remove_tag'):
        tags = vocabulary(active_only=False)
        if value not in tags:
            return 0, 'Pick a tag first.'
        for d in designs:
            have = _tag_slugs(d)
            if action == 'add_tag' and value not in have:
                set_manual_tags(d, have + [value], user_id=user_id)
                changed += 1
            elif action == 'remove_tag' and value in have:
                set_manual_tags(d, [s for s in have if s != value], user_id=user_id)
                changed += 1
        verb = 'Added' if action == 'add_tag' else 'Removed'
        return changed, f'{verb} "{tags[value].label}" on {changed} design{"" if changed == 1 else "s"}.'
    if action in ('show', 'hide'):
        for d in designs:
            if action == 'show' and not d.is_gallery:
                d.is_gallery = True
                changed += 1
            elif action == 'hide' and d.is_gallery:
                d.is_gallery = False                       # colorways stay attached; nothing is deleted
                changed += 1
        return changed, f'{"Published" if action == "show" else "Hid"} {changed} design{"" if changed == 1 else "s"}. Nothing was deleted.'
    return 0, 'Choose what to do first.'


def reread(ids, api_key, limit=5):
    """Run the automatic reading again on a few designs. Your locked edits are never overwritten."""
    from utils.design_ai import apply_classification
    from utils.design_organizer import _analyze
    done = failed = 0
    for d in Design.query.filter(Design.id.in_(ids or [0])).limit(limit).all():
        try:
            result = _analyze(d, 'smart', api_key)
            apply_classification(d, result, chose_folder=bool(d.folder))
            d.ai_error = None
            done += 1
        except Exception as exc:
            d.ai_status, d.ai_error = 'error', str(exc)[:500]
            failed += 1
    return done, failed
