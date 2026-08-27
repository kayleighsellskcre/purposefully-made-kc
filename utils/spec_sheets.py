"""Resolve working SanMar spec-sheet PDF URLs.

Historical product rows used https://www.sanmar.com/p/{STYLE}, which now 404s.
Official measurement PDFs live on SanMar's CDN:

    https://cdnm.sanmar.com/SpecSheetMeasurements/{STYLE}.pdf
"""
from __future__ import annotations

import re

CDN_SPEC_SHEET_TMPL = 'https://cdnm.sanmar.com/SpecSheetMeasurements/{style}.pdf'
_BROKEN_SANMAR_PRODUCT_PAGE = re.compile(
    r'^https?://(?:www\.)?sanmar\.com/p/([^/?#]+)/?$',
    re.IGNORECASE,
)
_CDN_SPEC_RE = re.compile(
    r'^https?://cdnm\.sanmar\.com/SpecSheetMeasurements/[^/?#]+\.pdf$',
    re.IGNORECASE,
)


def normalize_style_for_spec(style_number: str | None) -> str:
    """Uppercase style code suitable for the SanMar SpecSheetMeasurements PDF name."""
    style = (style_number or '').strip()
    if not style:
        return ''
    # Drop accidental .pdf / path junk
    style = style.replace('\\', '/').split('/')[-1]
    if style.lower().endswith('.pdf'):
        style = style[:-4]
    return style.upper()


def sanmar_cdn_spec_sheet_url(style_number: str | None) -> str:
    style = normalize_style_for_spec(style_number)
    if not style:
        return ''
    return CDN_SPEC_SHEET_TMPL.format(style=style)


def is_usable_spec_sheet_url(url: str | None) -> bool:
    """True when the stored URL already points at a CDN measurement PDF."""
    u = (url or '').strip()
    return bool(u and _CDN_SPEC_RE.match(u))


def resolve_spec_sheet_url(product_or_url=None, style_number: str | None = None) -> str:
    """Return a working spec-sheet URL for templates and APIs.

    Accepts a Product-like object, a raw URL string, or style_number kwarg.
    Always prefers the SanMar CDN PDF derived from the style number so broken
    /p/ product-page links and missing DB values still get a Spec Sheet button.
    """
    existing = ''
    style = normalize_style_for_spec(style_number)

    if product_or_url is not None and not isinstance(product_or_url, str):
        existing = (getattr(product_or_url, 'spec_sheet_url', None) or '').strip()
        if not style:
            style = normalize_style_for_spec(getattr(product_or_url, 'style_number', None))
    elif isinstance(product_or_url, str):
        existing = product_or_url.strip()

    if is_usable_spec_sheet_url(existing):
        return existing

    if style:
        return sanmar_cdn_spec_sheet_url(style)

    # Recover style from legacy sanmar.com/p/STYLE bookmarks
    m = _BROKEN_SANMAR_PRODUCT_PAGE.match(existing)
    if m:
        return sanmar_cdn_spec_sheet_url(m.group(1))

    # Local static SDL path that was never uploaded → fall through empty
    if existing.startswith('/static/') or existing.startswith('static/'):
        return ''

    return existing if existing.startswith('http') else ''


def rewrite_broken_spec_sheet_urls(db_session, Product) -> int:
    """One-time / startup repair: set CDN PDF URLs for every product with a style.

    Returns the number of rows updated.
    """
    updated = 0
    for product in Product.query.filter(Product.style_number.isnot(None)).all():
        style = normalize_style_for_spec(product.style_number)
        if not style:
            continue
        desired = sanmar_cdn_spec_sheet_url(style)
        current = (product.spec_sheet_url or '').strip()
        if current == desired:
            continue
        # Rewrite missing, broken /p/ pages, stale local paths, or non-CDN http links
        if (
            not current
            or _BROKEN_SANMAR_PRODUCT_PAGE.match(current)
            or current.startswith('/static/')
            or current.startswith('static/')
            or (
                current.startswith('http')
                and 'SpecSheetMeasurements' not in current
            )
        ):
            product.spec_sheet_url = desired
            updated += 1
    if updated:
        db_session.commit()
    return updated
