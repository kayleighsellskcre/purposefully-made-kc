"""Group gallery designs so one card can offer multiple color variants."""
from __future__ import annotations

import re

from sqlalchemy import or_

from utils.design_categories import (
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
    variants = []
    for i, opt in enumerate(options):
        variants.append({
            'id': opt.id,
            'url': resolve(opt.file_path),
            'label': _label_for(opt, 'Default' if i == 0 else f'Color {i + 1}'),
        })
    title = design.title or design.original_filename or 'Design'
    category_keys = design_category_keys(
        design.folder,
        design.extra_categories,
    )
    return {
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

    return [
        gallery_card_dict(
            design,
            resolve_url=resolve_url,
            options=[design, *children_by_parent.get(design.id, [])],
        )
        for design in mains
    ]


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
    """Landing cards: one folder per public category that has designs."""
    folders = []
    for category in GALLERY_CATEGORIES:
        members = [
            card for card in cards
            if category.key in (card.get('category_keys') or [])
        ]
        if not members:
            continue
        folders.append({
            'key': category.key,
            'label': category.label,
            'count': len(members),
            'covers': [
                {
                    'id': card['id'],
                    'url': card['url'],
                    'title': card['title'],
                }
                for card in members[:FOLDER_COVER_LIMIT]
            ],
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
