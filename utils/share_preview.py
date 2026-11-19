"""The picture a shared-design link shows on Facebook and in texts: the shirt photo with the design drawn on it.

The page itself draws the logo on the shirt in the browser, which a link preview cannot do, so this makes the same
picture on the server. Sized 1200 x 630, the shape Facebook shows without cropping.
"""
from __future__ import annotations

import io
import re

CANVAS = (1200, 630)
BACKDROP = (250, 247, 242)


# Where the cart draws the logo on the shirt photo (the .pm-proof-overlay rules in main.css). The shared
# page and its link preview use the same numbers, so a shared design looks like the one that was made.
_CART_LOOK = {
    'center_chest': 'width:38%;max-width:44%;max-height:46%;top:38%;left:50%;transform:translate(-50%,-50%);',
    'left_chest': 'width:14%;max-width:16%;max-height:20%;top:32%;left:62%;transform:translate(-50%,-50%);',
    'right_chest': 'width:14%;max-width:16%;max-height:20%;top:32%;left:38%;transform:translate(-50%,-50%);',
}


def cart_style(placement):
    """The logo's size and place on the front, exactly as the cart shows it."""
    return _CART_LOOK.get((placement or 'center_chest').strip().lower().replace(' ', '_'), _CART_LOOK['center_chest'])


def _percent(style, name):
    m = re.search(rf'(?:^|;){name}:\s*([0-9.]+)%', style or '')
    return float(m.group(1)) if m else None


def _trim_margins(img, backdrop, pad=0.05):
    """Crop the empty background around the shirt (plus a little breathing room) so the shirt fills the picture."""
    from PIL import Image, ImageChops
    try:
        flat = img.convert('RGB')
        diff = ImageChops.difference(flat, Image.new('RGB', flat.size, backdrop)).convert('L').point(lambda p: 255 if p > 14 else 0)
        box = diff.getbbox()
        if not box:
            return img
        w, h = img.size
        px, py = int((box[2] - box[0]) * pad), int((box[3] - box[1]) * pad)
        box = (max(0, box[0] - px), max(0, box[1] - py), min(w, box[2] + px), min(h, box[3] + py))
        return img.crop(box) if (box[2] - box[0]) > 50 and (box[3] - box[1]) > 50 else img
    except Exception:
        return img


def compose(mockup_url, design_url, style):
    """JPEG bytes of the design on the shirt photo, or None when either picture cannot be loaded."""
    from PIL import Image

    from utils.flyer import _read
    try:
        shirt_raw, art_raw = _read(mockup_url), _read(design_url)
        if not shirt_raw or not art_raw:
            return None
        shirt = Image.open(io.BytesIO(shirt_raw))
        shirt.load()
        shirt = shirt.convert('RGBA')
        art = Image.open(io.BytesIO(art_raw))
        art.load()
        art = art.convert('RGBA')
    except Exception:
        return None

    sw, sh = shirt.size
    width_pct = _percent(style, 'width') or 38.0
    max_h_pct = _percent(style, 'max-height') or 50.0
    top_pct = _percent(style, 'top') or 38.0
    left_pct = _percent(style, 'left') or 50.0
    aw = sw * width_pct / 100.0
    ah = aw * art.height / max(art.width, 1)
    if ah > sh * max_h_pct / 100.0:                       # same rule as the page: never taller than max-height
        ah = sh * max_h_pct / 100.0
        aw = ah * art.width / max(art.height, 1)
    art = art.resize((max(1, int(aw)), max(1, int(ah))), Image.LANCZOS)
    backdrop = tuple(shirt.convert('RGB').getpixel((2, 2)))        # the photo's own background, so the side margins blend in
    base = Image.new('RGBA', shirt.size, backdrop + (255,))
    base.alpha_composite(shirt)
    base.alpha_composite(art, (int(sw * left_pct / 100.0 - art.width / 2), int(sh * top_pct / 100.0 - art.height / 2)))

    base = _trim_margins(base, backdrop)                  # the shirt, not the empty photo around it
    sw, sh = base.size
    scale = min(CANVAS[0] / sw, CANVAS[1] / sh)           # the whole shirt fits inside the 1200 x 630 frame
    fitted = base.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
    canvas = Image.new('RGB', CANVAS, backdrop)
    canvas.paste(fitted.convert('RGB'), ((CANVAS[0] - fitted.width) // 2, (CANVAS[1] - fitted.height) // 2))
    out = io.BytesIO()
    canvas.save(out, 'JPEG', quality=88, optimize=True)
    return out.getvalue()
