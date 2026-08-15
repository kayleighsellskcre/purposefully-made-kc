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
    """Front and back garment photos for a product/color."""
    from models import ProductColorVariant
    front = back = None
    if not product:
        return None, None
    variant = ProductColorVariant.query.filter_by(
        product_id=product.id,
        color_name=color,
    ).first()
    if variant:
        front = _as_url(variant.front_image_url)
        back = _as_url(variant.back_image_url)
    if not front and getattr(product, 'style_number', None):
        color_slug = (color or '').replace(' ', '_')
        style = product.style_number
        front = f'/uploads/mockups/{style}/{style}_{color_slug}_front.jpg'
        back = back or f'/uploads/mockups/{style}/{style}_{color_slug}_back.jpg'
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
        url = resolve_print_url(meta.get('file_url') or meta.get('url'))
        if url:
            return url
    return resolve_print_url(getattr(item, 'back_design_file_name', None))


def _safe_name(value, fallback='file'):
    text = re.sub(r'[^A-Za-z0-9._-]+', '-', str(value or '').strip())
    text = text.strip('-._')
    return text[:60] or fallback


def download_filename(order, item, side):
    order_no = _safe_name(getattr(order, 'order_number', None) or order.id, 'order')
    if side == 'back':
        meta = getattr(item, 'back_design_details', None) or {}
        if not isinstance(meta, dict):
            meta = {}
        name = _safe_name(meta.get('name'), '')
        number = _safe_name(meta.get('number'), '')
        label = '-'.join(part for part in (name, number) if part) or 'back'
        return f'PMKC-{order_no}-back-{label}.png'
    return f'PMKC-{order_no}-front.png'


def artwork_kit(item, order=None):
    """URLs and labels for one order line: proofs + print files."""
    product = getattr(item, 'product', None)
    color = getattr(item, 'color', None)
    front_mockup, back_mockup = mockup_urls(product, color)
    placement = (getattr(item, 'placement', None) or 'center_chest').strip().lower().replace(' ', '_') or 'center_chest'
    front_print = front_print_url(item)
    back_print = back_print_url(item)
    front_on_shirt = placement in FRONT_PLACEMENTS
    return {
        'front_mockup_url': front_mockup,
        'back_mockup_url': back_mockup,
        'front_print_url': front_print,
        'back_print_url': back_print,
        'front_overlay_url': front_print if front_on_shirt else None,
        'back_overlay_url': back_print,
        'placement': placement,
        'has_front_print': bool(front_print),
        'has_back_print': bool(back_print),
        'has_back_proof': bool(back_print and back_mockup),
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
