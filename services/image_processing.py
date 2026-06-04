"""
Artwork background removal + validation pipeline.

Goal: turn an uploaded logo / graphic / artwork into a clean, true-transparent
PNG with crisp, print-ready edges — without manual Photoshop cleanup.

Engines (hybrid):
  * Algorithmic (default, no extra services): edge-seeded flood fill so the
    background is removed while interior detail (including white areas of the
    art itself) is preserved, plus colour-bleed defringe and anti-aliased edges.
  * AI (rembg / U2Net-isnet), enabled with env AI_BG_REMOVAL=1. Best for busy
    or photographic backgrounds and fine detail (hair). Falls back to the
    algorithmic engine automatically if rembg is unavailable or errors.

Also detects predominantly-white artwork (so the UI can preview it on a
contrasting background) and validates the result (leftover background, missing
artwork, low resolution, soft edges) so the user can choose to reprocess.

Every public function is defensive: on any failure it returns the image as a
plain transparent-capable PNG rather than raising, so uploads never break.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageOps

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:  # pragma: no cover - numpy ships with rembg, but stay safe
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------

_REMBG_SESSION = None
_REMBG_FAILED = False


def ai_enabled():
    """True when the AI engine is turned on via environment."""
    return str(os.environ.get('AI_BG_REMOVAL', '')).strip().lower() in (
        '1', 'true', 'yes', 'on'
    )


def _get_rembg_session():
    """Lazily create and cache a single rembg session for this process."""
    global _REMBG_SESSION, _REMBG_FAILED
    if _REMBG_FAILED:
        return None
    if _REMBG_SESSION is not None:
        return _REMBG_SESSION
    try:
        from rembg import new_session
        model = os.environ.get('REMBG_MODEL', 'isnet-general-use')
        _REMBG_SESSION = new_session(model)
        return _REMBG_SESSION
    except Exception:
        _REMBG_FAILED = True
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_artwork_bytes(data, mode='auto', engine=None):
    """Process raw image bytes.

    Args:
        data: image file bytes.
        mode: 'auto' | 'aggressive' | 'none'.
        engine: None (auto-select), 'ai', or 'algorithmic'.

    Returns dict:
        data:          processed PNG bytes (always a PNG)
        engine:        engine actually used
        white_artwork: bool, predominantly-white art
        validation:    dict with ok/issues/metrics
        width, height: pixels
        changed:       bool, whether anything was removed
    """
    try:
        src = Image.open(io.BytesIO(data))
        src.load()
    except Exception:
        # Not a decodable image — hand bytes back untouched.
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

    img = src.convert('RGBA')
    original_size = img.size

    result_engine = 'none'
    changed = False

    if mode == 'none':
        out = img
    else:
        # If the art already has a real transparent background, keep it.
        if _already_transparent(img):
            out = _cleanup_existing_alpha(img)
            result_engine = 'preserved'
            changed = True
        else:
            out = None
            want = engine or ('ai' if ai_enabled() else 'algorithmic')
            if want == 'ai':
                out = _remove_bg_ai(img)
                if out is not None:
                    out = _defringe(out)
                    result_engine = 'ai'
                    changed = True
            if out is None:
                out = _remove_bg_algorithmic(img, mode=mode)
                result_engine = 'algorithmic'
                changed = True

    white_artwork = _detect_white_artwork(out)
    validation = _validate(out, original_size, changed)
    has_transparency = _has_transparency(out)

    buf = io.BytesIO()
    out.save(buf, 'PNG', optimize=True)
    return {
        'data': buf.getvalue(),
        'engine': result_engine,
        'white_artwork': white_artwork,
        'validation': validation,
        'has_transparency': has_transparency,
        'width': out.size[0],
        'height': out.size[1],
        'changed': changed,
    }


def process_artwork_file(path, mode='auto', engine=None):
    """Process an image on disk in place, writing a transparent PNG.

    Returns the same dict as ``process_artwork_bytes`` plus:
        path:     pathlib.Path of the written PNG
        filename: its filename
    Falls back to leaving the original file untouched on error.
    """
    from pathlib import Path
    path = Path(path)
    try:
        with open(path, 'rb') as f:
            data = f.read()
        result = process_artwork_bytes(data, mode=mode, engine=engine)

        png_path = path.with_suffix('.png')
        with open(png_path, 'wb') as f:
            f.write(result['data'])
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
            'data': None,
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


# ---------------------------------------------------------------------------
# AI engine (rembg)
# ---------------------------------------------------------------------------

def _remove_bg_ai(img_rgba):
    session = _get_rembg_session()
    if session is None:
        return None
    try:
        from rembg import remove
        out = remove(
            img_rgba,
            session=session,
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=15,
            alpha_matting_erode_size=3,
            post_process_mask=True,
        )
        return out.convert('RGBA')
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Algorithmic engine
# ---------------------------------------------------------------------------

def _already_transparent(img):
    """True if the image already has a meaningful transparent background."""
    try:
        alpha = img.getchannel('A')
    except Exception:
        return False
    lo, hi = alpha.getextrema()
    if lo >= 250:
        return False  # effectively fully opaque
    # Sample the border on a small thumbnail; mostly-transparent border == cut out
    small = alpha.resize((64, 64))
    px = small.load()
    border_vals = []
    for x in range(64):
        border_vals.append(px[x, 0])
        border_vals.append(px[x, 63])
    for y in range(64):
        border_vals.append(px[0, y])
        border_vals.append(px[63, y])
    transparent_border = sum(1 for v in border_vals if v < 40) / len(border_vals)
    return transparent_border > 0.6


def _cleanup_existing_alpha(img):
    """Lightly anti-alias / clean an already-transparent image."""
    try:
        r, g, b, a = img.split()
        a = a.filter(ImageFilter.GaussianBlur(0.4))
        return Image.merge('RGBA', (r, g, b, a))
    except Exception:
        return img


def _border_profile(rgb):
    """Estimate background colour + uniformity from a thumbnail border ring."""
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
    # mean absolute deviation as a uniformity measure
    mad = sum(abs(s[0] - med[0]) + abs(s[1] - med[1]) + abs(s[2] - med[2])
              for s in samples) / (n * 3.0)
    return med, mad


def _remove_bg_algorithmic(img_rgba, mode='auto'):
    """Edge-seeded flood-fill background removal.

    The background is the region *connected to the image border*, found by
    flood-filling from seeds placed all the way around the perimeter. Because
    the fill detects which pixels *changed* (not a target colour), it removes
    backgrounds of ANY colour — white, off-white, grey, vivid colours, even
    non-uniform / gradient backdrops — while light/white areas *inside* the
    artwork are preserved (they are not border-connected).

    The result is then despeckled (stray pixels removed), pinhole-filled, and
    colour-bled at the edge so there are no white outlines, grey artefacts, or
    colour fringing — and thin text / hairlines survive intact.
    """
    try:
        rgb = img_rgba.convert('RGB')
        w, h = rgb.size
        bg_color, mad = _border_profile(rgb)

        # Tolerance adapts to how uniform the background is. A noisier border
        # (textured / gradient bg) needs a wider tolerance to fully clear.
        tol = int(min(100, max(24, 32 + mad * 1.6)))
        if mode == 'aggressive':
            tol = min(150, tol + 50)

        work = rgb.copy()
        px = rgb.load()
        sentinel = (0, 254, 1)  # arbitrary; we detect *changed* pixels, not colour

        # Seed densely around the WHOLE perimeter so disconnected or multi-tone
        # background regions are all reached — not just the four corners.
        step = max(1, min(w, h) // 80)
        margin = tol * 2.6  # only seed from border pixels that look background-ish
        corners = {(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)}
        seeds = set(corners)
        for x in range(0, w, step):
            seeds.add((x, 0))
            seeds.add((x, h - 1))
        for y in range(0, h, step):
            seeds.add((0, y))
            seeds.add((w - 1, y))

        for sx, sy in seeds:
            c = px[sx, sy]
            close = (abs(c[0] - bg_color[0]) + abs(c[1] - bg_color[1])
                     + abs(c[2] - bg_color[2])) <= margin
            # Always trust the corners; otherwise only seed background-ish edges
            # so artwork that bleeds to an edge is not eaten by the fill.
            if not (close or (sx, sy) in corners):
                continue
            try:
                ImageDraw.floodfill(work, (sx, sy), sentinel, thresh=tol)
            except Exception:
                pass

        # Background = pixels the flood fill changed.
        diff = ImageChops.difference(rgb, work).convert('L')
        bg_mask = diff.point(lambda p: 255 if p > 0 else 0)  # 255 = background

        if _HAS_NUMPY:
            return _compose_with_numpy(rgb, bg_mask, mode)
        return _compose_with_pil(img_rgba, bg_mask, mode)
    except Exception:
        # Last-resort: at least return an RGBA PNG unchanged.
        return img_rgba


def _compose_with_numpy(rgb, bg_mask, mode):
    rgb_arr = np.asarray(rgb).astype(np.uint8)
    bg = np.asarray(bg_mask) > 127           # True where background
    opaque = ~bg                              # True where artwork

    # Remove stray single-pixel specks / 1px spurs left by the fill. A pixel is
    # only dropped when it has <2 opaque neighbours, so genuine thin lines and
    # text strokes (>=2 connected pixels) are fully preserved.
    opaque = _despeckle(opaque)
    # Re-fill pinholes that are completely enclosed by artwork so solid fills
    # stay solid. Large, intentionally-transparent interior areas are untouched
    # (they have many transparent neighbours), preserving real internal detail.
    opaque = _fill_pinholes(opaque)

    # Defringe: bleed foreground colour outward so any edge pixel carries the
    # artwork's colour instead of leftover background -> no halo / colour fringe
    # / white outline, even after anti-aliasing.
    bled = _bleed_colors(rgb_arr, opaque, iters=4)

    # Alpha from the mask, lightly feathered for smooth (not jagged) edges.
    alpha = np.where(opaque, 255, 0).astype(np.uint8)
    alpha_img = Image.fromarray(alpha, 'L')
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(0.5))

    out = np.dstack([bled, np.asarray(alpha_img)])
    return Image.fromarray(out.astype(np.uint8), 'RGBA')


def _neighbor_count(mask_bool):
    """Count the 8-connected True neighbours of every cell (numpy)."""
    m = mask_bool.astype(np.uint16)
    c = np.zeros(m.shape, dtype=np.uint16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            c += np.roll(np.roll(m, dy, axis=0), dx, axis=1)
    return c


def _despeckle(opaque):
    """Drop isolated opaque specks/spurs; keep anything with >=2 fg neighbours."""
    try:
        nc = _neighbor_count(opaque)
        return opaque & (nc >= 2)
    except Exception:
        return opaque


def _fill_pinholes(opaque):
    """Fill transparent pixels that are almost fully enclosed by artwork."""
    try:
        nc = _neighbor_count(opaque)
        return opaque | ((~opaque) & (nc >= 7))
    except Exception:
        return opaque


def _has_transparency(img_rgba):
    """True when the result has a meaningful amount of transparency."""
    try:
        alpha = img_rgba.getchannel('A')
        if _HAS_NUMPY:
            a = np.asarray(alpha)
            return bool((a < 250).mean() > 0.003)
        lo, _hi = alpha.getextrema()
        return lo < 250
    except Exception:
        return False


def _bleed_colors(rgb_arr, opaque, iters=3):
    """Propagate opaque foreground colours into background pixels (defringe)."""
    rgb = rgb_arr.astype(np.uint8).copy()
    filled = opaque.copy()
    for _ in range(iters):
        for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            nb_filled = np.roll(filled, shift, axis=axis)
            nb_rgb = np.roll(rgb, shift, axis=axis)
            take = (~filled) & nb_filled
            if take.any():
                rgb[take] = nb_rgb[take]
                filled = filled | take
    return rgb


def _compose_with_pil(img_rgba, bg_mask, mode):
    """numpy-free fallback compositor."""
    alpha = ImageOps.invert(bg_mask)  # opaque where not background
    if mode == 'aggressive':
        alpha = alpha.filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.6))
    r, g, b = img_rgba.convert('RGB').split()
    return Image.merge('RGBA', (r, g, b, alpha))


def _defringe(img_rgba):
    """Light edge cleanup applied after AI removal (kill thin halo ring)."""
    try:
        if not _HAS_NUMPY:
            return img_rgba
        arr = np.asarray(img_rgba.convert('RGBA'))
        opaque = arr[..., 3] > 160
        bled = _bleed_colors(arr[..., :3], opaque, iters=2)
        out = np.dstack([bled, arr[..., 3]])
        return Image.fromarray(out.astype(np.uint8), 'RGBA')
    except Exception:
        return img_rgba


# ---------------------------------------------------------------------------
# White-artwork detection
# ---------------------------------------------------------------------------

def _detect_white_artwork(img_rgba):
    """True when the visible artwork is predominantly white/very light."""
    try:
        small = img_rgba.convert('RGBA')
        small.thumbnail((220, 220))
        if _HAS_NUMPY:
            arr = np.asarray(small)
            alpha = arr[..., 3]
            opaque = alpha > 200
            count = int(opaque.sum())
            if count < 40:
                return False
            rgb = arr[..., :3][opaque].astype(np.int16)
            near_white = (rgb.min(axis=1) >= 200)
            frac_white = float(near_white.mean())
            mean_bright = float(rgb.mean())
            return frac_white >= 0.78 and mean_bright >= 205
        # PIL fallback on the small thumbnail
        px = small.load()
        w, h = small.size
        opaque = 0
        white = 0
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a > 200:
                    opaque += 1
                    if min(r, g, b) >= 200:
                        white += 1
        if opaque < 40:
            return False
        return (white / opaque) >= 0.78
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(img_rgba, original_size, changed):
    """Inspect the cutout and report issues so the UI can offer a reprocess."""
    issues = []
    metrics = {}
    try:
        small = img_rgba.convert('RGBA')
        small.thumbnail((256, 256))

        if _HAS_NUMPY:
            arr = np.asarray(small)
            alpha = arr[..., 3]
            total = alpha.size
            opaque_frac = float((alpha > 200).sum()) / total
            transp_frac = float((alpha < 30).sum()) / total
            soft_frac = float(((alpha >= 30) & (alpha <= 200)).sum()) / total
            border = np.concatenate([
                alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]
            ])
            border_opaque_frac = float((border > 200).mean())
            # Corners are almost always background; opacity there is a strong
            # signal that the background was not fully removed.
            ch, cw = alpha.shape
            cs = max(2, min(ch, cw) // 10)
            corner_opaque_frac = float(np.mean([
                (alpha[:cs, :cs] > 200).mean(),
                (alpha[:cs, -cs:] > 200).mean(),
                (alpha[-cs:, :cs] > 200).mean(),
                (alpha[-cs:, -cs:] > 200).mean(),
            ]))
        else:
            px = small.load()
            w, h = small.size
            total = w * h
            opq = tr = soft = 0
            border_opq = border_n = 0
            for y in range(h):
                for x in range(w):
                    a = px[x, y][3]
                    if a > 200:
                        opq += 1
                    elif a < 30:
                        tr += 1
                    else:
                        soft += 1
                    if x in (0, w - 1) or y in (0, h - 1):
                        border_n += 1
                        if a > 200:
                            border_opq += 1
            opaque_frac = opq / total
            transp_frac = tr / total
            soft_frac = soft / total
            border_opaque_frac = (border_opq / border_n) if border_n else 0.0
            corner_opaque_frac = border_opaque_frac

        metrics = {
            'opaque_pct': round(opaque_frac * 100, 1),
            'transparent_pct': round(transp_frac * 100, 1),
            'soft_edge_pct': round(soft_frac * 100, 1),
            'border_opaque_pct': round(border_opaque_frac * 100, 1),
            'corner_opaque_pct': round(corner_opaque_frac * 100, 1),
        }

        if changed and transp_frac < 0.01:
            issues.append('no_background_removed')
        if opaque_frac < 0.015:
            issues.append('artwork_mostly_removed')
        if changed and border_opaque_frac > 0.55:
            issues.append('background_may_remain')
        # Leftover background artefacts: opaque pixels lingering at the frame /
        # corners after a cut that *did* remove something.
        if (changed and 'background_may_remain' not in issues
                and (corner_opaque_frac > 0.18 or border_opaque_frac > 0.28)):
            issues.append('background_artifacts')
        if soft_frac > 0.22:
            issues.append('soft_or_blurry_edges')

        w0, h0 = original_size or (0, 0)
        if w0 and h0 and min(w0, h0) < 300:
            issues.append('low_resolution')
    except Exception:
        pass

    # Only the genuinely broken outcomes flip ok=False (drives the auto prompt).
    blocking = {'no_background_removed', 'artwork_mostly_removed',
                'background_may_remain'}
    ok = not any(i in blocking for i in issues)
    return {'ok': ok, 'issues': issues, 'metrics': metrics}


# Human-readable messages the frontend can show.
ISSUE_MESSAGES = {
    'no_background_removed': "We couldn't detect a background to remove. Try the 'Reprocess (stronger)' option.",
    'artwork_mostly_removed': 'Most of the artwork was removed — the background may be too similar to the design. Try reprocessing.',
    'background_may_remain': 'Some background pixels may remain around the edges. You can reprocess for a stronger cut.',
    'background_artifacts': 'A few background artefacts may remain near the edges or corners. Reprocess for a cleaner cut if needed.',
    'soft_or_blurry_edges': 'Edges look a little soft. A higher-resolution file will give sharper print edges.',
    'low_resolution': 'This image is low resolution and may look blurry when printed. 300 DPI / 1500px+ is recommended.',
}


def issue_messages(validation):
    """Map a validation dict to a list of human-readable strings."""
    return [ISSUE_MESSAGES[i] for i in validation.get('issues', [])
            if i in ISSUE_MESSAGES]
