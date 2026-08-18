"""
image_normalize.py
──────────────────
Normalize a product / mockup image so the shirt always occupies the same
region of the frame, regardless of how the supplier cropped their photo.

Target canvas: 1 000 × 1 250 px  (4 : 5)
Target shirt position (fractions of canvas):
    top    = 0.087   →  108 px from top
    bottom = 0.912   →  1 140 px from top   (height ≈ 82.5 %)
    left   = 0.07    →  70 px from left
    right  = 0.93    →  930 px from right   (width  ≈ 86 %)

This matches what the hand-crafted mockup images already look like, so the
customizer preview will look identical across all product styles.

Usage (standalone):
    python services/image_normalize.py                   # normalize all
    python services/image_normalize.py --dry-run         # preview only
    python services/image_normalize.py --path static/uploads/products

Usage (from code):
    from services.image_normalize import normalize_image, normalize_bytes
"""

from __future__ import annotations

import argparse
import glob
import io
import os
import shutil
import sys

from PIL import Image, ImageOps

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# ── Target canvas ──────────────────────────────────────────────────────────────
CANVAS_W = 1000
CANVAS_H = 1250

# Where the shirt should sit inside the canvas (as fractions)
# Matches the existing hand-crafted BC3001 mockups exactly.
TARGET_TOP    = 0.087
TARGET_BOTTOM = 0.912
TARGET_LEFT   = 0.07
TARGET_RIGHT  = 0.93

# Background fill color (white — same as supplier ghost images)
BG_COLOR = (255, 255, 255)

# Detection thresholds (mirror garment_metrics.py)
_WORK_SIZE      = 320
_COLOR_DISTANCE = 40
_MIN_HEIGHT_FRAC = 0.20
_MIN_WIDTH_FRAC  = 0.10


# ── Silhouette detection ───────────────────────────────────────────────────────

def _backdrop_color(rgb):
    ring = np.concatenate([
        rgb[:2].reshape(-1, 3),
        rgb[-2:].reshape(-1, 3),
        rgb[:, :2].reshape(-1, 3),
        rgb[:, -2:].reshape(-1, 3),
    ])
    return np.median(ring, axis=0).astype(np.int16)


def detect_shirt_box(img: Image.Image):
    """
    Return (top, left, bottom, right) pixel coords of the shirt in *img*,
    or None if detection fails.
    """
    if not _HAS_NUMPY:
        return None

    work = img.copy()
    work.thumbnail((_WORK_SIZE, _WORK_SIZE), Image.BILINEAR)
    w, h = work.size
    if w < 32 or h < 32:
        return None

    mask = None
    if 'A' in work.getbands():
        alpha = np.asarray(work.getchannel('A'))
        if (alpha < 24).mean() > 0.02:
            mask = alpha > 24

    if mask is None:
        rgb = np.asarray(work.convert('RGB')).astype(np.int16)
        bg  = _backdrop_color(rgb)
        dist = (np.abs(rgb[..., 0] - bg[0])
                + np.abs(rgb[..., 1] - bg[1])
                + np.abs(rgb[..., 2] - bg[2]))
        mask = dist > _COLOR_DISTANCE

    min_run = max(2, int(round(w * 0.02)))
    rows = np.where(mask.sum(axis=1) >= min_run)[0]
    min_col_run = max(2, int(round(h * 0.02)))
    cols = np.where(mask.sum(axis=0) >= min_col_run)[0]
    if rows.size == 0 or cols.size == 0:
        return None

    # Scale detection coords back to original image dimensions
    scale_x = img.width  / float(w)
    scale_y = img.height / float(h)

    top    = int(rows[0]    * scale_y)
    bottom = int((rows[-1] + 1) * scale_y)
    left   = int(cols[0]    * scale_x)
    right  = int((cols[-1] + 1) * scale_x)

    height_frac = (bottom - top) / float(img.height)
    width_frac  = (right  - left) / float(img.width)

    if height_frac < _MIN_HEIGHT_FRAC or width_frac < _MIN_WIDTH_FRAC:
        return None

    return (top, left, bottom, right)


# ── Core normalizer ────────────────────────────────────────────────────────────

def normalize_image(img: Image.Image) -> Image.Image:
    """
    Return a new 1000×1250 image with the shirt padded to the target region.
    Falls back gracefully if silhouette detection fails.
    """
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    box = detect_shirt_box(img)

    if box is None:
        # Detection failed — just resize to canvas and center it
        result = Image.new('RGB', (CANVAS_W, CANVAS_H), BG_COLOR)
        thumb = img.convert('RGB').copy()
        thumb.thumbnail((CANVAS_W, CANVAS_H), Image.LANCZOS)
        paste_x = (CANVAS_W - thumb.width)  // 2
        paste_y = (CANVAS_H - thumb.height) // 2
        result.paste(thumb, (paste_x, paste_y))
        return result

    shirt_top, shirt_left, shirt_bottom, shirt_right = box
    shirt_h = shirt_bottom - shirt_top
    shirt_w = shirt_right  - shirt_left

    # How many canvas pixels are allocated for the shirt
    target_h_px = int((TARGET_BOTTOM - TARGET_TOP)  * CANVAS_H)   # ~1005
    target_w_px = int((TARGET_RIGHT  - TARGET_LEFT) * CANVAS_W)   # ~860

    # Scale so the shirt fits within both target dims (letterbox)
    scale = min(target_w_px / shirt_w, target_h_px / shirt_h)

    new_w = int(img.width  * scale)
    new_h = int(img.height * scale)
    scaled = img.convert('RGB').resize((new_w, new_h), Image.LANCZOS)

    # After scaling, where does the shirt land?
    scaled_shirt_top  = int(shirt_top  * scale)
    scaled_shirt_left = int(shirt_left * scale)

    # Where we want the shirt top-left to end up on the canvas
    canvas_shirt_top  = int(TARGET_TOP  * CANVAS_H)
    canvas_shirt_left = int(TARGET_LEFT * CANVAS_W)

    # Offset of the full scaled image on the canvas
    offset_y = canvas_shirt_top  - scaled_shirt_top
    offset_x = canvas_shirt_left - scaled_shirt_left

    result = Image.new('RGB', (CANVAS_W, CANVAS_H), BG_COLOR)
    result.paste(scaled, (offset_x, offset_y))
    return result


def normalize_bytes(data: bytes, fmt: str = 'JPEG') -> bytes:
    """Normalize image from raw bytes, return normalized bytes."""
    img = Image.open(io.BytesIO(data))
    img.load()
    normalized = normalize_image(img)
    buf = io.BytesIO()
    normalized.save(buf, format=fmt, quality=92, optimize=True)
    return buf.getvalue()


# ── Batch file processor ───────────────────────────────────────────────────────

def _should_process(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in ('.jpg', '.jpeg', '.png', '.webp')


def process_file(path: str, dry_run: bool = False, backup: bool = True) -> str:
    """
    Normalize a single image file in place.
    Returns 'normalized', 'skipped', or 'failed'.
    """
    try:
        img = Image.open(path)
        img.load()
    except Exception as e:
        return f'failed (open: {e})'

    # Already normalized canvas size — check if shirt is already in the right spot
    if img.width == CANVAS_W and img.height == CANVAS_H:
        box = detect_shirt_box(img)
        if box is not None:
            t, l, b, r = box
            top_frac    = t / float(CANVAS_H)
            bottom_frac = b / float(CANVAS_H)
            if (abs(top_frac - TARGET_TOP) < 0.04
                    and abs(bottom_frac - TARGET_BOTTOM) < 0.04):
                return 'already normalized'

    if dry_run:
        box = detect_shirt_box(img)
        if box:
            t, l, b, r = box
            return (f'would normalize  shirt={t/img.height:.3f}-{b/img.height:.3f}'
                    f'  size={img.width}x{img.height}')
        return f'would normalize (no detection)  size={img.width}x{img.height}'

    try:
        normalized = normalize_image(img)
    except Exception as e:
        return f'failed (normalize: {e})'

    if backup:
        bak = path + '.bak'
        if not os.path.exists(bak):
            shutil.copy2(path, bak)

    ext = os.path.splitext(path)[1].lower()
    fmt = 'PNG' if ext == '.png' else 'JPEG'
    try:
        normalized.save(path, format=fmt, quality=92, optimize=True)
    except Exception as e:
        return f'failed (save: {e})'

    return 'normalized'


def run_batch(roots: list[str], dry_run: bool = False, backup: bool = True):
    patterns = [
        '**/*.jpg', '**/*.jpeg', '**/*.png', '**/*.webp',
    ]
    files = []
    for root in roots:
        if os.path.isfile(root):
            files.append(root)
        else:
            for pat in patterns:
                files.extend(glob.glob(os.path.join(root, pat), recursive=True))
    files = sorted(set(files))

    if not files:
        print('No image files found.')
        return

    counts = {'normalized': 0, 'already normalized': 0, 'failed': 0, 'skipped': 0}
    for path in files:
        status = process_file(path, dry_run=dry_run, backup=backup)
        label = status.split()[0]  # first word
        counts[label] = counts.get(label, 0) + 1
        short = path.replace('\\', '/').split('static/')[-1]
        print(f'  {status:<50}  {short}')

    print()
    print(f"Done.  normalized={counts.get('normalized',0)}  "
          f"already_ok={counts.get('already',0)}  "
          f"failed={counts.get('failed',0)}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Normalize product images to standard canvas.')
    parser.add_argument('--path', nargs='*',
                        default=[
                            'static/uploads/mockups',
                            'static/uploads/products',
                        ],
                        help='Directories or files to process')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would happen without writing files')
    parser.add_argument('--no-backup', action='store_true',
                        help='Skip creating .bak backup files')
    args = parser.parse_args()

    if not _HAS_NUMPY:
        print('ERROR: numpy is required.  pip install numpy', file=sys.stderr)
        sys.exit(1)

    mode = 'DRY RUN' if args.dry_run else 'NORMALIZING'
    print(f'=== Image Normalizer — {mode} ===')
    print(f'Canvas: {CANVAS_W}x{CANVAS_H}   '
          f'Target shirt: top={TARGET_TOP} bottom={TARGET_BOTTOM}')
    print()
    run_batch(args.path, dry_run=args.dry_run, backup=not args.no_backup)
