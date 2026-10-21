"""Width and height for a picture printed on the back of a shirt, so you know what size to order.

The width comes from the same size chart as every other transfer; the height follows the picture's own shape.
The picture's shape is read once from the file and remembered on the order line, so pages stay quick.
"""
import io
import json
from urllib.request import Request, urlopen

from flask import current_app

from models import db
from utils.order_artwork import back_print_url, local_file_for_url, remote_url_allowed
from utils.print_sizes import front_transfer_size, inches

MAX_BYTES = 12 * 1024 * 1024


def _read_size(url):
    """(width, height) in pixels of the picture at this URL, or None."""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        local = local_file_for_url(current_app, url)
        if local:
            with Image.open(local) as img:
                return img.size
        if url and url.startswith(('http://', 'https://')) and remote_url_allowed(current_app, url):
            req = Request(url, headers={'User-Agent': 'PMKC-Admin/1.0'})
            with urlopen(req, timeout=8) as resp:
                data = resp.read(MAX_BYTES)
            with Image.open(io.BytesIO(data)) as img:
                return img.size
    except Exception:
        current_app.logger.warning('could not read back picture size for %s', url)
    return None


def aspect_for(item, remember=True):
    """(w, h) shape of the item's back picture; reads the file the first time, then remembers it."""
    meta = dict(item.back_design_details or {})
    if meta.get('aspect_w') and meta.get('aspect_h'):
        return meta['aspect_w'], meta['aspect_h']
    size = _read_size(back_print_url(item))
    if not size or not size[0] or not size[1]:
        return None
    if remember:
        try:
            meta['aspect_w'], meta['aspect_h'] = int(size[0]), int(size[1])
            item.back_design_meta = json.dumps(meta)
            db.session.commit()
        except Exception:
            db.session.rollback()
    return size


def back_logo_dims(item):
    """{'width','height','width_display','height_display','exceeds_safe_area','known'} for a back picture."""
    aw, ah = (aspect_for(item) or (None, None))
    chart = front_transfer_size(item.size, getattr(item, 'product', None), 'center_back', aw, ah)
    known = bool(aw and ah)
    return {
        'width': chart['width'], 'height': chart['height'] if known else None,
        'width_display': inches(chart['width']), 'height_display': inches(chart['height']) if known else None,
        'exceeds_safe_area': chart['exceeds_safe_area'] if known else False, 'known': known,
    }
