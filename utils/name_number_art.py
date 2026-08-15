"""Split a combined back name/number PNG into two transfer files."""
from io import BytesIO

from PIL import Image


def _trim(image):
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    bbox = image.getbbox()
    if not bbox:
        return image
    return image.crop(bbox)


def _load_combined(app, item):
    from flask import request
    from urllib.request import Request, urlopen
    from utils.order_artwork import back_print_url, local_file_for_url, remote_url_allowed

    url = back_print_url(item)
    if not url:
        return None
    local = local_file_for_url(app, url)
    if local:
        with Image.open(local) as img:
            return img.convert('RGBA')
    fetch_url = url
    if url.startswith('/'):
        fetch_url = request.host_url.rstrip('/') + url
    if fetch_url.startswith(('http://', 'https://')) and (
        remote_url_allowed(app, fetch_url, request.host_url) or url.startswith('/')
    ):
        req = Request(fetch_url, headers={'User-Agent': 'PMKC-Admin/1.0'})
        with urlopen(req, timeout=20) as resp:
            data = resp.read()
        with Image.open(BytesIO(data)) as img:
            return img.convert('RGBA')
    return None


def _crop_piece(image, back, piece):
    combined = float(back.get('combined_height') or 0)
    name_h = float(back.get('name_height') or 0)
    number_h = float(back.get('number_height') or 0)
    if combined <= 0 or image.height <= 0:
        return None
    width, height = image.size
    if piece == 'name':
        if name_h <= 0:
            return None
        cut = max(1, int(round(height * (name_h / combined))))
        return _trim(image.crop((0, 0, width, min(height, cut))))
    if piece == 'number':
        if number_h <= 0:
            return None
        cut = max(1, int(round(height * (number_h / combined))))
        top = max(0, height - cut)
        return _trim(image.crop((0, top, width, height)))
    return None


def personalized_png(app, item, piece, customer_name=None):
    """Return PNG bytes for the name or number transfer, or None."""
    from utils.print_sizes import production_from_order_item

    if piece not in ('name', 'number'):
        return None
    prod = production_from_order_item(item, customer_name=customer_name)
    back = (prod or {}).get('back') or {}
    text = (back.get(piece) or '').strip()
    if not text:
        return None
    try:
        combined = _load_combined(app, item)
    except Exception:
        combined = None
    if combined is not None:
        cropped = _crop_piece(combined, back, piece)
        if cropped and cropped.getbbox():
            buf = BytesIO()
            cropped.save(buf, format='PNG')
            return buf.getvalue()
    return _render_fallback(text, back, piece)


def _render_fallback(text, back, piece):
    from PIL import ImageDraw, ImageFont

    height_in = float(back.get(f'{piece}_height') or (2 if piece == 'name' else 7))
    scale_x = float(back.get('number_scale') or 1) if piece == 'number' else 1
    color = (back.get('text_color') or '#ffffff').strip()
    if color.startswith('#') and len(color) == 7:
        fill = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    else:
        fill = (255, 255, 255, 255)
    px = max(48, int(height_in * 300))
    font = None
    for candidate in ('DejaVuSans-Bold.ttf', 'arialbd.ttf', 'Arial Bold.ttf', 'arial.ttf'):
        try:
            font = ImageFont.truetype(candidate, px)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    dummy = Image.new('RGBA', (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = max(1, bbox[2] - bbox[0])
    height = max(1, bbox[3] - bbox[1])
    pad = max(8, px // 10)
    image = Image.new('RGBA', (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=fill)
    if 0 < scale_x < 1:
        image = image.resize((max(1, int(image.width * scale_x)), image.height), Image.Resampling.LANCZOS)
    buf = BytesIO()
    _trim(image).save(buf, format='PNG')
    return buf.getvalue()
