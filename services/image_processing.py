"""
Background removal pipeline — rewritten from scratch.

Strategy:
  1. PRIMARY: rembg AI (u2net model) — works on ANY background color, any logo.
     Neural network understands foreground vs background by structure, not color.
  2. FALLBACK: Enhanced algorithmic edge-fill — used only when rembg is
     completely unavailable (missing package, no network for model download).

Post-processing (always applied after removal):
  - Edge sharpening / alpha hardening  → crisp, print-ready borders
  - Defringe                           → kills color halos at edges
  - Enclosed-region removal            → clears background inside A B D O P Q etc.
  - Autocrop                           → trims transparent padding

Every public function is crash-safe: returns the original image on any error
so uploads never break.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageOps

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


# ---------------------------------------------------------------------------
# rembg session — lazily initialized, cached for the process lifetime
# ---------------------------------------------------------------------------

_SESSION_CACHE: dict = {}
_REMBG_FAILED = False

# Try small/fast models first so Railway's first-upload latency is low.
# u2netp is only 4 MB — downloads in seconds, works great for logos/graphics.
# u2net (180 MB) is the quality fallback when u2netp isn't available.
_MODEL_PRIORITY = [
    'isnet-general-use', # 170 MB — best for crevices/fine details
    'u2net',             # 180 MB — high quality fallback
    'u2netp',            # 4 MB   — fast download, good for simple logos
]


def _get_session(model: str = 'u2net'):
    """Return a cached rembg session for *model*, or None on failure."""
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
    """Try models in priority order; return first that loads."""
    global _REMBG_FAILED
    if _REMBG_FAILED:
        return None, None
    # Check env override first
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
    """Process raw image bytes → transparent PNG.

    Args:
        data:   raw image bytes (any format PIL can open)
        mode:   'auto' | 'aggressive' | 'none'
        engine: None (auto) | 'ai' | 'algorithmic'

    Returns dict:
        data          – processed PNG bytes
        engine        – engine used
        white_artwork – bool
        validation    – {ok, issues, metrics}
        has_transparency – bool
        width, height – int
        changed       – bool
    """
    # ── Decode ────────────────────────────────────────────────────────────────
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

    # ── Already transparent? ──────────────────────────────────────────────────
    if _already_transparent(img) and mode != 'aggressive':
        out = _cleanup_alpha(img)
        out = _enclosed_bg_removal(out)
        out = _autocrop(out)
        return _encode(out, 'preserved', original_size, changed=True)

    # ── Engine selection ──────────────────────────────────────────────────────
    want = engine if engine else 'ai'   # always prefer AI

    out = None
    used_engine = 'none'

    # ── AI removal (rembg) ────────────────────────────────────────────────────
    # We track the source used for AI so _post_process can detect the correct
    # background color.  After preswap, the "background" is gray (not the
    # original black), so harden_alpha must match gray halos, not black ones.
    src_for_post = src.convert('RGB')   # default: use original for bg detection

    if want in ('ai', None):
        # Pre-swap: replace the uniform background with a neutral gray BEFORE
        # sending to rembg. This solves "black outline on black background" where
        # the design's dark border is indistinguishable from the background.
        #
        # Strategy:
        #   1. Flood-fill from image borders to find all background pixels.
        #   2. Replace with 180,180,180 (light gray) if bg is dark, 80,80,80 if light.
        #   3. rembg now sees pink text with black outline on GRAY — the black
        #      outline is visually surrounded by pink, not by gray, so rembg
        #      keeps it as foreground.
        #   4. Pass the preswapped RGB to _post_process so harden_alpha knows the
        #      bg is now GRAY, not black, and kills gray halos correctly.
        img_for_ai = _preswap_background(src.convert('RGB'))
        out = _remove_ai(img_for_ai.convert('RGBA'))
        if out is not None:
            used_engine = 'ai'
            src_for_post = img_for_ai   # harden_alpha targets gray, not original black

    # ── Algorithmic fallback ──────────────────────────────────────────────────
    if out is None:
        out = _remove_algorithmic(img, mode=mode)
        used_engine = 'algorithmic'

    if out is None:
        out = img  # absolute last resort

    # ── Post-processing ───────────────────────────────────────────────────────
    out = _post_process(out, src_for_post, used_engine, mode)

    return _encode(out, used_engine, original_size, changed=True)


def process_artwork_file(path, mode: str = 'auto', engine=None) -> dict:
    """Process an image file in place, writing a transparent PNG.

    Returns the same dict as process_artwork_bytes plus:
        path     – pathlib.Path of the written PNG
        filename – its filename
    """
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
    """Human-readable messages from a validation dict."""
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
# AI engine
# ---------------------------------------------------------------------------

def _preswap_background(img_rgb: Image.Image) -> Image.Image:
    """Replace the flood-filled background with a neutral gray before rembg.

    Solves the "black outline on black background" problem: the design's dark
    border and the background share the same color, so rembg can't distinguish
    them by hue alone.  By swapping the background to a contrasting gray we
    give rembg a clear signal:
      - background = gray
      - foreground = pink text + black outline (the outline is enclosed WITHIN
        the design structure so flood-fill from the border won't reach it)

    Only activates when the background is reasonably uniform (MAD < 25) and
    not already a mid-gray (which needs no swapping).
    """
    try:
        bg_color, mad = _border_profile(img_rgb)
        if mad > 25:          # Complex/gradient background — let rembg handle it
            return img_rgb
        br, bg, bb = int(bg_color[0]), int(bg_color[1]), int(bg_color[2])
        bg_mean = (br + bg + bb) / 3
        # Skip if bg is already a neutral mid-gray (80–180) — no ambiguity
        if 80 <= bg_mean <= 180 and max(abs(br-bg), abs(bg-bb), abs(br-bb)) < 20:
            return img_rgb

        # Flood-fill background from the image border using a loose tolerance
        w, h = img_rgb.size
        work = img_rgb.copy()
        tol = int(min(55, max(22, 28 + mad * 1.2)))
        SENTINEL = (0, 254, 1)        # Distinctive color that won't appear in logos
        step = max(1, min(w, h) // 60)
        for x in range(0, w, step):
            for y in [0, h - 1]:
                try:
                    ImageDraw.floodfill(work, (x, y), SENTINEL, thresh=tol)
                except Exception:
                    pass
        for y in range(0, h, step):
            for x in [0, w - 1]:
                try:
                    ImageDraw.floodfill(work, (x, y), SENTINEL, thresh=tol)
                except Exception:
                    pass
        for corner in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]:
            try:
                ImageDraw.floodfill(work, corner, SENTINEL, thresh=tol)
            except Exception:
                pass

        if not _HAS_NUMPY:
            # PIL-only path: scan and replace sentinel pixels
            px = work.load()
            neutral = (180, 180, 180) if bg_mean < 128 else (80, 80, 80)
            for yy in range(h):
                for xx in range(w):
                    if px[xx, yy] == SENTINEL:
                        px[xx, yy] = neutral
            return work

        work_arr = np.asarray(work).astype(np.uint8).copy()
        mask = ((work_arr[..., 0] == 0) &
                (work_arr[..., 1] == 254) &
                (work_arr[..., 2] == 1))
        if mask.sum() < 100:     # Flood fill barely touched anything — skip
            return img_rgb
        # Choose replacement: light gray for dark backgrounds, dark gray for light
        neutral = (180, 180, 180) if bg_mean < 128 else (80, 80, 80)
        work_arr[mask] = neutral
        return Image.fromarray(work_arr, 'RGB')
    except Exception:
        return img_rgb


def _remove_ai(img_rgba: Image.Image):
    """Run rembg on the image. Returns RGBA Image or None.

    alpha_matting is intentionally disabled. It is designed for hair and fur
    and introduces a multi-pixel erosion that eats logo outlines. For clean
    graphic logos (the main use-case here), the raw u2netp mask with
    post_process_mask=True produces sharper, more accurate edges.
    """
    sess, model = _best_session()
    if sess is None:
        return None
    try:
        from rembg import remove
        out = remove(
            img_rgba,
            session=sess,
            alpha_matting=False,
            post_process_mask=True,
        )
        if out is None:
            return None
        return out.convert('RGBA')
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Algorithmic fallback (used only when rembg is unavailable)
# ---------------------------------------------------------------------------

def _remove_algorithmic(img_rgba: Image.Image, mode: str = 'auto'):
    """Edge-seeded flood-fill removal. Works on any uniform background."""
    try:
        if not _HAS_NUMPY:
            return _remove_algorithmic_pil(img_rgba, mode)

        rgb = img_rgba.convert('RGB')
        w, h = rgb.size
        bg_color, mad = _border_profile(rgb)

        # Tolerance: adapts to background uniformity
        tol = int(min(120, max(28, 30 + mad * 2.0)))
        if mode == 'aggressive':
            tol = min(200, tol + 80)

        # Flood fill from perimeter seeds
        work = rgb.copy()
        px_orig = rgb.load()
        sentinel = (0, 254, 1)

        step = max(1, min(w, h) // 80)
        seeds = set()
        for x in range(0, w, step):
            seeds.add((x, 0)); seeds.add((x, h - 1))
        for y in range(0, h, step):
            seeds.add((0, y)); seeds.add((w - 1, y))
        # Always include corners
        for corner in [(0,0),(w-1,0),(0,h-1),(w-1,h-1)]:
            seeds.add(corner)

        margin = tol * 3
        for sx, sy in seeds:
            c = px_orig[sx, sy]
            dist = abs(c[0]-bg_color[0]) + abs(c[1]-bg_color[1]) + abs(c[2]-bg_color[2])
            if dist <= margin or (sx,sy) in {(0,0),(w-1,0),(0,h-1),(w-1,h-1)}:
                try:
                    ImageDraw.floodfill(work, (sx, sy), sentinel, thresh=tol)
                except Exception:
                    pass

        diff = ImageChops.difference(rgb, work).convert('L')
        flood_mask = np.asarray(diff) > 0

        # Grow flood mask into color-similar pixels (catches enclosed bg)
        rgb_arr = np.asarray(rgb).astype(np.int16)
        dist_bg = (np.abs(rgb_arr[...,0] - bg_color[0])
                 + np.abs(rgb_arr[...,1] - bg_color[1])
                 + np.abs(rgb_arr[...,2] - bg_color[2]))
        ck_tol = int(min(110, max(30, 28 + mad * 1.8)))
        if mode == 'aggressive':
            ck_tol = min(180, ck_tol + 70)
        color_bg = dist_bg <= ck_tol
        bg = flood_mask.copy()
        for _ in range(12):
            expanded = bg.copy()
            for dy, dx in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
                nb = np.roll(np.roll(bg, dy, axis=0), dx, axis=1)
                if dy == 1: nb[0,:] = False
                elif dy == -1: nb[-1,:] = False
                if dx == 1: nb[:,0] = False
                elif dx == -1: nb[:,-1] = False
                expanded |= nb & color_bg
            if expanded.sum() == bg.sum():
                break
            bg = expanded

        fg = ~bg
        fg = _despeckle(fg)
        fg = _fill_pinholes(fg)
        bled = _bleed_colors(np.asarray(rgb).astype(np.uint8), fg, iters=6)
        alpha = np.where(fg, 255, 0).astype(np.uint8)
        alpha_img = Image.fromarray(alpha, 'L').filter(ImageFilter.GaussianBlur(0.5))
        arr = np.dstack([bled, np.asarray(alpha_img)])
        return Image.fromarray(arr.astype(np.uint8), 'RGBA')
    except Exception:
        return img_rgba


def _remove_algorithmic_pil(img_rgba: Image.Image, mode: str = 'auto'):
    """PIL-only fallback (no numpy)."""
    try:
        rgb = img_rgba.convert('RGB')
        w, h = rgb.size
        bg_color, mad = _border_profile(rgb)
        tol = int(min(100, max(24, 30 + mad * 1.6)))
        if mode == 'aggressive':
            tol = min(180, tol + 80)
        work = rgb.copy()
        sentinel = (0, 254, 1)
        for corner in [(0,0),(w-1,0),(0,h-1),(w-1,h-1)]:
            try:
                ImageDraw.floodfill(work, corner, sentinel, thresh=tol)
            except Exception:
                pass
        diff = ImageChops.difference(rgb, work).convert('L')
        bg_mask = diff.point(lambda p: 255 if p > 0 else 0)
        alpha = ImageOps.invert(bg_mask).filter(ImageFilter.GaussianBlur(0.6))
        r, g, b = img_rgba.convert('RGB').split()
        return Image.merge('RGBA', (r, g, b, alpha))
    except Exception:
        return img_rgba


# ---------------------------------------------------------------------------
# Post-processing pipeline
# ---------------------------------------------------------------------------

def _post_process(out: Image.Image, src_rgb: Image.Image,
                  engine: str, mode: str) -> Image.Image:
    """Minimal, logo-safe post-processing pipeline.

    Removed _defringe and _edge_contract — those functions use the detected
    background color to kill edge pixels, but when the design shares the same
    color as the background (e.g. black outline on a black background) they
    destroy real logo pixels. rembg's AI output is trusted as-is; we only
    apply:
      1. Color-aware alpha hardening — kills semi-transparent background halos
      2. Enclosed-region removal    — clears background inside letter holes
      3. Autocrop
    """
    if not _HAS_NUMPY:
        return _autocrop(out)

    try:
        bg_color, _ = _border_profile(src_rgb)
    except Exception:
        bg_color = (255, 255, 255)

    try:
        out = _harden_alpha(out, engine, bg_color)
        out = _enclosed_bg_removal(out)
        out = _autocrop(out)
    except Exception:
        pass

    return out


def _harden_alpha(img: Image.Image, engine: str,
                  bg_color=(255, 255, 255)) -> Image.Image:
    """Color-aware alpha hardening — removes background halos without hurting logos.

    rembg outputs a smooth alpha mask: background edges are semi-transparent
    (alpha 5-150) while the logo interior is near-opaque (alpha 200-255).

    We exploit two facts:
      1. Semi-transparent pixels that share the BACKGROUND COLOR are halo
         remnants → set alpha to 0.
      2. Semi-transparent pixels with a DIFFERENT color from the background are
         anti-aliased logo edges → leave them alone so the cutout looks clean.
      3. Snap extremes: alpha < 10 → 0, alpha > 230 → 255.

    This correctly handles the hard case of a black-outlined logo on a black
    background: the black outline has alpha ≈ 255 from rembg (solid foreground),
    while the halo around it has alpha 20-100 AND color ≈ black → zeroed out.
    """
    if not _HAS_NUMPY:
        return img
    try:
        arr = np.asarray(img).astype(np.uint8).copy()
        if arr.shape[2] < 4:
            return img
        a = arr[..., 3].astype(np.float32)
        rgb = arr[..., :3].astype(np.int16)

        bg_r = int(bg_color[0])
        bg_g = int(bg_color[1])
        bg_b = int(bg_color[2])

        # Manhattan distance from each pixel to the background color
        dist_from_bg = (np.abs(rgb[..., 0] - bg_r)
                       + np.abs(rgb[..., 1] - bg_g)
                       + np.abs(rgb[..., 2] - bg_b))

        # Step 1: absolute snaps at the extremes
        a = np.where(a < 10, 0.0, a)
        a = np.where(a > 230, 255.0, a)

        # Step 2: mid-range pixels (10 ≤ alpha ≤ 230)
        #   → if color is close to background AND alpha is not fully opaque → halo
        is_mid = (a >= 10) & (a <= 230)
        # "Close to background" threshold: 80 on a 0-765 Manhattan distance scale.
        # Wide enough to catch dark-gray halos (not just pure black), narrow enough
        # to preserve logo colors that only partially resemble the background.
        is_bg_colored = dist_from_bg < 80
        # Kill background-colored pixels that are less than 200/255 (≈78%) opaque.
        # rembg gives the design's actual black outline pixels alpha ≥ 200 because
        # they are structurally part of the foreground. Halo/fringe pixels at the
        # background edge only reach alpha 20-180, so raising the cutoff to 200
        # eliminates virtually all halo while keeping real logo outlines intact.
        a = np.where(is_mid & is_bg_colored & (a < 200), 0.0, a)

        arr[..., 3] = a.astype(np.uint8)
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return img


def _defringe(img: Image.Image, bg_color=(255,255,255)) -> Image.Image:
    """Bleed opaque foreground colors into transparent edge pixels.

    Eliminates white/bg-colored halos so the logo looks clean on any shirt
    color — not just white.
    """
    if not _HAS_NUMPY:
        return img
    try:
        arr = np.asarray(img).astype(np.uint8).copy()
        alpha = arr[..., 3]
        rgb = arr[..., :3].copy()

        opaque = alpha > 128
        filled = opaque.copy()
        for _ in range(6):          # 6 px outward bleed
            for shift, axis in [(1,0),(-1,0),(1,1),(-1,1)]:
                nb_filled = np.roll(filled, shift, axis=axis)
                nb_rgb = np.roll(rgb, shift, axis=axis)
                take = (~filled) & nb_filled
                if take.any():
                    rgb[take] = nb_rgb[take]
                    filled |= take

        arr[..., :3] = rgb
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return img


def _enclosed_bg_removal(img: Image.Image) -> Image.Image:
    """BFS from the transparent border into enclosed background regions.

    Removes background pixels trapped inside letter holes (A B D O P Q 8 …)
    and circular logo elements. Uses connectivity so it NEVER touches logo
    elements that happen to match the background color.
    """
    if not _HAS_NUMPY:
        return img
    try:
        arr = np.asarray(img).astype(np.uint8).copy()
        alpha = arr[..., 3]
        h, w = alpha.shape

        transparent = alpha < 40    # current transparent pixels (raised for better crevice removal)
        opaque = alpha >= 128       # definite foreground

        # BFS: find all transparent pixels reachable from the image border
        # (these are legitimate "outside" transparent areas).
        # Enclosed bg pixels are transparent but NOT reachable from the border.
        from collections import deque
        visited = np.zeros((h, w), dtype=bool)

        q = deque()
        for x in range(w):
            for y in [0, h-1]:
                if transparent[y, x] and not visited[y, x]:
                    visited[y, x] = True
                    q.append((y, x))
        for y in range(h):
            for x in [0, w-1]:
                if transparent[y, x] and not visited[y, x]:
                    visited[y, x] = True
                    q.append((y, x))

        while q:
            y, x = q.popleft()
            for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                ny, nx = y+dy, x+dx
                if 0 <= ny < h and 0 <= nx < w and not visited[ny,nx]:
                    if transparent[ny, nx]:
                        visited[ny, nx] = True
                        q.append((ny, nx))

        # Transparent pixels not reachable from border = enclosed bg → remove
        enclosed = transparent & ~visited

        # Expand enclosed region slightly to catch semi-transparent fringe
        for _ in range(5):
            dilated = np.zeros_like(enclosed)
            for dy, dx in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                dilated |= np.roll(np.roll(enclosed, dy, axis=0), dx, axis=1)
            # Only expand into semi-transparent (not into opaque foreground)
            enclosed = dilated & ~opaque

        alpha_copy = alpha.copy().astype(np.int32)
        alpha_copy[enclosed] = 0
        arr[..., 3] = alpha_copy.clip(0, 255).astype(np.uint8)
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return img


def _edge_contract(img: Image.Image, bg_color=(255,255,255)) -> Image.Image:
    """Kill any remaining background-colored fringe pixels at opaque edges."""
    if not _HAS_NUMPY:
        return img
    try:
        arr = np.asarray(img).astype(np.uint8).copy()
        alpha = arr[..., 3].astype(np.int32)
        rgb = arr[..., :3].astype(np.int16)

        bg_r, bg_g, bg_b = int(bg_color[0]), int(bg_color[1]), int(bg_color[2])
        dist = (np.abs(rgb[..., 0] - bg_r)
              + np.abs(rgb[..., 1] - bg_g)
              + np.abs(rgb[..., 2] - bg_b))

        # Very tight threshold: only kill pixels very close to detected bg color.
        # A loose threshold eats logo pixels that share a hue with the background.
        is_near_bg = dist < 30

        transparent = alpha < 20
        has_transp_nb = np.zeros(transparent.shape, bool)
        for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:   # 4-connected only, not diagonal
            has_transp_nb |= np.roll(np.roll(transparent, dy, axis=0), dx, axis=1)

        # Kill opaque bg-colored pixels that sit right next to transparency
        kill = (alpha >= 200) & is_near_bg & has_transp_nb
        alpha[kill] = 0

        arr[..., 3] = alpha.clip(0, 255).astype(np.uint8)
        return Image.fromarray(arr, 'RGBA')
    except Exception:
        return img


def _autocrop(img: Image.Image, padding: int = 6) -> Image.Image:
    """Crop to the bounding box of non-transparent pixels."""
    try:
        if img.mode != 'RGBA':
            return img
        alpha = img.getchannel('A')
        bbox = alpha.getbbox()
        if bbox is None:
            return img
        l, t, r, b = bbox
        w, h = img.size
        l = max(0, l - padding)
        t = max(0, t - padding)
        r = min(w, r + padding)
        b = min(h, b + padding)
        return img.crop((l, t, r, b))
    except Exception:
        return img


def _cleanup_alpha(img: Image.Image) -> Image.Image:
    """Light cleanup for images that are already transparent."""
    try:
        r, g, b, a = img.split()
        a = a.filter(ImageFilter.GaussianBlur(0.4))
        return Image.merge('RGBA', (r, g, b, a))
    except Exception:
        return img


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _border_profile(rgb: Image.Image):
    """Estimate background color from the image border ring."""
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
    mad = sum(abs(s[0]-med[0]) + abs(s[1]-med[1]) + abs(s[2]-med[2])
              for s in samples) / (n * 3.0)
    return med, mad


def _already_transparent(img: Image.Image) -> bool:
    """True if the image already has a meaningful transparent background."""
    try:
        alpha = img.getchannel('A')
        lo, hi = alpha.getextrema()
        if lo >= 250:
            return False
        small = alpha.resize((64, 64))
        px = small.load()
        border = []
        for x in range(64):
            border.append(px[x, 0]); border.append(px[x, 63])
        for y in range(64):
            border.append(px[0, y]); border.append(px[63, y])
        return sum(1 for v in border if v < 40) / len(border) > 0.6
    except Exception:
        return False


def _despeckle(mask: 'np.ndarray') -> 'np.ndarray':
    """Remove isolated single-pixel foreground specks."""
    try:
        m = mask.astype(np.uint16)
        c = np.zeros(m.shape, dtype=np.uint16)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                c += np.roll(np.roll(m, dy, axis=0), dx, axis=1)
        return mask & (c >= 2)
    except Exception:
        return mask


def _fill_pinholes(mask: 'np.ndarray') -> 'np.ndarray':
    """Fill single-pixel transparent holes inside foreground."""
    try:
        m = mask.astype(np.uint16)
        c = np.zeros(m.shape, dtype=np.uint16)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                c += np.roll(np.roll(m, dy, axis=0), dx, axis=1)
        return mask | ((~mask) & (c >= 7))
    except Exception:
        return mask


def _bleed_colors(rgb: 'np.ndarray', opaque: 'np.ndarray', iters: int = 6) -> 'np.ndarray':
    """Propagate opaque foreground colors into transparent edge pixels (defringe)."""
    rgb = rgb.astype(np.uint8).copy()
    filled = opaque.copy()
    for _ in range(iters):
        for shift, axis in [(1,0),(-1,0),(1,1),(-1,1)]:
            nb_filled = np.roll(filled, shift, axis=axis)
            nb_rgb = np.roll(rgb, shift, axis=axis)
            take = (~filled) & nb_filled
            if take.any():
                rgb[take] = nb_rgb[take]
                filled |= take
    return rgb


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
    """True when the visible artwork is predominantly white/very light."""
    try:
        if not _HAS_NUMPY:
            return False
        arr = np.asarray(img)
        alpha = arr[..., 3]
        rgb = arr[..., :3]
        opaque = alpha > 128
        if opaque.sum() == 0:
            return False
        brightness = rgb[opaque].mean(axis=0).mean()
        return float(brightness) > 230
    except Exception:
        return False


def _validate(img: Image.Image, original_size, changed: bool) -> dict:
    """Basic sanity checks on the cutout."""
    issues = []
    metrics = {}
    try:
        if not _HAS_NUMPY:
            return {'ok': True, 'issues': [], 'metrics': {}}

        arr = np.asarray(img)
        alpha = arr[..., 3]
        total = alpha.size
        transparent_frac = (alpha < 30).sum() / total
        opaque_frac = (alpha > 200).sum() / total

        metrics['transparent_pct'] = round(float(transparent_frac) * 100, 1)
        metrics['opaque_pct'] = round(float(opaque_frac) * 100, 1)

        if changed and transparent_frac < 0.03:
            issues.append('no_background_removed')
        if opaque_frac < 0.02:
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
    white_artwork = _detect_white_artwork(img)
    validation = _validate(img, original_size, changed)
    has_transparency = _has_transparency(img)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return {
        'data': buf.getvalue(),
        'engine': engine,
        'white_artwork': white_artwork,
        'validation': validation,
        'has_transparency': has_transparency,
        'width': img.size[0],
        'height': img.size[1],
        'changed': changed,
    }
