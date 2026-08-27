"""Group gallery designs so one card can offer multiple color variants."""
from __future__ import annotations

from sqlalchemy import or_


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


def gallery_card_dict(design, resolve_url=None):
    """Payload for one public/customizer gallery card."""
    resolve = resolve_url or _resolve_url
    options = color_options_for(design, include_self=True)
    variants = []
    for i, opt in enumerate(options):
        variants.append({
            'id': opt.id,
            'url': resolve(opt.file_path),
            'label': _label_for(opt, 'Default' if i == 0 else f'Color {i + 1}'),
        })
    title = design.title or design.original_filename or 'Design'
    return {
        'id': design.id,
        'url': resolve(design.file_path),
        'title': title,
        'variants': variants,
        'has_colors': len(variants) > 1,
        'color_count': len(variants),
    }


def gallery_cards_for_public(Design, resolve_url=None, limit=None):
    q = gallery_mains_query(Design)
    if limit:
        q = q.limit(limit)
    return [gallery_card_dict(d, resolve_url=resolve_url) for d in q.all()]


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
