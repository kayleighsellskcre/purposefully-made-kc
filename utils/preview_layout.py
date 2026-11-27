"""Where the customer placed their art on the shirt, measured in the customizer.

Each side is stored as fractions of the shirt photo: x and y (top-left corner), w and h (size), and ar (the photo's
height / width). The cart, checkout and admin redraw the shirt from these numbers, so every page shows the shirt
exactly as the customer saw it while designing, even when the snapshot picture could not be saved.
"""
from __future__ import annotations

import json

SIDES = ('front', 'back')


def _num(value, low, high):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n < low or n > high:          # NaN or out of range
        return None
    return round(n, 4)


def clean(raw):
    """A stored layout from the customizer's JSON, keeping only sane numbers. None when nothing usable was sent."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    out = {}
    for side in SIDES:
        part = raw.get(side)
        if not isinstance(part, dict):
            continue
        x, y = _num(part.get('x'), -0.5, 1.0), _num(part.get('y'), -0.5, 1.0)
        w, h = _num(part.get('w'), 0.005, 1.5), _num(part.get('h'), 0.005, 1.5)
        ar = _num(part.get('ar'), 0.3, 3.0)
        if None in (x, y, w, h, ar):
            continue
        out[side] = {'x': x, 'y': y, 'w': w, 'h': h, 'ar': ar}
    return out or None


def load(value):
    """The layout kept on a cart line (a dict) or an order line (JSON text)."""
    return clean(value)


def side(layout, which):
    """One side's numbers, or None."""
    layout = load(layout) if not isinstance(layout, dict) else layout
    return (layout or {}).get(which)


def dumps(layout):
    layout = clean(layout)
    return json.dumps(layout, separators=(',', ':')) if layout else None
