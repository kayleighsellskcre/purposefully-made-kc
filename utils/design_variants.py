"""Group gallery designs so one card can offer multiple color variants."""
from __future__ import annotations

import re

from sqlalchemy import or_

from utils.design_categories import (
    ALWAYS_VISIBLE_GALLERY_CATEGORIES,
    GALLERY_CATEGORIES,
    GALLERY_CATEGORY_LABELS,
    design_category_keys,
    gallery_group_for_title,
)

FOLDER_COVER_LIMIT = 6


def _resolve_url(file_path):
    try:
        from utils.cloud_storage import image_url
        return image_url(file_path) if file_path else ''
    except Exception:
        if not file_path:
            return ''
        if str(file_path).startswith('http'):
            return file_path
        return f'/static/{file_path.lstrip("/")}'


def _label_for(design, fallback='Default'):
    label = (getattr(design, 'variant_label', None) or '').strip()
    if label:
        return label
    return fallback


def gallery_mains_query(Design):
    """Published gallery designs that are main cards (not color children)."""
    return (
        Design.query
        .filter(
            Design.is_gallery == True,
            or_(Design.parent_design_id.is_(None), Design.parent_design_id == None),
        )
        .order_by(Design.uploaded_at.desc())
    )


def color_options_for(design, *, include_self=True):
    """Ordered list of Design rows: main (optional) then published color children."""
    options = []
    if include_self and design is not None:
        options.append(design)
    if design is None:
        return options
    children = [c for c in design.color_variants.filter_by(is_gallery=True).all()]
    children.sort(key=lambda d: ((d.variant_label or 'zzz').lower(), d.id))
    options.extend(children)
    return options


def gallery_card_dict(design, resolve_url=None, options=None):
    """Payload for one public/customizer gallery card."""
    resolve = resolve_url or _resolve_url
    options = (
        options
        if options is not None
        else color_options_for(design, include_self=True)
    )
    try:
        from services.artwork_metrics import peek_cached
    except Exception:
        peek_cached = None

    def _artwork_fit(opt):
        if peek_cached is None or opt is None:
            return None
        try:
            return peek_cached(opt)
        except Exception:
            return None

    variants = []
    for i, opt in enumerate(options):
        variant = {
            'id': opt.id,
            'url': resolve(opt.file_path),
            'label': _label_for(opt, 'Default' if i == 0 else f'Color {i + 1}'),
            '_path': (opt.file_path or '').strip().lower(),
        }
        fit = _artwork_fit(opt)
        if fit is not None:
            variant['artwork_fit'] = fit
        variants.append(variant)
    title = design.title or design.original_filename or 'Design'
    category_keys = design_category_keys(
        design.folder,
        design.extra_categories,
    )
    card = {
        'id': design.id,
        'url': resolve(design.file_path),
        'title': title,
        'variants': variants,
        'has_colors': len(variants) > 1,
        'color_count': len(variants),
        'folder': design.folder or '',
        'extra_categories': design.extra_categories or '',
        'category_keys': category_keys,
        'category_labels': [
            GALLERY_CATEGORY_LABELS[key] for key in category_keys
        ],
        'group': gallery_group_for_title(title),
        'uploaded_at': design.uploaded_at.isoformat() if design.uploaded_at else '',
    }
    fit = _artwork_fit(design)
    if fit is not None:
        card['artwork_fit'] = fit
    return card


def gallery_cards_for_public(Design, resolve_url=None, limit=None):
    q = gallery_mains_query(Design)
    if limit:
        q = q.limit(limit)
    mains = q.all()
    if not mains:
        return []

    # Fetch every published color child in one query. The previous dynamic
    # relationship lookup issued one additional query per card as the gallery
    # grew.
    main_ids = [design.id for design in mains]
    children = (
        Design.query
        .filter(
            Design.is_gallery == True,
            Design.parent_design_id.in_(main_ids),
        )
        .order_by(Design.id.asc())
        .all()
    )
    children_by_parent = {design_id: [] for design_id in main_ids}
    for child in children:
        children_by_parent.setdefault(child.parent_design_id, []).append(child)
    for family in children_by_parent.values():
        family.sort(key=lambda d: ((d.variant_label or 'zzz').lower(), d.id))

    cards = [
        gallery_card_dict(
            design,
            resolve_url=resolve_url,
            options=[design, *children_by_parent.get(design.id, [])],
        )
        for design in mains
    ]
    return dedupe_gallery_cards(cards)


def _gallery_title_key(title):
    return re.sub(r'[^a-z0-9]+', ' ', (title or '').lower()).strip()


def _gallery_title_display(title):
    text = re.sub(r'\s+', ' ', (title or '').strip())
    return text.title() if text else 'Design'


def _public_variant(variant, fallback_url=''):
    public = {
        'id': variant.get('id'),
        'url': (variant.get('url') or fallback_url or '').strip(),
        'label': variant.get('label') or 'Default',
    }
    if variant.get('artwork_fit') is not None:
        public['artwork_fit'] = variant['artwork_fit']
    return public


def _variant_marker(variant, card):
    """Prefer the stored file path so placeholder/CDN fallbacks do not collapse real colors."""
    path = (variant.get('_path') or '').strip().lower()
    if path:
        return path
    url = (variant.get('url') or card.get('url') or '').strip()
    if url and not url.startswith('data:'):
        return url.lower()
    return f"id:{variant.get('id') or card.get('id')}"


def dedupe_gallery_cards(cards):
    """One public card per design name, merging duplicate images and stray copies."""
    buckets = {}
    order = []
    for card in cards or []:
        key = _gallery_title_key(card.get('title')) or f"id:{card.get('id')}"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(card)

    result = []
    for key in order:
        family = buckets[key]
        cover = family[0]
        if len(family) == 1:
            variants = [
                _public_variant(variant, cover.get('url'))
                for variant in (cover.get('variants') or [])
            ]
            result.append({
                **cover,
                'title': _gallery_title_display(cover.get('title')),
                'variants': variants,
                'has_colors': len(variants) > 1,
                'color_count': max(len(variants), 1),
            })
            continue
        seen = set()
        variants = []
        for card in family:
            options = card.get('variants') or [{
                'id': card.get('id'),
                'url': card.get('url'),
                'label': 'Default',
                '_path': '',
            }]
            for variant in options:
                marker = _variant_marker(variant, card)
                if marker in seen:
                    continue
                seen.add(marker)
                variants.append(_public_variant(variant, card.get('url')))
        result.append({
            **cover,
            'title': _gallery_title_display(cover.get('title')),
            'url': (variants[0]['url'] if variants else cover.get('url')),
            'variants': variants,
            'has_colors': len(variants) > 1,
            'color_count': max(len(variants), 1),
        })
    return result


def _search_blob(card):
    bits = [
        card.get('title') or '',
        card.get('group') or '',
        ' '.join(card.get('category_keys') or []),
        ' '.join(card.get('category_labels') or []),
    ]
    for variant in card.get('variants') or []:
        bits.append(variant.get('label') or '')
    return re.sub(r'[^a-z0-9]+', ' ', ' '.join(bits).lower())


def filter_gallery_cards(cards, *, category=None, query=None):
    """Keep main gallery cards that match a public folder and/or search words."""
    words = [
        word
        for word in re.sub(r'[^a-z0-9]+', ' ', (query or '').lower()).split()
        if word
    ]
    matches = []
    for card in cards:
        if category and category not in (card.get('category_keys') or []):
            continue
        if words:
            blob = _search_blob(card)
            if not all(word in blob for word in words):
                continue
        matches.append(card)
    return matches


def gallery_folder_cards(cards):
    """Landing cards: one folder per public category that has designs.

    A design tagged with more than one category (e.g. "Kansas City Football"
    filed under both Sports and Kansas City) genuinely belongs in both
    folders, so it still counts toward both. But picking cover thumbnails
    independently per folder meant the same image could appear twice in the
    previews visible on the overview page at once. Covers are now unique
    across folders - each design's image previews as a cover for the first
    folder that claims it, and later folders pick a different design.
    """
    folders = []
    used_cover_urls = set()
    for category in GALLERY_CATEGORIES:
        members = [
            card for card in cards
            if category.key in (card.get('category_keys') or [])
        ]
        if not members and category.key not in ALWAYS_VISIBLE_GALLERY_CATEGORIES:
            continue
        covers = []
        for card in members:
            if len(covers) >= FOLDER_COVER_LIMIT:
                break
            marker = (card.get('url') or '').strip().lower()
            if marker and marker in used_cover_urls:
                continue
            if marker:
                used_cover_urls.add(marker)
            covers.append({
                'id': card['id'],
                'url': card['url'],
                'title': card['title'],
            })
        if not covers and members:
            # Every candidate image was already claimed by an earlier
            # folder. A repeated image beats an empty folder tile.
            first = members[0]
            covers.append({
                'id': first['id'],
                'url': first['url'],
                'title': first['title'],
            })
        folders.append({
            'key': category.key,
            'label': category.label,
            'count': len(members),
            'covers': covers,
        })
    return folders


def ensure_not_nested_parent(parent):
    """Variants of variants are not allowed — always attach to the root main."""
    if parent is None:
        return None
    root = parent
    # Walk up in case someone linked a child as parent
    seen = set()
    while getattr(root, 'parent_design_id', None) and root.id not in seen:
        seen.add(root.id)
        root = root.parent_design
        if root is None:
            break
    return root or parent


def _replace_id_in_json_list(raw, old_id, new_id):
    import json
    try:
        ids = json.loads(raw)
    except Exception:
        return raw, False
    if not isinstance(ids, list):
        return raw, False
    next_ids = []
    changed = False
    for item in ids:
        try:
            value = int(item)
        except (TypeError, ValueError):
            next_ids.append(item)
            continue
        if value == old_id:
            next_ids.append(new_id)
            changed = True
        else:
            next_ids.append(value)
    if not changed:
        return raw, False
    return json.dumps(next_ids), True


def _rewrite_collection_design_ids(old_id, new_id):
    """Keep group-order logo lists pointed at the family cover after a swap."""
    if not old_id or not new_id or old_id == new_id:
        return
    from models import Collection
    collections = Collection.query.filter(
        or_(
            Collection.allowed_design_ids.isnot(None),
            Collection.showcase_design_ids.isnot(None),
        )
    ).all()
    for collection in collections:
        for field in ('allowed_design_ids', 'showcase_design_ids'):
            raw = getattr(collection, field)
            if not raw:
                continue
            updated, changed = _replace_id_in_json_list(raw, old_id, new_id)
            if changed:
                setattr(collection, field, updated)


def promote_gallery_main(chosen):
    """Make this color variant the public gallery cover for its family."""
    if chosen is None:
        return None
    from models import db
    root = ensure_not_nested_parent(chosen) or chosen
    if root.id == chosen.id:
        return chosen

    siblings = [
        child for child in root.color_variants.all()
        if child.id != chosen.id
    ]
    chosen.parent_design_id = None
    db.session.flush()
    for sibling in siblings:
        sibling.parent_design_id = chosen.id
    root.parent_design_id = chosen.id

    chosen.title = root.title or chosen.title
    chosen.folder = root.folder or chosen.folder
    chosen.extra_categories = root.extra_categories
    if root.sku and not chosen.sku:
        chosen.sku = root.sku
    chosen.is_gallery = True
    if not (root.variant_label or '').strip():
        root.variant_label = 'Default'

    _rewrite_collection_design_ids(root.id, chosen.id)
    return chosen


def unpublish_color_variants(design):
    """Take color children off the public gallery with their main design."""
    if design is None:
        return []
    children = list(design.color_variants.all())
    for child in children:
        child.is_gallery = False
        child.gallery_status = None
    return children


def card_contains_design_id(card, design_id):
    """True if a gallery card dict includes this design id (main or color)."""
    if not card or design_id is None:
        return False
    try:
        wanted = int(design_id)
    except (TypeError, ValueError):
        return False
    if int(card.get('id') or 0) == wanted:
        return True
    for v in card.get('variants') or []:
        try:
            if int(v.get('id')) == wanted:
                return True
        except (TypeError, ValueError):
            continue
    return False
