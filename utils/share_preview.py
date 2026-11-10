"""The picture a shared-design link shows on Facebook and in texts: the shirt photo with the design drawn on it.

The page itself draws the logo on the shirt in the browser, which a link preview cannot do, so this makes the same
picture on the server. Sized 1200 x 630, the shape Facebook shows without cropping.
"""
from __future__ import annotations

import io
import re

CANVAS = (1200, 630)
BACKDROP = (250, 247, 242)


def _percent(style, name):
    m = re.search(rf'(?:^|;){name}:\s*([0-9.]+)%', style or '')
    return float(m.group(1)) if m else None


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

    scale = min(CANVAS[0] / sw, CANVAS[1] / sh)           # the whole shirt fits inside the 1200 x 630 frame
    fitted = base.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
    canvas = Image.new('RGB', CANVAS, backdrop)
    canvas.paste(fitted.convert('RGB'), ((CANVAS[0] - fitted.width) // 2, (CANVAS[1] - fitted.height) // 2))
    out = io.BytesIO()
    canvas.save(out, 'JPEG', quality=88, optimize=True)
    return out.getvalue()
