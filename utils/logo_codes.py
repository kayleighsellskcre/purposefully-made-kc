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


def _orders_items(orders, collection_id):
    for order in orders or []:
        if collection_id is not None and getattr(order, 'collection_id', None) != collection_id:
            continue
        items = order.items.all() if hasattr(getattr(order, 'items', None), 'all') else list(getattr(order, 'items', None) or [])
        for item in items:
            yield item


def design_sides(orders, collection_id=None):
    """{design_id: 'front' | 'back'}. A logo is "back" only if every order line puts it on the back."""
    seen = {}
    for item in _orders_items(orders, collection_id):
        did = getattr(item, 'design_id', None)
        if not did:
            continue
        placement = (getattr(item, 'placement', None) or '').strip().lower().replace(' ', '_')
        seen.setdefault(did, set()).add('back' if placement == 'center_back' else 'front')
    return {did: ('back' if sides == {'back'} else 'front') for did, sides in seen.items()}


def _file_key(url):
    return (url or '').replace('\\', '/').split('?')[0].rstrip('/').split('/')[-1].lower()


def _pretty_name(url):
    raw = _file_key(url)
    if '.' in raw:
        raw = raw.rsplit('.', 1)[0]
    return raw.replace('_', ' ').replace('-', ' ').strip().title() or 'Back art'


def back_logo_tiles(collection, orders):
    """What is printed on the BACK of the shirts: shared back art, and names and numbers.

    Shared back art (the group's locked back design, or a back file customers added) gets a code
    B1, B2... Names and numbers are personal, so they get one tile with the count and the style.
    """
    from models import Design, db
    from utils.order_artwork import back_print_url

    art = {}                     # file name -> tile
    names_count = 0
    names_style = {}

    def add_art(url, title, qty):
        key = _file_key(url)
        if not key:
            return
        tile = art.setdefault(key, {'kind': 'art', 'image_url': url, 'title': title or _pretty_name(url), 'count': 0})
        tile['count'] += qty

    back_id = getattr(collection, 'back_design_id', None)
    if back_id:
        design = db.session.get(Design, back_id)
        if design and design.file_path:
            add_art(image_url(design.file_path), _design_title(design), 0)

    for item in _orders_items(orders, collection.id):
        qty = getattr(item, 'quantity', None) or 1
        details = getattr(item, 'back_design_details', None)   # a property on the order line
        if callable(details):
            details = details()
        meta = details if isinstance(details, dict) else {}
        if meta.get('name') or meta.get('number'):
            names_count += qty
            names_style = names_style or {
                'font': meta.get('font') or getattr(collection, 'back_design_font', None) or '',
                'color': meta.get('text_color') or getattr(collection, 'back_design_text_color', None) or '',
            }
            continue
        url = back_print_url(item)
        if url:
            add_art(url, None, qty)

    tiles = []
    for number, tile in enumerate(art.values(), start=1):
        tile['code'] = f'B{number}'
        tiles.append(tile)
    if names_count:
        tiles.append({
            'kind': 'names', 'code': 'N', 'image_url': '', 'title': 'Names & numbers',
            'count': names_count, 'font': names_style.get('font', ''), 'color': names_style.get('color', ''),
        })
    return tiles
