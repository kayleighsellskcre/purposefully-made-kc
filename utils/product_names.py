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


def fit_title(name, prefix='', suffix=TITLE_SUFFIX, limit=TITLE_LIMIT):
    """prefix + name, trimmed at a word so that with the suffix the whole page title is at most ``limit`` characters."""
    name = re.sub(r'\s+', ' ', str(name or '')).strip()
    room = limit - len(prefix) - len(suffix)
    if len(name) <= room:
        return prefix + name
    if len(name) <= limit - len(suffix):
        return name                                  # the whole name matters more than the word "Customize"
    cut = name[:max(room, 1)].rsplit(' ', 1)[0] if ' ' in name[:max(room, 1) + 1] else name[:max(room, 1)]
    return prefix + cut.rstrip(' ,.-&/')
