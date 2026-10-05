"""True-to-garment color swatches.

Suppliers rarely send a hex code, so a color dot built from the color name is
only a guess ("Heather Bubble Gum" came out grey). The real color comes from
the manufacturer's own swatch image (SanMar COLOR_SQUARE_IMAGE) or, failing
that, from the manufacturer's flat photo of that exact shirt.
"""
import os
from functools import lru_cache

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANMAR_SWATCH_PREFIX = '/static/sanmar/front/SDL/COLOR_SQUARE_IMAGE/'
SANMAR_SWATCH_CDN = 'https://cdnm.sanmar.com/swatch/gifs/'


def local_static_path(url):
    raw = (url or '').strip()
    if not raw.startswith('/static/'):
        return None
    return os.path.join(_ROOT, *raw.lstrip('/').split('/'))


@lru_cache(maxsize=8192)
def _local_file_exists(path):
    return os.path.isfile(path)


def usable_swatch_url(url):
    """The manufacturer swatch image URL if it will load, else None."""
    raw = (url or '').strip()
    if not raw:
        return None
    if raw.startswith(('http://', 'https://')):
        return raw
    path = local_static_path(raw)
    if path and _local_file_exists(path):
        return raw
    return None


def swatch_background(hex_value, swatch_url=None):
    """Inline CSS for a color dot: real fabric image over its sampled color."""
    parts = []
    if hex_value:
        parts.append(f'background-color:{hex_value}')
    url = usable_swatch_url(swatch_url)
    if url and "'" not in url and ')' not in url:
        parts.append(f"background-image:url('{url}');background-size:cover;background-position:center")
    return ';'.join(parts)


def _open_image(source):
    from io import BytesIO
    from PIL import Image

    path = local_static_path(source)
    if path:
        if not os.path.isfile(path):
            return None
        return Image.open(path)
    if (source or '').startswith(('http://', 'https://')):
        import requests
        resp = requests.get(source, timeout=15)
        if resp.status_code != 200:
            return None
        return Image.open(BytesIO(resp.content))
    return None


def _median_hex(image):
    from PIL import Image

    img = image.convert('RGBA')
    flat = Image.new('RGBA', img.size, (255, 255, 255, 255))
    flat.alpha_composite(img)
    small = flat.convert('RGB').resize((32, 32))
    pixels = list(small.getdata())
    channels = []
    for i in range(3):
        values = sorted(p[i] for p in pixels)
        channels.append(values[len(values) // 2])
    return '#{:02x}{:02x}{:02x}'.format(*channels)


def hex_from_swatch_image(source):
    """Median color of a manufacturer fabric swatch."""
    try:
        img = _open_image(source)
        return _median_hex(img) if img is not None else None
    except Exception:
        return None


def hex_from_garment_photo(source):
    """Median color of the chest on a flat product photo of the blank shirt."""
    try:
        img = _open_image(source)
        if img is None:
            return None
        if img.format == 'JPEG':
            img.draft('RGB', (250, 250))
        w, h = img.size
        chest = img.crop((int(w * 0.38), int(h * 0.36), int(w * 0.62), int(h * 0.56)))
        return _median_hex(chest)
    except Exception:
        return None


def true_color_hex(swatch_url, front_image_url):
    """Best available real color for a variant, or None."""
    if usable_swatch_url(swatch_url):
        hex_value = hex_from_swatch_image(swatch_url)
        if hex_value:
            return hex_value
    if front_image_url and '/static/sanmar/front/SDL/' not in front_image_url:
        return hex_from_garment_photo(front_image_url)
    return None


def fill_missing_color_hex(db, ProductColorVariant, Product, *, dry_run=False, log=print):
    """Set color_hex from real images on active variants that have none.

    Never overwrites a hex a supplier already sent.
    """
    rows = (
        db.session.query(ProductColorVariant)
        .join(Product, Product.id == ProductColorVariant.product_id)
        .filter(Product.is_active.is_(True))
        .filter((ProductColorVariant.color_hex.is_(None)) | (ProductColorVariant.color_hex == ''))
        .all()
    )
    filled = 0
    for variant in rows:
        hex_value = true_color_hex(variant.color_swatch_url, variant.front_image_url)
        if not hex_value:
            continue
        filled += 1
        if not dry_run:
            variant.color_hex = hex_value
        if filled % 100 == 0:
            log(f'  {filled} colors sampled...')
            if not dry_run:
                db.session.commit()
    if not dry_run:
        db.session.commit()
    return filled, len(rows)
