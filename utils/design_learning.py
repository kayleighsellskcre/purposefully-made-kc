"""What the library has learned from your corrections, and the numbers for the admin overview.

Only patterns you repeat become lessons (a single fix is a one-off). Lessons are shown to the AI as plain house
rules the next time it reads a design. They only ever make it more careful; they never auto-publish anything.
"""
from collections import Counter
from datetime import datetime, timedelta

from models import Design, DesignCategoryLink, DesignCorrection, DesignRelation, DesignTag, db

MIN_TAG_REMOVALS = 3          # designs you took the same tag off of
MIN_MOVES = 2                 # times you moved designs from the same place to the same other place


def _first_place(summary):
    return (summary or '').split(',')[0].strip()


def lessons(limit=12):
    """[{'kind', 'text', 'count'}] from repeated corrections, most repeated first."""
    out = []
    removed = Counter()
    rows = DesignCorrection.query.filter_by(correction_type='tag_removed').all()
    for slug, design_id in {(r.original_value, r.design_id) for r in rows}:
        removed[slug] += 1
    labels = {t.slug: t.label for t in DesignTag.query.filter(DesignTag.slug.in_(list(removed) or ['-'])).all()}
    for slug, n in removed.items():
        if n >= MIN_TAG_REMOVALS and slug in labels:
            out.append({'kind': 'tag', 'count': n, 'slug': slug,
                        'text': f'You often take the "{labels[slug]}" tag off, so only add it when it is clearly shown.'})

    moves = Counter()
    for r in DesignCorrection.query.filter_by(correction_type='categories_changed').all():
        a, b = _first_place(r.original_value), _first_place(r.corrected_value)
        if a and b and a != 'none' and a != b:
            moves[(a, b)] += 1
    for (a, b), n in moves.items():
        if n >= MIN_MOVES:
            out.append({'kind': 'category', 'count': n,
                        'text': f'Designs placed in "{a}" are often moved to "{b}" by the owner; weigh "{b}" more carefully.'})
    out.sort(key=lambda l: -l['count'])
    return out[:limit]


def prompt_addendum():
    """House rules to append to the AI instructions ('' when nothing has been learned yet)."""
    try:
        found = lessons(8)
    except Exception:
        return ''
    if not found:
        return ''
    return '\n\nHouse rules learned from the owner\'s corrections:\n' + '\n'.join(f'- {l["text"]}' for l in found)


def overview():
    """Everything the admin overview page shows, from a handful of cheap queries."""
    from sqlalchemy import or_
    from utils.design_taxonomy import COLLECTIONS
    mains = Design.query.filter(Design.is_gallery == True, Design.parent_design_id.is_(None))  # noqa: E712
    published = mains.count()
    filed_ids = db.session.query(DesignCategoryLink.design_id).distinct()
    unfiled = mains.filter(~Design.id.in_(filed_ids)).count()
    review = Design.query.filter(or_(Design.ai_status.in_(['needs_review', 'error']), Design.ip_status == 'review')).count()
    reading = Design.query.filter(Design.ai_status.in_(['pending', 'processing'])).count()
    week = datetime.utcnow() - timedelta(days=7)
    added = mains.filter(Design.uploaded_at >= week).count()
    waiting = DesignRelation.query.filter_by(status='suggested').count()

    per = dict(db.session.query(DesignCategoryLink.category_key, db.func.count(db.distinct(DesignCategoryLink.design_id)))
               .join(Design, Design.id == DesignCategoryLink.design_id)
               .filter(Design.is_gallery == True, Design.parent_design_id.is_(None))  # noqa: E712
               .group_by(DesignCategoryLink.category_key).all())
    collections = [{'key': c.key, 'label': c.label, 'count': per.get(c.key, 0)} for c in COLLECTIONS]
    top = max([c['count'] for c in collections] + [1])
    for c in collections:
        c['pct'] = int(round(100 * c['count'] / top))

    recent = (DesignCorrection.query.order_by(DesignCorrection.created_at.desc()).limit(8).all())
    titles = {d.id: (d.title or d.original_filename or 'Design')
              for d in Design.query.filter(Design.id.in_([r.design_id for r in recent] or [0])).all()}
    activity = [{'title': titles.get(r.design_id, 'Design'), 'what': _describe(r), 'when': r.created_at} for r in recent]
    return {'published': published, 'unfiled': unfiled, 'review': review, 'reading': reading, 'added': added,
            'waiting': waiting, 'collections': collections, 'activity': activity, 'lessons': lessons(),
            'corrections': DesignCorrection.query.count()}


def _describe(r):
    if r.correction_type == 'renamed':
        return f'renamed to "{r.corrected_value}"'
    if r.correction_type == 'tag_removed':
        return f'removed the "{r.original_value}" tag'
    if r.correction_type == 'categories_changed':
        return f'moved to {r.corrected_value}'
    return 'edited'
