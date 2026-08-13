"""
Background removal — clean rewrite.

Keep the design. Delete the background. Nothing else.

  1. rembg produces a first-pass cutout
  2. Sample the background color from the photo's border
  3. Every pixel that matches that color becomes transparent
     (this is what kills cream/white/black boxes and halos)
  4. Grow from already-transparent pixels into leftover fringe
  5. Hard edges + crop

Public API is unchanged so the rest of the app does not care.
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

    # Phone photos can be 4000px+; rembg on those OOMs Railway and the
    # upload looks like it "failed". Cap the working size.
    try:
        img, orig_rgb = _fit_working_size(img)
        bg_color, mad = _border_profile(orig_rgb)

        out = None
        used = 'none'
        rembg_alpha = None
        if engine != 'algorithmic':
            ai = _rembg(img)
            if ai is not None:
                out = _use_original_colors(img, ai)
                used = 'ai'
                if _HAS_NUMPY:
                    rembg_alpha = np.asarray(ai.convert('RGBA'))[..., 3]
        if out is None:
            out = _flood_cut(img, bg_color, mad, mode)
            used = 'algorithmic'

        interior_bg = _HAS_NUMPY and _looks_like_interior_bg_art(orig_rgb, bg_color, mad)
        out = _strip_background_color(out, orig_rgb, bg_color, mad, mode,
                                      rembg_alpha=rembg_alpha,
                                      preserve_interior=interior_bg)
        # GAME DAY only: if the default still ate interior outlines/field
        # lines, swap in the border-flood preserve. Simple logos never
        # enter this branch.
        if interior_bg:
            fallback = _border_connected_preserve(img, orig_rgb, bg_color, mad)
            if _fallback_keeps_more_interior(out, fallback):
                out = fallback
        out = _autocrop(out)
        return _encode(out, used, original_size, changed=True)
    except (MemoryError, Exception):
        return _encode(img, 'none', original_size, changed=False)


def process_artwork_file(path, mode: str = 'auto', engine=None) -> dict:
    from pathlib import Path
    path = Path(path)
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
    """Downscale huge uploads so rembg fits in Railway RAM and finishes in time."""
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


def _use_original_colors(orig_rgba: Image.Image, ai_rgba: Image.Image) -> Image.Image:
    """Keep the uploaded pixels; only take rembg's transparency mask."""
    if not _HAS_NUMPY:
        return ai_rgba
    o = np.asarray(orig_rgba.convert('RGBA')).copy()
    a = np.asarray(ai_rgba.convert('RGBA'))
    o[..., 3] = a[..., 3]
    return Image.fromarray(o, 'RGBA')


# ---------------------------------------------------------------------------
# The actual cut: delete the background color
# ---------------------------------------------------------------------------

def _dilate_bool(mask, px: int, diagonal: bool = False):
    out = mask.copy()
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if diagonal:
        offsets += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    for _ in range(max(0, int(px))):
        d = out.copy()
        for dy, dx in offsets:
            d |= np.roll(np.roll(out, dy, axis=0), dx, axis=1)
        out = d
    return out


def _erode_bool(mask, px: int, diagonal: bool = False):
    return ~_dilate_bool(~mask, px, diagonal=diagonal)


def _close_bool(mask, px: int, diagonal: bool = False):
    """Fill gaps up to ~2*px without growing the silhouette."""
    return _erode_bool(_dilate_bool(mask, px, diagonal=diagonal), px, diagonal=diagonal)


def _flood_from_border(seedable):
    """True on pixels reachable from the image border through seedable."""
    from collections import deque
    h, w = seedable.shape
    exterior = np.zeros((h, w), dtype=bool)
    q = deque()

    def seed(y, x):
        if not exterior[y, x] and seedable[y, x]:
            exterior[y, x] = True
            q.append((y, x))

    for x in range(w):
        seed(0, x)
        seed(h - 1, x)
    for y in range(h):
        seed(y, 0)
        seed(y, w - 1)
    while q:
        y, x = q.popleft()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not exterior[ny, nx] and seedable[ny, nx]:
                exterior[ny, nx] = True
                q.append((ny, nx))
    return exterior


def _iter_bool_components(mask):
    h, w = mask.shape
    visited = np.zeros((h, w), dtype=bool)
    ys, xs = np.where(mask)
    for y0, x0 in zip(ys, xs):
        if visited[y0, x0]:
            continue
        comp = [(y0, x0)]
        visited[y0, x0] = True
        qi = 0
        while qi < len(comp):
            y, x = comp[qi]
            qi += 1
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and mask[ny, nx]:
                    visited[ny, nx] = True
                    comp.append((ny, nx))
        yield comp


def _comp_is_thin_or_ring(comp):
    """Field lines, white outlines, and stroke rings — keep these."""
    n = len(comp)
    if n < 12:
        return False
    ys = [p[0] for p in comp]
    xs = [p[1] for p in comp]
    bh = max(ys) - min(ys) + 1
    bw = max(xs) - min(xs) + 1
    aspect = max(bh, bw) / max(1.0, min(bh, bw))
    if aspect >= 5:
        return True
    fill = n / max(1.0, bh * bw)
    return fill < 0.32 and max(bh, bw) >= 10


def _comp_ring_mostly_logo(comp, is_logo):
    """True when this blob sits in a letter counter (surrounded by ink)."""
    n = len(comp)
    if n > 8000:
        return False
    h, w = is_logo.shape
    cset = set(comp)
    logo_n = other = 0
    for y, x in comp:
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + dy, x + dx
            if not (0 <= ny < h and 0 <= nx < w) or (ny, nx) in cset:
                continue
            if is_logo[ny, nx]:
                logo_n += 1
            else:
                other += 1
    return logo_n > 8 and logo_n >= 2.5 * max(1, other)


def _strip_background_color(img: Image.Image, orig_rgb: Image.Image,
                            bg_color, mad, mode: str, rembg_alpha=None,
                            preserve_interior: bool = False) -> Image.Image:
    """Keep every logo-colored pixel. Delete the backdrop color.

    Default (preserve_interior=False): punch letter counters, kill ghost
    rectangles, keep large enclosed art (cream shapes, parchment) and
    thin structures rembg marked as foreground (small white text).

    GAME DAY path (preserve_interior=True): also seal distressed interiors
    so cream specks inside a painted field are not swiss-cheesed.
    """
    if not _HAS_NUMPY:
        return img
    try:
        arr = np.asarray(img.convert('RGBA')).copy()
        rgb = np.asarray(orig_rgb.convert('RGB')).astype(np.int16)
        alpha = arr[..., 3].astype(np.int32)

        dist = (np.abs(rgb[..., 0] - int(bg_color[0]))
              + np.abs(rgb[..., 1] - int(bg_color[1]))
              + np.abs(rgb[..., 2] - int(bg_color[2])))

        tol = int(min(58, max(28, 32 + mad * 1.4)))
        if mode == 'aggressive':
            tol = min(80, tol + 18)

        is_bg = dist <= tol
        is_logo = dist > tol

        alpha[is_logo] = 255

        rembg_a = None
        rembg_fg = None
        if rembg_alpha is not None:
            rembg_a = np.asarray(rembg_alpha)
            if rembg_a.ndim == 3:
                rembg_a = rembg_a[..., 3] if rembg_a.shape[-1] >= 4 else rembg_a[..., 0]
            if rembg_a.shape[:2] == alpha.shape:
                rembg_fg = rembg_a >= 140
                # Protect colored art and thin white text/outlines. Do NOT
                # protect fat paper-colored blobs — those are letter holes
                # rembg failed to punch, or a ghost rectangle.
                thin_bg_fg = rembg_fg & is_bg & ~_erode_bool(rembg_fg & is_bg, 2)
                protect_fg = (rembg_fg & ~is_bg) | thin_bg_fg
                alpha[protect_fg] = 255
            else:
                rembg_a = None
                rembg_fg = None
                protect_fg = None
        else:
            protect_fg = None

        if protect_fg is not None:
            protected = is_logo | protect_fg
        else:
            protected = is_logo
        protected = _erode_bool(_dilate_bool(protected, 2), 1)

        logo_solid = None
        heal = np.zeros(alpha.shape, dtype=bool)
        if preserve_interior:
            logo_solid = _close_bool(is_logo, 3, diagonal=True)

        h, w = alpha.shape
        floodable = is_bg & ~protected
        if logo_solid is not None:
            floodable = floodable & ~logo_solid
        if rembg_a is not None:
            # Ghost rectangles rembg leaves at alpha ~20–90
            floodable = floodable | ((rembg_a < 96) & ~protected)

        exterior = _flood_from_border(floodable)
        # Grow from already-transparent pixels into leftover canvas
        trans = alpha < 20
        if trans.any():
            extra = _dilate_bool(trans, 1) & floodable & ~exterior
            if extra.any():
                from collections import deque
                q = deque()
                ys, xs = np.where(extra)
                for y, x in zip(ys, xs):
                    exterior[y, x] = True
                    q.append((y, x))
                while q:
                    y, x = q.popleft()
                    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w and not exterior[ny, nx] and floodable[ny, nx]:
                            exterior[ny, nx] = True
                            q.append((ny, nx))

        alpha[exterior] = 0

        enclosed = is_bg & ~exterior
        alpha[enclosed] = 255
        if logo_solid is not None:
            heal = logo_solid & enclosed
            if protect_fg is not None:
                heal = heal & ~protect_fg
            alpha[heal] = 255

        max_letter_hole = max(500, (h * w) // 90)
        punchable = enclosed & ~heal
        for comp in _iter_bool_components(punchable):
            n = len(comp)
            if n > max_letter_hole:
                continue
            if _comp_is_thin_or_ring(comp):
                continue
            # Letter counters: compact blobs wrapped in ink. Pattern fills
            # (checkered heart) have mixed neighbors and stay.
            if _comp_ring_mostly_logo(comp, is_logo):
                for y, x in comp:
                    alpha[y, x] = 0

        fg = alpha >= 128
        fg = _erode_bool(_dilate_bool(fg, 1), 1)
        alpha = np.where(fg, 255, 0).astype(np.int32)

        halo_tol = tol + 34
        is_halo = dist <= halo_tol
        for _ in range(2):
            trans = alpha < 20
            has_t = _dilate_bool(trans, 1)
            peel = has_t & is_halo & (alpha > 0) & ~protected
            if rembg_a is not None:
                peel = peel & (rembg_a < 80)
            alpha[peel] = 0

        # Kill rembg ghost boxes (semi-transparent gray rectangles)
        alpha[alpha < 40] = 0

        opaque = alpha >= 128
        rgb_out = arr[..., :3].copy()
        if heal.any():
            filled = is_logo.copy()
            for _ in range(8):
                for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
                    nb_f = np.roll(filled, shift, axis=axis)
                    nb_c = np.roll(rgb_out, shift, axis=axis)
                    take = heal & opaque & (~filled) & nb_f
                    if take.any():
                        rgb_out[take] = nb_c[take]
                        filled |= take
        filled = opaque.copy()
        for _ in range(4):
            for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
                nb_f = np.roll(filled, shift, axis=axis)
                nb_c = np.roll(rgb_out, shift, axis=axis)
                take = (~filled) & nb_f
                if take.any():
                    rgb_out[take] = nb_c[take]
                    filled |= take
        arr[..., :3] = rgb_out
        arr[..., 3] = alpha.clip(0, 255).astype(np.uint8)
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return img


def _bg_tol(mad, mode: str) -> int:
    tol = int(min(58, max(28, 32 + mad * 1.4)))
    if mode == 'aggressive':
        tol = min(80, tol + 18)
    return tol


def _looks_like_interior_bg_art(orig_rgb: Image.Image, bg_color, mad) -> bool:
    """GAME DAY-style: paper color used as thin interior art (outlines, field lines).

    Simple logos on a white canvas do NOT match — their enclosed paper
    pixels are compact letter counters, not thin strokes.
    """
    if not _HAS_NUMPY or mad > 22:
        return False
    try:
        rgb = np.asarray(orig_rgb.convert('RGB')).astype(np.int16)
        h, w = rgb.shape[:2]
        dist = (np.abs(rgb[..., 0] - int(bg_color[0]))
              + np.abs(rgb[..., 1] - int(bg_color[1]))
              + np.abs(rgb[..., 2] - int(bg_color[2])))
        tol = _bg_tol(mad, 'auto')
        is_bg = dist <= tol
        margin = max(8, min(h, w) // 20)
        border = np.zeros((h, w), dtype=bool)
        border[:margin, :] = True
        border[-margin:, :] = True
        border[:, :margin] = True
        border[:, -margin:] = True
        if float(is_bg[border].mean()) < 0.72:
            return False
        exterior = _flood_from_border(is_bg)
        enclosed = is_bg & ~exterior
        if not enclosed.any():
            return False
        thin = 0
        for comp in _iter_bool_components(enclosed):
            if _comp_is_thin_or_ring(comp):
                thin += len(comp)
        return thin >= max(500, int(h * w * 0.004))
    except Exception:
        return False


def _border_connected_preserve(orig_rgba: Image.Image, orig_rgb: Image.Image,
                               bg_color, mad) -> Image.Image:
    """Remove only backdrop that touches the image border.

    Enclosed paper-colored art (outlines, field lines, falcon white, cream
    highlights) stays. Tiny distress specks inside painted regions are
    healed. True letter counters still punch through to the shirt.
    """
    if not _HAS_NUMPY:
        return orig_rgba
    try:
        from collections import deque
        arr = np.asarray(orig_rgba.convert('RGBA')).copy()
        rgb = np.asarray(orig_rgb.convert('RGB')).astype(np.int16)
        h, w = rgb.shape[:2]
        dist = (np.abs(rgb[..., 0] - int(bg_color[0]))
              + np.abs(rgb[..., 1] - int(bg_color[1]))
              + np.abs(rgb[..., 2] - int(bg_color[2])))
        tol = _bg_tol(mad, 'auto')
        is_bg = dist <= tol
        is_logo = dist > tol
        alpha = np.full((h, w), 255, dtype=np.int32)
        alpha[is_logo] = 255

        logo_solid = _close_bool(is_logo, 3, diagonal=True)
        floodable = is_bg & ~logo_solid
        exterior = np.zeros((h, w), dtype=bool)
        q = deque()

        def seed(y, x):
            if not exterior[y, x] and floodable[y, x]:
                exterior[y, x] = True
                q.append((y, x))

        for x in range(w):
            seed(0, x)
            seed(h - 1, x)
        for y in range(h):
            seed(y, 0)
            seed(y, w - 1)

        while q:
            y, x = q.popleft()
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not exterior[ny, nx] and floodable[ny, nx]:
                    exterior[ny, nx] = True
                    q.append((ny, nx))

        alpha[exterior] = 0
        enclosed = is_bg & ~exterior
        alpha[enclosed] = 255
        heal = logo_solid & enclosed
        alpha[heal] = 255

        max_letter_hole = max(500, (h * w) // 90)
        punchable = enclosed & ~heal
        for comp in _iter_bool_components(punchable):
            n = len(comp)
            if n > max_letter_hole:
                continue
            if _comp_is_thin_or_ring(comp):
                continue
            if _comp_ring_mostly_logo(comp, is_logo):
                for y, x in comp:
                    alpha[y, x] = 0

        fg = alpha >= 128
        fg = _erode_bool(_dilate_bool(fg, 1), 1)
        alpha = np.where(fg, 255, 0).astype(np.int32)

        is_halo = dist <= (tol + 34)
        for _ in range(2):
            trans = alpha < 20
            has_t = _dilate_bool(trans, 1)
            peel = has_t & is_halo & (alpha > 0) & ~logo_solid
            alpha[peel] = 0
        alpha[alpha < 40] = 0

        opaque = alpha >= 128
        rgb_out = arr[..., :3].copy()
        filled = is_logo.copy()
        for _ in range(8):
            for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
                nb_f = np.roll(filled, shift, axis=axis)
                nb_c = np.roll(rgb_out, shift, axis=axis)
                take = heal & opaque & (~filled) & nb_f
                if take.any():
                    rgb_out[take] = nb_c[take]
                    filled |= take
        arr[..., :3] = rgb_out
        arr[..., 3] = alpha.clip(0, 255).astype(np.uint8)
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return orig_rgba


def _fallback_keeps_more_interior(default_img: Image.Image,
                                  fallback_img: Image.Image) -> bool:
    """Accept fallback only if it restored a meaningful chunk of interior art."""
    if not _HAS_NUMPY:
        return False
    try:
        d = np.asarray(default_img.convert('RGBA'))[..., 3]
        f = np.asarray(fallback_img.convert('RGBA'))[..., 3]
        if d.shape != f.shape:
            return False
        restored = (d < 128) & (f >= 128)
        n = restored.sum()
        area = d.size
        return int(n) >= max(800, int(area * 0.008))
    except Exception:
        return False


def _flood_cut(img_rgba: Image.Image, bg_color, mad, mode: str) -> Image.Image:
    """Fallback when rembg is missing: flood-fill from the border."""
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
