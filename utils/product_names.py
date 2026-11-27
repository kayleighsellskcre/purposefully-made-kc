"""Customer-facing product titles. Stored supplier names stay untouched."""
from __future__ import annotations

import re

_REG_MARK = re.compile(
    r'(?:\u00ae|\ufffd|\(R\)|\(r\)|&reg;|&#174;)',
    re.IGNORECASE,
)
_TRAILING_STYLE = re.compile(r'[\s.]+[A-Z]{1,6}\d{2,}[A-Z0-9]*\s*$')


def display_product_name(product_or_name, style_number=None):
    """Drop registered marks and a trailing style code. Keep the brand name."""
    if product_or_name is None:
        return 'Product'
    if not isinstance(product_or_name, str):
        style_number = style_number or getattr(product_or_name, 'style_number', None)
        product_or_name = getattr(product_or_name, 'name', None) or ''
    text = _REG_MARK.sub('', str(product_or_name))
    text = re.sub(r'\s+', ' ', text).strip(' .')
    style = str(style_number or '').strip()
    if style:
        text = re.sub(
            r'[\s.\-]*' + re.escape(style) + r'\s*$',
            '',
            text,
            flags=re.IGNORECASE,
        ).strip(' .')
    else:
        text = _TRAILING_STYLE.sub('', text).strip(' .')
    return text or re.sub(r'\s+', ' ', str(product_or_name)).strip() or 'Product'


def without_brand(title, brand):
    """The title with the brand taken off the front, for a card that already prints the brand on its own line."""
    title = str(title or '').strip()
    brand = re.sub(r'\s+', ' ', str(brand or '')).strip()
    if not title or not brand:
        return title
    squash = lambda t: re.sub(r'[^a-z0-9+]', '', t.lower())
    words = title.split(' ')
    for n in range(1, min(len(words), 4) + 1):          # the brand can be one to four words ("Bella + Canvas", "Port & Company")
        if squash(' '.join(words[:n])) == squash(brand):
            rest = ' '.join(words[n:]).strip()
            return rest or title
    return title


def shop_title(product):
    """The same friendly title a shop card shows: no mark, no style code, no brand in front."""
    if product is None:
        return 'Item'
    from utils.product_filters import infer_brand
    brand = getattr(product, 'display_brand', None) or infer_brand(product) or ''
    return without_brand(display_product_name(product), brand)


def design_label(title):
    """'Lion of Judah' -> 'Lion of Judah design'; a title that already says design is left as is."""
    title = re.sub(r'\s+', ' ', str(title or '')).strip()
    if not title:
        return ''
    return title if re.search(r'\bdesigns?\b', title, re.I) else f'{title} design'


TITLE_SUFFIX = ' - Purposefully Made KC'
TITLE_LIMIT = 60
_BRAND_LEAD = re.compile(r'^(?:bella\s*\+\s*canvas|comfort colors|gildan|port & company|next level|independent trading co\.?|rabbit skins)\s+', re.I)


def fit_title(name, prefix='', suffix=TITLE_SUFFIX, limit=TITLE_LIMIT):
    """prefix + name, trimmed at a word so that with the suffix the whole page title is at most ``limit`` characters."""
    name = re.sub(r'\s+', ' ', str(name or '')).strip()
    room = limit - len(prefix) - len(suffix)
    if len(name) <= room:
        return prefix + name
    shorter = _BRAND_LEAD.sub('', name)              # the brand is the least useful part of a long title
    if shorter != name:
        if len(shorter) <= room:
            return prefix + shorter
        if len(shorter) <= limit - len(suffix):
            return shorter
        name = shorter
    if len(name) <= limit - len(suffix):
        return name                                  # the whole name matters more than the word "Customize"
    room = max(limit - len(suffix), 1)               # too long even alone: drop the prefix, keep as much of the name as fits
    cut = name[:room].rsplit(' ', 1)[0] if ' ' in name[:room + 1] else name[:room]
    return cut.rstrip(' ,.-&/')
