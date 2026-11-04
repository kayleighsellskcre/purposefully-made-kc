"""Smaller copies of the big design pictures for list pages, so a page of tiles does not download many megabytes.

The stored originals are never touched. /thumb makes a small WebP copy the first time, keeps it, and sends it with a long
cache time, so Cloudflare and the browser keep it afterwards. Anything that goes wrong falls back to the original picture.
"""
import hashlib
import io
import os
import tempfile
import threading
from urllib.parse import quote, urlparse

WIDTHS = (160, 240, 320, 480, 800)
_DIR = os.path.join(tempfile.gettempdir(), 'pmkc_thumbs')
MAX_SOURCE_BYTES = 25 * 1024 * 1024
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _allowed_host(app):
    base = (app.config.get('R2_PUBLIC_URL') or '').rstrip('/')
    return urlparse(base).netloc.lower() if base else ''


def thumb_url(url, width=320):
    """The address of a small copy of a stored picture (anything we cannot shrink comes back unchanged)."""
    from flask import current_app
    if not url or not isinstance(url, str):
        return url
    host = _allowed_host(current_app)
    if not host or urlparse(url).netloc.lower() != host or not url.lower().split('?')[0].endswith(('.png', '.jpg', '.jpeg', '.webp')):
        return url
    width = min(WIDTHS, key=lambda w: abs(w - width))
    return f'/thumb?w={width}&u={quote(url, safe="")}'


def make_thumb(app, url, width):
    """Bytes of the small WebP copy, or None. Only pictures on our own storage host are ever fetched."""
    if urlparse(url).netloc.lower() != _allowed_host(app) or width not in WIDTHS:
        return None
    key = hashlib.sha256(f'{width}|{url}'.encode()).hexdigest()
    path = os.path.join(_DIR, key + '.webp')
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())      # many families asking for the same new picture make it once
    with lock:
        if os.path.exists(path):
            with open(path, 'rb') as fh:
                return fh.read()
        return _build(url, width, path)


def _build(url, width, path):
    import requests
    from PIL import Image
    resp = requests.get(url, timeout=10, stream=True)
    if resp.status_code != 200:
        return None
    raw = resp.raw.read(MAX_SOURCE_BYTES + 1, decode_content=True)
    if len(raw) > MAX_SOURCE_BYTES:
        return None
    im = Image.open(io.BytesIO(raw))
    im.load()
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGBA' if 'transparency' in im.info or im.mode in ('LA', 'P') else 'RGB')
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, 'WEBP', quality=82, method=4)
    data = out.getvalue()
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(data)
    except OSError:
        pass
    return data
