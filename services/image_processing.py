"""
LOCKED — Kayleigh signed off on this cut. Do not change the algorithm
unless she explicitly asks. See .cursor/rules/background-removal.mdc.

Background removal — same-color key, nothing else.

Sample the backdrop from the border. Delete every pixel that is that
color (letter holes included). Keep every pixel that is a different
color (lavender, parchment, gold text, navy ink). Peel 1–2px of
blended fringe. Crop.

No rembg — that ate similar colors and made uploads time out.
"""

import io
import os

from PIL import Image, ImageDraw, ImageChops, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False


_SESSION_CACHE = {}
_REMBG_FAILED = False
_MODEL_PRIORITY = [
    'u2netp',            # 4 MB — boots on Railway without OOM
    'u2net',             # 180 MB — only if u2netp is missing
    'isnet-general-use', # 170 MB — too heavy to preload on small containers
]


def _get_session(model: str = 'u2net'):
    global _REMBG_FAILED
    if _REMBG_FAILED:
        return None
    if model in _SESSION_CACHE:
        return _SESSION_CACHE[model]
    try:
        from rembg import new_session
        sess = new_session(model)
        _SESSION_CACHE[model] = sess
        return sess
    except BaseException:
        return None


def _best_session():
    global _REMBG_FAILED
    if _REMBG_FAILED:
        return None, None
    preferred = os.environ.get('REMBG_MODEL', '').strip()
    order = ([preferred] + _MODEL_PRIORITY) if preferred else _MODEL_PRIORITY
    for model in order:
        sess = _get_session(model)
        if sess is not None:
            return sess, model
    _REMBG_FAILED = True
    return None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_artwork_bytes(data: bytes, mode: str = 'auto', engine=None) -> dict:
    try:
        src = Image.open(io.BytesIO(data))
        src.load()
        try:
            src = ImageOps.exif_transpose(src)
        except Exception:
            pass
    except Exception:
        return _passthrough(data)

    img = src.convert('RGBA')
    original_size = img.size

    if mode == 'none':
        return _encode(img, 'none', original_size, changed=False)

    # Already-cut PNGs: do not run the chroma-key. Converting RGBA→RGB fills
    # transparent pixels with black, and the key then keeps that fill as a
    # goofy block behind the artwork. The cut itself is unchanged.
    if _already_cutout(img):
        out = _autocrop(img)
        return _encode(out, 'preserved', original_size, changed=True)

    try:
        img, orig_rgb = _fit_working_size(img)
        bg_color, mad = _border_profile(orig_rgb)

        out = _strip_background_color(img, orig_rgb, bg_color, mad, mode)
        out = _autocrop(out)
        return _encode(out, 'algorithmic', original_size, changed=True)
    except (MemoryError, Exception):
        return _encode(img, 'none', original_size, changed=False)


def process_artwork_file(path, mode: str = 'auto', engine=None) -> dict:
    from pathlib import Path
    path = Path(path)
    if mode == 'none':
        return {
            'data': b'',
            'engine': 'none',
            'white_artwork': False,
            'validation': {'ok': True, 'issues': [], 'metrics': {}},
            'has_transparency': path.suffix.lower() in ('.png', '.webp'),
            'width': None,
            'height': None,
            'changed': False,
            'path': path,
            'filename': path.name,
        }
    try:
        data = path.read_bytes()
        result = process_artwork_bytes(data, mode=mode, engine=engine)
        png_path = path.with_suffix('.png')
        png_path.write_bytes(result['data'])
        if png_path != path and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        result['path'] = png_path
        result['filename'] = png_path.name
        return result
    except Exception:
        return {
            'data': path.read_bytes() if path.exists() else b'',
            'engine': 'none',
            'white_artwork': False,
            'validation': {'ok': True, 'issues': [], 'metrics': {}},
            'has_transparency': False,
            'width': None,
            'height': None,
            'changed': False,
            'path': path,
            'filename': path.name,
        }


def issue_messages(validation: dict) -> list:
    msgs = []
    for issue in validation.get('issues', []):
        if issue == 'background_may_remain':
            msgs.append('Some background may still be visible. Try "Reprocess" for a stronger cut.')
        elif issue == 'artwork_mostly_removed':
            msgs.append('Most of the artwork was removed — try uploading a higher-contrast version.')
        elif issue == 'low_resolution':
            msgs.append('Image resolution is low. For best print quality, use at least 300 DPI.')
    return msgs


# ---------------------------------------------------------------------------
# rembg
# ---------------------------------------------------------------------------

def _fit_working_size(img: Image.Image, max_side: int = 1600):
    w, h = img.size
    if max(w, h) <= max_side:
        return img, img.convert('RGB')
    scale = max_side / max(w, h)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    img = img.resize(new_size, Image.LANCZOS)
    return img, img.convert('RGB')


def _rembg(img_rgba: Image.Image):
    sess, _model = _best_session()
    if sess is None:
        return None
    try:
        from rembg import remove
        work = img_rgba
        orig = img_rgba.size
        if max(orig) > 1024:
            s = 1024 / max(orig)
            work = img_rgba.resize(
                (max(1, int(orig[0] * s)), max(1, int(orig[1] * s))),
                Image.LANCZOS,
            )
        out = remove(work, session=sess, alpha_matting=False, post_process_mask=False)
        if out is None:
            return None
        out = out.convert('RGBA')
        if out.size != orig:
            out = out.resize(orig, Image.LANCZOS)
        return out
    except (MemoryError, Exception):
        return None


# ---------------------------------------------------------------------------
# The cut: delete every pixel that matches the backdrop color
# ---------------------------------------------------------------------------

def _use_original_colors(orig_rgba: Image.Image, ai_rgba: Image.Image) -> Image.Image:
    """Keep the uploaded pixels; only take rembg's transparency mask."""
    if not _HAS_NUMPY:
        return ai_rgba
    o = np.asarray(orig_rgba.convert('RGBA')).copy()
    a = np.asarray(ai_rgba.convert('RGBA'))
    o[..., 3] = a[..., 3]
    return Image.fromarray(o, 'RGBA')


def _strip_background_color(img: Image.Image, orig_rgb: Image.Image,
                            bg_color, mad, mode: str) -> Image.Image:
    """Same-color key: backdrop pixels go, every other color stays."""
    if not _HAS_NUMPY:
        return img
    try:
        arr = np.asarray(img.convert('RGBA')).copy()
        rgb = np.asarray(orig_rgb.convert('RGB')).astype(np.int16)
        # Always start from the real pixels — never a rembg hole-punch.
        alpha = np.full(rgb.shape[:2], 255, dtype=np.int32)

        dist = (np.abs(rgb[..., 0] - int(bg_color[0]))
              + np.abs(rgb[..., 1] - int(bg_color[1]))
              + np.abs(rgb[..., 2] - int(bg_color[2])))

        # Tight: only the actual paper color, not nearby lavender/beige/gold.
        tol = int(min(36, max(16, 18 + mad * 1.2)))
        if mode == 'aggressive':
            tol = min(48, tol + 10)

        alpha[dist <= tol] = 0

        # 1–2px of anti-aliased cream mixed into the edge — not interiors.
        blend = dist <= (tol + 22)
        for _ in range(2):
            trans = alpha < 20
            has_t = np.zeros_like(trans)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                has_t |= np.roll(np.roll(trans, dy, axis=0), dx, axis=1)
            peel = has_t & blend & (alpha > 0)
            alpha[peel] = 0

        alpha = np.where(alpha >= 128, 255, 0).astype(np.int32)
        arr[..., 3] = alpha.astype(np.uint8)
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return img


def _flood_cut(img_rgba: Image.Image, bg_color, mad, mode: str) -> Image.Image:
    """Unused fallback kept for the public algorithmic path if rembg is gone."""
    try:
        rgb = img_rgba.convert('RGB')
        w, h = rgb.size
        tol = int(min(120, max(32, 36 + mad * 2.0)))
        if mode == 'aggressive':
            tol = min(180, tol + 50)
        work = rgb.copy()
        sentinel = (0, 254, 1)
        step = max(1, min(w, h) // 60)
        px = rgb.load()
        for x in range(0, w, step):
            for y in (0, h - 1):
                c = px[x, y]
                if abs(c[0] - bg_color[0]) + abs(c[1] - bg_color[1]) + abs(c[2] - bg_color[2]) <= tol * 3:
                    try:
                        ImageDraw.floodfill(work, (x, y), sentinel, thresh=tol)
                    except Exception:
                        pass
        for y in range(0, h, step):
            for x in (0, w - 1):
                c = px[x, y]
                if abs(c[0] - bg_color[0]) + abs(c[1] - bg_color[1]) + abs(c[2] - bg_color[2]) <= tol * 3:
                    try:
                        ImageDraw.floodfill(work, (x, y), sentinel, thresh=tol)
                    except Exception:
                        pass
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            try:
                ImageDraw.floodfill(work, corner, sentinel, thresh=tol)
            except Exception:
                pass
        r, g, b = rgb.split()
        if _HAS_NUMPY:
            wa = np.asarray(work)
            bg = ((wa[..., 0] == 0) & (wa[..., 1] == 254) & (wa[..., 2] == 1))
            alpha = np.where(bg, 0, 255).astype(np.uint8)
            arr = np.dstack([np.asarray(rgb), alpha])
            return Image.fromarray(arr, 'RGBA')
        diff = ImageChops.difference(rgb, work).convert('L')
        alpha = ImageOps.invert(diff.point(lambda p: 255 if p > 0 else 0))
        return Image.merge('RGBA', (r, g, b, alpha))
    except Exception:
        return img_rgba


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _border_profile(rgb: Image.Image):
    small = rgb.resize((80, 80))
    px = small.load()
    samples = []
    for x in range(80):
        for y in (0, 1, 78, 79):
            samples.append(px[x, y])
    for y in range(80):
        for x in (0, 1, 78, 79):
            samples.append(px[x, y])
    n = len(samples)
    rs = sorted(s[0] for s in samples)
    gs = sorted(s[1] for s in samples)
    bs = sorted(s[2] for s in samples)
    med = (rs[n // 2], gs[n // 2], bs[n // 2])
    mad = sum(abs(s[0] - med[0]) + abs(s[1] - med[1]) + abs(s[2] - med[2])
              for s in samples) / (n * 3.0)
    return med, mad


def _autocrop(img: Image.Image, padding: int = 8) -> Image.Image:
    try:
        if img.mode != 'RGBA':
            return img
        bbox = img.getchannel('A').getbbox()
        if bbox is None:
            return img
        l, t, r, b = bbox
        w, h = img.size
        return img.crop((max(0, l - padding), max(0, t - padding),
                         min(w, r + padding), min(h, b + padding)))
    except Exception:
        return img


def _has_transparency(img: Image.Image) -> bool:
    try:
        alpha = img.getchannel('A')
        if _HAS_NUMPY:
            return bool((np.asarray(alpha) < 250).mean() > 0.003)
        lo, _ = alpha.getextrema()
        return lo < 250
    except Exception:
        return False


def _already_cutout(img: Image.Image) -> bool:
    """True when the file already has a real knockout, not just edge AA.

    Paper photos stay on the chroma-key path. A few anti-aliased edge
    pixels are not enough — we need a meaningful transparent area.
    """
    try:
        if img.mode != 'RGBA':
            return False
        alpha = img.getchannel('A')
        if _HAS_NUMPY:
            return float((np.asarray(alpha) < 32).mean()) >= 0.05
        hist = alpha.histogram()
        total = sum(hist) or 1
        return (sum(hist[:32]) / total) >= 0.05
    except Exception:
        return False


def _detect_white_artwork(img: Image.Image) -> bool:
    try:
        if not _HAS_NUMPY:
            return False
        arr = np.asarray(img)
        opaque = arr[..., 3] > 128
        if opaque.sum() == 0:
            return False
        return float(arr[..., :3][opaque].mean()) > 230
    except Exception:
        return False


def _validate(img: Image.Image, original_size, changed: bool) -> dict:
    issues = []
    metrics = {}
    try:
        if not _HAS_NUMPY:
            return {'ok': True, 'issues': [], 'metrics': {}}
        alpha = np.asarray(img)[..., 3]
        total = alpha.size
        t = (alpha < 30).sum() / total
        o = (alpha > 200).sum() / total
        metrics['transparent_pct'] = round(float(t) * 100, 1)
        metrics['opaque_pct'] = round(float(o) * 100, 1)
        if changed and t < 0.03:
            issues.append('background_may_remain')
        if o < 0.02:
            issues.append('artwork_mostly_removed')
        w, h = img.size
        if w < 200 or h < 200:
            issues.append('low_resolution')
    except Exception:
        pass
    return {'ok': len(issues) == 0, 'issues': issues, 'metrics': metrics}


def _passthrough(data: bytes) -> dict:
    return {
        'data': data,
        'engine': 'none',
        'white_artwork': False,
        'validation': {'ok': True, 'issues': [], 'metrics': {}},
        'has_transparency': False,
        'width': None,
        'height': None,
        'changed': False,
    }


def _encode(img: Image.Image, engine: str, original_size, changed: bool) -> dict:
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=False)
    return {
        'data': buf.getvalue(),
        'engine': engine,
        'white_artwork': _detect_white_artwork(img),
        'validation': _validate(img, original_size, changed),
        'has_transparency': _has_transparency(img),
        'width': img.size[0],
        'height': img.size[1],
        'changed': changed,
    }
