"""What a new group order starts with: the styles and shirt colors we recommend.

Nothing here limits the organizer. Every other style and color stays in the lists, unchecked, ready to be added.
"""
from __future__ import annotations

import re

from utils.product_filters import _bare_style, infer_age

# The styles that start checked, by style number with any BC prefix dropped: adult styles, plus the youth, toddler
# and baby versions of the ones in this list. Every other style is still offered, just not checked.
DEFAULT_STYLES = {
    # hoodies
    '3739', '3719', 'W23716', 'PC146', '3719Y', 'PC146Y', '3719T',
    # long sleeve
    '3501', 'PC147LS', '3501Y', 'PC147YLS', '3501T',
    # onesie
    '100B',
    # sweatshirts
    '3901', 'CC1466', '3901Y',
    # tank
    '8800',
    # tees
    '3001', 'PC147', '3001Y', 'PC147Y', '3001T', '3001B',
    # v-neck
    '3005', 'LPC147V',
}

KID_AGES = ('youth', 'toddler', 'baby')

# Favorite group-order colors, by name (matched without caring about case, dashes, or grey/gray).
FAVORITE_COLORS = {
    'natural', 'natural heather', 'heather natural',
    'navy', 'heather navy',
    'athletic heather', 'deep heather', 'dark gray heather',
    'solid black blend', 'solid white blend', 'solid red blend', 'heather red',
}
# A plain color is a fallback: used only when the style has no matching "solid ... blend" color.
FALLBACKS = (('black', 'solid black blend'), ('white', 'solid white blend'), ('red', 'solid red blend'))
TIE_DYE_COLORS = {'rainbow', 'pastel rainbow', 'neon rainbow'}


def normal_color(name):
    text = re.sub(r'[\s_/,-]+', ' ', (name or '').strip().lower())
    return text.replace('grey', 'gray').strip()


def favorite_colors(color_names, tie_dye=False):
    """The subset of a style's color names that start checked."""
    names = list(color_names)
    norm = {n: normal_color(n) for n in names}
    if tie_dye:
        return [n for n in names if norm[n] in TIE_DYE_COLORS]
    have = set(norm.values())
    picked = [n for n in names if norm[n] in FAVORITE_COLORS]
    for plain, preferred in FALLBACKS:
        if preferred not in have:
            picked += [n for n in names if norm[n] == plain and n not in picked]
    return picked


def is_tie_dye(product):
    text = f"{getattr(product, 'name', '')} {getattr(product, 'style_number', '')}".lower()
    return 'tie-dye' in text or 'tie dye' in text


def default_style_ids(products, ages=None):
    """Ids of the styles that start checked. ``ages`` limits it ('adult' only, or the kids' ages only)."""
    out = []
    for product in products or []:
        if _bare_style(product.style_number) not in DEFAULT_STYLES:
            continue
        if ages is not None:
            age = getattr(product, 'display_age', None) or infer_age(product) or 'adult'
            if age not in ages:
                continue
        out.append(product.id)
    return out


def default_fan_color_keys(picker, products):
    """The 'p:<id>||Color' boxes that start checked, for every style, so any style someone adds starts the same way."""
    picker = picker or {}
    palette = picker.get('palette') or []
    by_product = picker.get('products') or {}
    by_id = {str(p.id): p for p in products or []}
    keys = []
    for pid, indexes in by_product.items():
        product = by_id.get(str(pid))
        names = [palette[i][0] for i in indexes if 0 <= i < len(palette)]
        for name in favorite_colors(names, tie_dye=bool(product and is_tie_dye(product))):
            keys.append(f'p:{pid}||{name}')
    return keys
