"""Which artwork belongs to which group: add it to another group, take it off one, or borrow it from a sibling.

A group's artwork is its own list. Nothing is shared between groups unless the owner puts it there. The one
exception is a school's main logos (see utils.districts.set_school_logos), which are meant for every store.
"""
from __future__ import annotations

import json

from models import Collection, Design, OrgSection, db


def _ids(raw):
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [int(i) for i in value if str(i).isdigit()] if isinstance(value, list) else []


def _dump(ids):
    return json.dumps(list(dict.fromkeys(ids))) if ids else None


def attach(store, design_ids, show_at_top=False):
    """Offer these designs in ``store``. Returns how many were new there."""
    have = _ids(store.allowed_design_ids)
    new = [int(i) for i in design_ids if str(i).isdigit() and int(i) not in have and db.session.get(Design, int(i))]
    if not new:
        return 0
    store.allowed_design_ids = _dump(have + new)
    if show_at_top:
        store.showcase_design_ids = _dump(_ids(store.showcase_design_ids) + new)
    return len(new)


def link_as_colors(designs):
    """Make ``designs[0]`` the main design and the rest its color options. Returns how many colors were linked."""
    from utils.design_metadata import unique_variant_label
    main = designs[0]
    if main.parent_design_id:
        return 0
    if not (main.variant_label or '').strip():
        first = (main.color_families or '').split(',')[0].strip().title()
        main.variant_label = unique_variant_label(main, first or 'Color 1')
    linked = 0
    for child in designs[1:]:
        if child.parent_design_id or child.color_variants.count():
            continue                                    # already part of a family: leave it alone
        first = (child.color_families or '').split(',')[0].strip().title()
        child.variant_label = unique_variant_label(main, first or f'Color {linked + 2}')
        child.parent_design_id = main.id
        child.title = main.title or child.title
        linked += 1
    return linked


def link_uploaded_colors(new_upload_ids, form):
    """When the owner says the files she just uploaded are one layout in different colors, link them as they are saved.
    Returns the uploads that are main designs now (the first one), so only that one is also shown at the top."""
    for raw in form.getlist('new_uploaded_designs'):            # pictures the page uploaded the moment they were chosen
        if str(raw).isdigit() and int(raw) not in new_upload_ids:
            new_upload_ids = list(new_upload_ids) + [int(raw)]
    if form.get('link_new_uploads') != 'on' or len(new_upload_ids) < 2:
        return new_upload_ids
    designs = [d for d in (db.session.get(Design, i) for i in new_upload_ids) if d is not None]
    if len(designs) < 2 or not link_as_colors(designs):
        return new_upload_ids
    db.session.flush()
    return [designs[0].id]


def detach(store, design_id):
    """Take a design off ``store``'s list. The artwork itself stays, and so does every other group that offers it."""
    design_id = int(design_id)
    store.allowed_design_ids = _dump([i for i in _ids(store.allowed_design_ids) if i != design_id])
    store.showcase_design_ids = _dump([i for i in _ids(store.showcase_design_ids) if i != design_id])
    if getattr(store, 'back_design_id', None) == design_id:
        store.back_design_id = None


def uses(design_id):
    """Active groups that offer this design, for a plain "also used in" note."""
    out = []
    for store in Collection.query.filter(Collection.allowed_design_ids.isnot(None)).all():
        if design_id in _ids(store.allowed_design_ids):
            out.append(store)
    return out


def sources(store):
    """What the edit page offers for sharing artwork: ([(sibling store, [designs not yet here])], [other stores])."""
    mine = set(_ids(store.allowed_design_ids))
    section = OrgSection.query.filter_by(collection_id=store.id).first()
    sibling_ids = []
    if section is not None:
        sibling_ids = [s.collection_id for s in OrgSection.query.filter_by(organization_id=section.organization_id).all()
                       if s.collection_id and s.collection_id != store.id]
    siblings = []
    for sib in Collection.query.filter(Collection.id.in_(sibling_ids)).order_by(Collection.name).all() if sibling_ids else []:
        ids = [i for i in _ids(sib.allowed_design_ids) if i not in mine]
        designs = [d for d in Design.query.filter(Design.id.in_(ids)).all() if not d.parent_design_id] if ids else []
        if designs:
            siblings.append((sib, designs))
    others = (Collection.query.filter(Collection.is_active.is_(True), Collection.id != store.id)
              .order_by(Collection.name).all())
    return siblings, others
