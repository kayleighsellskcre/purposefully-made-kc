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
