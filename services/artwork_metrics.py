"""Visible (non-transparent) width of gallery artwork.

The customizer sizes logos from the shirt in the mockup photo, then stretches
the layer so the *ink* is 38% of that shirt. Transparent padding in the PNG
would otherwise make the art look tiny. Measuring here, once per design, lets
the first click use the final size instead of guessing in the browser and
snapping later.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 2048
_MAX_BYTES = 12 * 1024 * 1024
_SAMPLE = 256
_ALPHA_CUTOFF = 20


def visible_width_ratio(data):
    """Fraction of image width that contains ink. 1.0 means edge-to-edge art."""
    if not data:
        return 1.0
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert('RGBA')
        img.thumbnail((_SAMPLE, _SAMPLE), Image.BILINEAR)
        width, height = img.size
        if width < 2 or height < 2:
            return 1.0
        alpha = img.getchannel('A')
        min_x = width
        max_x = -1
        pixels = alpha.getdata()
        for index, value in enumerate(pixels):
            if value > _ALPHA_CUTOFF:
                x = index % width
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
        if max_x < min_x:
            return 1.0
        return min(1.0, max(0.2, (max_x - min_x + 1) / float(width)))
    except Exception:
        return 1.0


def _design_key(design):
    if design is None or getattr(design, 'id', None) is None:
        return None
    return (int(design.id), (design.file_path or ''))


def peek_cached(design):
    """In-memory ratio if this design was already measured. None otherwise."""
    key = _design_key(design)
    if key is None:
        return None
    with _CACHE_LOCK:
        return _CACHE.get(key)


def measure_design(design, app=None):
    """Cached visible-width ratio for one Design row."""
    key = _design_key(design)
    if key is None:
        return 1.0
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached

    ratio = visible_width_ratio(_load_design_bytes(design, app))
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = ratio
    return ratio


def _unwrap_app(app):
    """Flask's current_app proxy cannot be used from worker threads."""
    getter = getattr(app, '_get_current_object', None)
    if callable(getter):
        try:
            return getter()
        except RuntimeError:
            return None
    return app


def measure_designs(designs, app=None, max_workers=4):
    """Measure several designs, using threads so one slow file cannot stall the rest."""
    app = _unwrap_app(app)
    rows = [design for design in (designs or []) if design is not None]
    if not rows:
        return {}
    if len(rows) == 1 or max_workers <= 1:
        return {str(design.id): measure_design(design, app) for design in rows}

    from concurrent.futures import ThreadPoolExecutor

    def work(design):
        if app is not None:
            with app.app_context():
                return design.id, measure_design(design, app)
        return design.id, measure_design(design, app)

    fits = {}
    workers = min(max_workers, len(rows))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for design_id, ratio in pool.map(work, rows):
            fits[str(design_id)] = ratio
    return fits


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def _load_design_bytes(design, app):
    source = (getattr(design, 'file_path', None) or '').strip()
    if not source or app is None:
        return None
    try:
        from utils.order_artwork import local_file_for_url
        local = local_file_for_url(app, source)
        if local and local.is_file() and local.stat().st_size <= _MAX_BYTES:
            return local.read_bytes()
    except Exception:
        pass

    candidates = []
    if source.startswith('/static/'):
        candidates.append(Path(app.root_path) / source.lstrip('/'))
    elif not source.startswith(('http://', 'https://')):
        candidates.append(Path(app.root_path) / 'static' / source.lstrip('/'))
        candidates.append(Path(app.root_path) / 'static' / 'uploads' / 'designs' / Path(source).name)
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size <= _MAX_BYTES:
                return path.read_bytes()
        except OSError:
            continue

    if source.startswith(('http://', 'https://')):
        try:
            from utils.order_artwork import remote_url_allowed
            if not remote_url_allowed(app, source):
                return None
            import requests
            resp = requests.get(source, timeout=8, stream=True)
            resp.raise_for_status()
            return resp.raw.read(_MAX_BYTES + 1, decode_content=True)[:_MAX_BYTES]
        except Exception:
            return None
    return None
