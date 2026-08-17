"""Find the garment inside a mockup photo.

The customizer draws a 2" name 2" tall, so it has to know how many preview
pixels an inch is. That number comes from the shirt in the picture, not from
the white card behind it: measure the garment silhouette, then divide its
height by the body length of the selected size (utils/print_sizes.py).

Results are fractions of the image, so the browser can scale them to whatever
size the mockup happens to be displayed at. Measuring here instead of in the
browser keeps it working for CDN-hosted mockups, which a <canvas> is not
allowed to read.
"""

import os
import threading
from urllib.parse import urlparse

from PIL import Image, ImageOps

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False


_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 1024

# Mockup hosts we already load images from.
_ALLOWED_HOSTS = frozenset((
    'cdn.ssactivewear.com',
    'cdnm.sanmar.com',
    'www.sanmar.com',
    'sanmar.com',
    'www.apparel4print.com',
    'apparel4print.com',
    'cdn.shopify.com',
))

_WORK_SIZE = 320          # silhouette detection resolution
_COLOR_DISTANCE = 40      # sum of per-channel difference from the backdrop
_MAX_BYTES = 12 * 1024 * 1024

# A detected box outside these bounds means we found the frame, a watermark, or
# nothing at all. Better to tell the browser to fall back.
_MIN_HEIGHT_FRAC = 0.25
_MAX_HEIGHT_FRAC = 0.999
_MIN_WIDTH_FRAC = 0.15


def measure(src, app=None, timeout=6.0):
    """Garment silhouette for a mockup path or URL, as image fractions."""
    src = (src or '').strip()
    if not src:
        return {'ok': False, 'reason': 'no_src'}

    with _CACHE_LOCK:
        cached = _CACHE.get(src)
    if cached is not None:
        return cached

    result = {'ok': False, 'reason': 'unreadable'}
    try:
        data = _load_bytes(src, app, timeout)
        if data:
            result = _silhouette(data)
    except Exception:
        result = {'ok': False, 'reason': 'error'}

    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[src] = result
    return result


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load_bytes(src, app, timeout):
    parsed = urlparse(src)
    if parsed.scheme in ('http', 'https'):
        if not _remote_allowed(parsed.netloc, app):
            return None
        import requests
        resp = requests.get(src, timeout=timeout, stream=True)
        resp.raise_for_status()
        ctype = (resp.headers.get('Content-Type') or '').lower()
        if ctype and not ctype.startswith('image/'):
            return None
        return resp.raw.read(_MAX_BYTES + 1, decode_content=True)[:_MAX_BYTES]
    if parsed.scheme:
        return None
    return _read_static(src, app)


def _remote_allowed(netloc, app):
    host = (netloc or '').split('@')[-1].split(':')[0].lower()
    if not host:
        return False
    if host in _ALLOWED_HOSTS:
        return True
    if any(host.endswith('.' + allowed) for allowed in _ALLOWED_HOSTS):
        return True
    public = ''
    if app is not None:
        public = (app.config.get('R2_PUBLIC_URL') or '').strip()
    if not public:
        public = (os.environ.get('R2_PUBLIC_URL') or '').strip()
    if public:
        return host == urlparse(public if '//' in public else '//' + public).netloc.lower()
    return False


def _read_static(src, app):
    """Read a same-origin /static/... mockup off disk, staying inside static/."""
    if app is None:
        return None
    rel = src.split('?', 1)[0].split('#', 1)[0].lstrip('/')
    if not rel.startswith('static/'):
        return None
    static_root = os.path.realpath(app.static_folder or os.path.join(app.root_path, 'static'))
    path = os.path.realpath(os.path.join(os.path.dirname(static_root), rel))
    if os.path.commonpath([static_root, path]) != static_root:
        return None
    if not os.path.isfile(path) or os.path.getsize(path) > _MAX_BYTES:
        return None
    with open(path, 'rb') as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _silhouette(data):
    import io

    img = Image.open(io.BytesIO(data))
    img.load()
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if not _HAS_NUMPY:
        return {'ok': False, 'reason': 'no_numpy'}

    work = img.copy()
    work.thumbnail((_WORK_SIZE, _WORK_SIZE), Image.BILINEAR)
    w, h = work.size
    if w < 32 or h < 32:
        return {'ok': False, 'reason': 'too_small'}

    mask = None
    if 'A' in work.getbands():
        alpha = np.asarray(work.getchannel('A'))
        if (alpha < 24).mean() > 0.02:
            mask = alpha > 24

    if mask is None:
        rgb = np.asarray(work.convert('RGB')).astype(np.int16)
        bg = _backdrop_color(rgb)
        dist = (np.abs(rgb[..., 0] - bg[0])
                + np.abs(rgb[..., 1] - bg[1])
                + np.abs(rgb[..., 2] - bg[2]))
        mask = dist > _COLOR_DISTANCE

    # A row belongs to the garment only if a real run of pixels differs from the
    # backdrop, so watermarks, sensor noise, and JPEG ringing do not count.
    min_run = max(2, int(round(w * 0.02)))
    rows = np.where(mask.sum(axis=1) >= min_run)[0]
    min_col_run = max(2, int(round(h * 0.02)))
    cols = np.where(mask.sum(axis=0) >= min_col_run)[0]
    if rows.size == 0 or cols.size == 0:
        return {'ok': False, 'reason': 'not_found'}

    top, bottom = int(rows[0]), int(rows[-1] + 1)
    left, right = int(cols[0]), int(cols[-1] + 1)
    height_frac = (bottom - top) / float(h)
    width_frac = (right - left) / float(w)
    if not (_MIN_HEIGHT_FRAC <= height_frac <= _MAX_HEIGHT_FRAC):
        return {'ok': False, 'reason': 'height_out_of_range', 'height': round(height_frac, 4)}
    if width_frac < _MIN_WIDTH_FRAC:
        return {'ok': False, 'reason': 'width_out_of_range', 'width': round(width_frac, 4)}

    return {
        'ok': True,
        'top': round(top / float(h), 5),
        'bottom': round(bottom / float(h), 5),
        'height': round(height_frac, 5),
        'left': round(left / float(w), 5),
        'right': round(right / float(w), 5),
        'width': round(width_frac, 5),
        'center': round(((left + right) / 2.0) / float(w), 5),
        'image_width': img.size[0],
        'image_height': img.size[1],
        'source': 'measured',
    }


def _backdrop_color(rgb):
    """Median color of the outer ring — mockups sit on a plain backdrop."""
    ring = np.concatenate([
        rgb[:2].reshape(-1, 3),
        rgb[-2:].reshape(-1, 3),
        rgb[:, :2].reshape(-1, 3),
        rgb[:, -2:].reshape(-1, 3),
    ])
    return np.median(ring, axis=0).astype(np.int16)
