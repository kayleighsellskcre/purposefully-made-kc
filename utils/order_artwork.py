"""Resolve garment mockups and print-ready artwork for cart, checkout, and admin.

Customer-facing pages show a proof (shirt + design at the ordered size).
Production pages show the transparent print file so it can be saved for DTF.
"""
from pathlib import Path
import re


FRONT_PLACEMENTS = ('center_chest', 'left_chest', 'right_chest')


def _as_url(value):
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith(('http://', 'https://', '/', 'data:')):
        return value
    return f'/static/{value.lstrip("/")}'


def mockup_urls(product, color):
    """Front and back garment photos for a product/color.

    Never falls back to a generic product template when a color was requested —
    that template is often a different color (or even a different garment look)
    and is what made admin order pages show the wrong shirt.
    """
    from models import ProductColorVariant
    from flask import current_app, has_app_context

    front = back = None
    if not product:
        return None, None

    color = (color or '').strip() or None
    variant = None
    if color:
        variant = ProductColorVariant.query.filter_by(
            product_id=product.id,
            color_name=color,
        ).first()
        if not variant:
            color_key = color.lower()
            color_compact = color_key.replace(' ', '').replace('-', '').replace('_', '')
            for v in ProductColorVariant.query.filter_by(product_id=product.id).all():
                name = (v.color_name or '').strip()
                if not name:
                    continue
                key = name.lower()
                compact = key.replace(' ', '').replace('-', '').replace('_', '')
                if key == color_key or compact == color_compact:
                    variant = v
                    break
                # "Heather Navy" ↔ "Navy" / "Navy Heather"
                if color_key.replace('heather ', '') == key.replace('heather ', ''):
                    variant = v
                    break

    if variant:
        front = _as_url(variant.front_image_url)
        back = _as_url(variant.back_image_url)
        if has_app_context():
            try:
                from utils.mockups import get_mockup_url_for_variant
                app = current_app._get_current_object()
                front = get_mockup_url_for_variant(product, variant, 'front', app) or front
                back = get_mockup_url_for_variant(product, variant, 'back', app) or back
            except Exception:
                pass

    if (not front or not back) and color and getattr(product, 'style_number', None) and has_app_context():
        try:
            from utils.mockups import _find_mockup_file
            app = current_app._get_current_object()
            front = front or _find_mockup_file(app, product.style_number, color, 'front')
            back = back or _find_mockup_file(app, product.style_number, color, 'back')
            if variant and (not front or not back):
                vname = getattr(variant, 'color_name', None)
                if vname and vname != color:
                    front = front or _find_mockup_file(app, product.style_number, vname, 'front')
                    back = back or _find_mockup_file(app, product.style_number, vname, 'back')
        except Exception:
            pass

    # Only use the product-level template when no color was asked for.
    if not color:
        if not front and getattr(product, 'front_mockup_template', None):
            front = _as_url(product.front_mockup_template)
        if not back and getattr(product, 'back_mockup_template', None):
            back = _as_url(product.back_mockup_template)
    return front, back


def resolve_print_url(path_or_name):
    """Turn a stored design path or filename into a browser URL."""
    if not path_or_name or not isinstance(path_or_name, str):
        return None
    value = path_or_name.strip()
    if not value:
        return None
    if value.startswith(('http://', 'https://', '/', 'data:')):
        return value
    if '/' in value or '\\' in value:
        return _as_url(value.replace('\\', '/'))
    return f'/static/uploads/designs/{value}'


def front_print_url(item):
    design = getattr(item, 'design', None)
    if design and getattr(design, 'file_path', None):
        return resolve_print_url(design.file_path)
    if isinstance(item, dict):
        return resolve_print_url(item.get('design_url') or item.get('design_file_name'))
    return resolve_print_url(getattr(item, 'design_file_name', None))


def piece_print_url(item, piece):
    """Stored URL for one render mode. Name/number never fall back to the combined file."""
    meta = None
    details = getattr(item, 'back_design_details', None) if not isinstance(item, dict) else item
    if callable(details):
        try:
            details = details()
        except Exception:
            details = None
    meta = details if isinstance(details, dict) else {}
    if piece == 'name':
        return resolve_print_url(meta.get('name_png_url'))
    if piece == 'number':
        return resolve_print_url(meta.get('number_png_url'))
    return back_print_url(item)


def back_print_url(item):
    if isinstance(item, dict):
        return resolve_print_url(item.get('back_design_url') or item.get('back_design_file_name'))
    meta = None
    details = getattr(item, 'back_design_details', None)
    if callable(details):
        try:
            meta = details()
        except Exception:
            meta = None
    else:
        meta = details
    if isinstance(meta, dict):
        url = resolve_print_url(
            meta.get('production_png_url') or meta.get('file_url') or meta.get('url')
        )
        if url:
            return url
    return resolve_print_url(getattr(item, 'back_design_file_name', None))


def _safe_name(value, fallback='file'):
    text = re.sub(r'[^A-Za-z0-9._-]+', '-', str(value or '').strip())
    text = text.strip('-._')
    return text[:60] or fallback


def download_filename(order, item, side):
    order_no = _safe_name(getattr(order, 'order_number', None) or order.id, 'order')
    meta = getattr(item, 'back_design_details', None) or {}
    if not isinstance(meta, dict):
        meta = {}
    if side == 'back':
        name = _safe_name(meta.get('name'), '')
        number = _safe_name(meta.get('number'), '')
        label = '-'.join(part for part in (name, number) if part) or 'back'
        return f'PMKC-{order_no}-back-{label}.png'
    if side == 'back-name':
        return f'PMKC-{order_no}-name-{_safe_name(meta.get("name"), "name")}.png'
    if side == 'back-number':
        return f'PMKC-{order_no}-number-{_safe_name(meta.get("number"), "number")}.png'
    return f'PMKC-{order_no}-front.png'


def _is_composite_proof(url):
    """True when URL is a saved customer preview (shirt + design), not a raw design file."""
    if not url:
        return False
    lower = url.lower()
    return (
        '/uploads/proofs/' in lower
        or '/proofs/' in lower
        or 'proof_front_' in lower
        or 'proof_back_' in lower
    )


def preview_overlay_style(item, placement='center_chest'):
    """Match customize.html applyDesignFit / hoodieLogoScale for live admin overlays."""
    from utils.print_sizes import (
        chart_width_for_size,
        classify_age,
        get_print_width_for_size,
    )

    if isinstance(item, dict):
        size = item.get('size')
        product = item.get('product')
        print_w = item.get('print_width')
        print_h = item.get('print_height')
    else:
        size = getattr(item, 'size', None)
        product = getattr(item, 'product', None)
        print_w = getattr(item, 'print_width', None)
        print_h = getattr(item, 'print_height', None)

    placement = (placement or 'center_chest').strip().lower().replace(' ', '_')
    is_side = placement in ('left_chest', 'right_chest')

    try:
        print_w = float(print_w) if print_w is not None else None
    except (TypeError, ValueError):
        print_w = None
    try:
        print_h = float(print_h) if print_h is not None else None
    except (TypeError, ValueError):
        print_h = None

    tall = (print_h / print_w) if (print_w and print_h and print_w > 0) else 1.0
    age = classify_age(product, size) if product is not None or size else 'adult'
    cat_scale = {'baby': 0.55, 'toddler': 0.68, 'youth': 0.82}.get(age, 1.0)

    chart = chart_width_for_size(size, product) or 10.0
    ordered = print_w or get_print_width_for_size(size, product) or chart
    try:
        hoodie_scale = float(ordered) / float(chart) if chart else 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        hoodie_scale = 1.0
    hoodie_scale = max(0.55, min(hoodie_scale, 1.0))

    if is_side:
        pct, max_w, max_h = 12.0, 90.0, 18.0
        top, left = 32, 62 if placement == 'left_chest' else 38
    elif tall > 1.28:
        pct, max_w, max_h = 22.0 * cat_scale, 165.0 * cat_scale, 40.0 * cat_scale
        top, left = 38, 50
    elif tall > 1.18:
        pct, max_w, max_h = 25.0 * cat_scale, 185.0 * cat_scale, 40.0 * cat_scale
        top, left = 38, 50
    elif tall >= 0.90:
        pct, max_w, max_h = 30.0 * cat_scale, 225.0 * cat_scale, 40.0 * cat_scale
        top, left = 38, 50
    else:
        # Wide / banner logos — keep them chest-width, not full garment
        pct, max_w, max_h = 30.0 * cat_scale, 225.0 * cat_scale, 36.0 * cat_scale
        top, left = 38, 50

    pct *= hoodie_scale
    max_w *= hoodie_scale
    # Hard cap so a bad print_width cannot blow up the preview
    if is_side:
        pct = min(pct, 16.0)
        max_h = min(max_h, 20.0)
    else:
        pct = min(pct, 34.0)
        max_h = min(max_h, 42.0)

    return (
        f'width:{pct:.1f}%;max-width:{int(round(max_w))}px;max-height:{max_h:.1f}%;'
        f'top:{top}%;left:{left}%;transform:translate(-50%,-50%);'
    )


def artwork_kit(item, order=None):
    """URLs and labels for one order line: proofs + print files.

    "How they ordered it" prefers the saved customer proof images (exact shirt
    + design the buyer approved). Live mockup+overlay is only a fallback, sized
    like the customizer so logos are not blown up.
    """
    product = getattr(item, 'product', None) if not isinstance(item, dict) else None
    if isinstance(item, dict):
        color = item.get('color')
        placement = (item.get('placement') or 'center_chest')
        proof_front = _as_url(item.get('proof_front_url') or item.get('proof_image'))
        proof_back = _as_url(item.get('proof_back_url') or item.get('proof_back_image'))
    else:
        color = getattr(item, 'color', None)
        placement = (getattr(item, 'placement', None) or 'center_chest')
        proof_front = _as_url(getattr(item, 'proof_image', None))
        proof_back = _as_url(getattr(item, 'proof_back_image', None))

    if not _is_composite_proof(proof_front):
        proof_front = None
    if not _is_composite_proof(proof_back):
        proof_back = None

    front_mockup, back_mockup = mockup_urls(product, color)
    placement = placement.strip().lower().replace(' ', '_') or 'center_chest'
    front_print = front_print_url(item)
    back_print = back_print_url(item)
    front_on_shirt = placement in FRONT_PLACEMENTS
    meta = getattr(item, 'back_design_details', None) if not isinstance(item, dict) else item.get('back_design_meta')
    if callable(meta):
        try:
            meta = meta()
        except Exception:
            meta = None
    if not isinstance(meta, dict):
        meta = {}
    personalized = bool(meta.get('name') or meta.get('number'))

    if proof_front:
        front_mockup = proof_front
        front_overlay = None
        front_overlay_style = ''
    else:
        front_overlay = front_print if front_on_shirt else None
        front_overlay_style = preview_overlay_style(item, placement) if front_overlay else ''

    back_placement = 'back_name_number' if personalized else 'center_back'
    if proof_back:
        back_mockup = proof_back
        back_overlay = None
        back_overlay_style = ''
    else:
        back_overlay = back_print
        back_overlay_style = preview_overlay_style(item, 'center_back') if back_overlay and not personalized else ''

    return {
        'front_mockup_url': front_mockup,
        'back_mockup_url': back_mockup,
        'front_print_url': front_print,
        'back_print_url': back_print,
        'name_print_url': resolve_print_url(meta.get('name_png_url')),
        'number_print_url': resolve_print_url(meta.get('number_png_url')),
        'proof_front_url': proof_front,
        'proof_back_url': proof_back,
        'front_overlay_url': front_overlay,
        'back_overlay_url': back_overlay,
        'front_overlay_style': front_overlay_style,
        'back_overlay_style': back_overlay_style,
        'placement': placement,
        'back_overlay_class': back_placement,
        'is_personalized_back': personalized,
        'has_front_print': bool(front_print),
        'has_back_print': bool(back_print) or personalized,
        'has_back_proof': bool(proof_back or ((back_print or personalized) and back_mockup)),
        'used_saved_proof': bool(proof_front or proof_back),
    }


def local_file_for_url(app, url):
    """Return a filesystem Path if this URL maps to a local upload."""
    if not url:
        return None
    path = None
    if url.startswith('/static/'):
        path = Path(app.root_path) / url.lstrip('/')
    elif url.startswith('/uploads/'):
        rel = url[len('/uploads/'):]
        for base in (
            Path(app.root_path) / 'static' / 'uploads',
            Path(app.root_path) / 'uploads',
        ):
            candidate = base / rel
            if candidate.is_file():
                return candidate
        return None
    elif not url.startswith(('http://', 'https://')):
        path = Path(app.root_path) / 'static' / url.lstrip('/')
    if path and path.is_file():
        return path
    name = Path(str(url).split('?')[0]).name
    if name:
        candidate = Path(app.root_path) / 'static' / 'uploads' / 'designs' / name
        if candidate.is_file():
            return candidate
    return None


def remote_url_allowed(app, url, host_url=None):
    if not url or not url.startswith(('http://', 'https://')):
        return False
    public = (app.config.get('R2_PUBLIC_URL') or '').rstrip('/')
    if public and url.startswith(public):
        return True
    if host_url and url.startswith(host_url):
        return True
    lowered = url.lower()
    if 'r2.dev' in lowered or 'r2.cloudflarestorage.com' in lowered:
        return True
    return False
