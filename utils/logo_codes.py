"""Stable presser codes for group-order logos: 1, 1a, 1b, 2, 2a..."""
from utils.cloud_storage import image_url
from utils.design_variants import ensure_not_nested_parent
from utils.group_orders import allowed_design_ids


def letter_suffix(index):
    """0 -> a, 25 -> z, 26 -> aa."""
    if index < 0:
        return ''
    if index < 26:
        return chr(ord('a') + index)
    return letter_suffix(index // 26 - 1) + chr(ord('a') + (index % 26))


def short_collection_name(collection):
    name = (
        (getattr(collection, 'card_title', None) or '')
        or (getattr(collection, 'name', None) or '')
    ).strip()
    if not name:
        return 'Group'
    return name.split()[0]


def _design_title(design):
    return (
        (getattr(design, 'title', None) or '')
        or (getattr(design, 'original_filename', None) or '')
        or 'Logo'
    ).strip() or 'Logo'


def _variant_label(design, fallback='Main'):
    label = (getattr(design, 'variant_label', None) or '').strip()
    return label or fallback


def extra_design_ids_from_orders(orders, collection_id=None):
    ids = []
    seen = set()
    for order in orders or []:
        if collection_id is not None and getattr(order, 'collection_id', None) != collection_id:
            continue
        items = order.items.all() if hasattr(getattr(order, 'items', None), 'all') else list(getattr(order, 'items', None) or [])
        for item in items:
            did = getattr(item, 'design_id', None)
            if did and did not in seen:
                ids.append(did)
                seen.add(did)
    return ids


def logo_families(collection, extra_design_ids=None):
    """One family per main logo, with numbered colorways.

    Main art is "1". Extra colors of that art are "1a", "1b". The next distinct
    logo is "2". Order follows the group order's allowed-design list.
    """
    from models import Design

    ordered_ids = list(allowed_design_ids(collection) or []) if collection else []
    extras = [int(i) for i in (extra_design_ids or []) if i]
    wanted = []
    seen = set()
    for did in ordered_ids + extras:
        if did not in seen:
            wanted.append(did)
            seen.add(did)
    if not wanted:
        return []

    designs = Design.query.filter(Design.id.in_(wanted)).all()
    by_id = {d.id: d for d in designs}

    parent_ids = {d.parent_design_id for d in designs if d.parent_design_id}
    missing = [pid for pid in parent_ids if pid and pid not in by_id]
    if missing:
        for parent in Design.query.filter(Design.id.in_(missing)).all():
            by_id[parent.id] = parent

    roots_in_play = []
    seen_roots = set()
    for did in wanted:
        design = by_id.get(did)
        if not design:
            continue
        root = ensure_not_nested_parent(design) or design
        if root.id not in by_id:
            by_id[root.id] = root
        if root.id not in seen_roots:
            seen_roots.add(root.id)
            roots_in_play.append(root)

    if roots_in_play:
        children = Design.query.filter(
            Design.parent_design_id.in_([root.id for root in roots_in_play])
        ).all()
        for child in children:
            by_id[child.id] = child

    families = []
    for number, root in enumerate(roots_in_play, start=1):
        kids = [
            child for child in by_id.values()
            if child.parent_design_id == root.id
        ]

        def child_sort(child):
            try:
                listed = ordered_ids.index(child.id)
            except ValueError:
                listed = 10_000 + child.id
            return (listed, (child.variant_label or 'zzz').lower(), child.id)

        kids.sort(key=child_sort)
        variants = [_variant_payload(str(number), root, fallback='Main')]
        for index, child in enumerate(kids):
            variants.append(_variant_payload(f'{number}{letter_suffix(index)}', child))
        families.append({
            'number': number,
            'main': variants[0],
            'variants': variants,
        })
    return families


def _variant_payload(code, design, fallback=None):
    return {
        'code': code,
        'design_id': design.id,
        'title': _design_title(design),
        'label': _variant_label(design, fallback=fallback or _design_title(design)),
        'image_url': image_url(design.file_path) if design.file_path else '',
    }


def logo_code_map(families):
    codes = {}
    for family in families or []:
        for variant in family.get('variants') or []:
            did = variant.get('design_id')
            if did:
                codes[did] = variant['code']
    return codes


def stamp_logo_codes(orders, rows, *, design_key='design_id', collection_key='collection_id'):
    """Add logo_code to each row using that order's group-order numbering."""
    from models import Collection

    if not rows:
        return rows

    orders_by_collection = {}
    for order in orders or []:
        orders_by_collection.setdefault(getattr(order, 'collection_id', None), []).append(order)

    named_collections = [
        cid for cid in orders_by_collection
        if cid
    ]
    use_prefix = len(set(named_collections)) > 1

    maps = {}
    prefixes = {}
    for cid, coll_orders in orders_by_collection.items():
        collection = Collection.query.get(cid) if cid else None
        extra = extra_design_ids_from_orders(coll_orders, cid)
        families = logo_families(collection, extra)
        maps[cid] = logo_code_map(families)
        prefixes[cid] = short_collection_name(collection) if collection and use_prefix else ''

    for row in rows:
        did = row.get(design_key)
        cid = row.get(collection_key)
        code = maps.get(cid, {}).get(did)
        if not code and did:
            for other_map in maps.values():
                if did in other_map:
                    code = other_map[did]
                    break
        prefix = prefixes.get(cid) or ''
        row['logo_code'] = f'{prefix} {code}'.strip() if code else ''
    return rows
