"""Resolve Spec Sheet links by brand / distributor.

SanMar's old product pages (sanmar.com/p/STYLE) and CDN measurement PDFs
(cdnm.sanmar.com/SpecSheetMeasurements/*.pdf) currently return HTML
"File Not Found" — they must never be used.

C2 Sport and MV Sport are S&S Activewear brands — use their brand / S&S pages.
Bella+Canvas and other mills use manufacturer product pages when known.
Otherwise the UI opens the on-site size chart modal.
"""
from __future__ import annotations

import re

# Template sentinel: open the on-site size-chart modal instead of an external URL.
SIZE_CHART_SENTINEL = '__onsite_size_chart__'

# S&S Activewear styleIDs for brands that are NOT SanMar (browser-facing catalog).
# Kept in sync with scripts/fix_missing_flat_images.py STYLE_ID_HINTS.
SS_ACTIVEWEAR_STYLE_IDS = {
    # C2 Sport
    '5100': 2281,
    '5200': 2485,
    '5600': 2731,
    '5104': 2730,  # best-effort; verify if admin notices a miss
    # MV Sport
    '17116': 7466,
    '496': 12262,
}

_BROKEN_SANMAR_PRODUCT_PAGE = re.compile(
    r'^https?://(?:www\.)?sanmar\.com/p/([^/?#]+)/?$',
    re.IGNORECASE,
)
_BROKEN_SANMAR_CDN = re.compile(
    r'^https?://cdn[-.]?nm\.sanmar\.com/SpecSheetMeasurements/',
    re.IGNORECASE,
)


def normalize_style_for_spec(style_number: str | None) -> str:
    style = (style_number or '').strip()
    if not style:
        return ''
    style = style.replace('\\', '/').split('/')[-1]
    if style.lower().endswith('.pdf'):
        style = style[:-4]
    return style.upper()


def _brand_key(brand: str | None) -> str:
    b = (brand or '').lower()
    b = b.replace('+', '').replace('&', '').replace('/', ' ')
    return re.sub(r'[^a-z0-9]+', '', b)


def _strip_bella_prefix(style: str) -> str:
    s = style.upper()
    if s.startswith('BC'):
        return s[2:]
    return s


def _strip_comfort_prefix(style: str) -> str:
    s = style.upper()
    if s.startswith('CC') and len(s) > 2 and s[2:].isdigit():
        return s[2:]
    if s.startswith('C') and len(s) > 1 and s[1:].isdigit():
        return s[1:]
    return s


def _strip_gildan_noise(style: str) -> str:
    """Gildan Softstyle tee is often G64000 in SanMar / 64000 on brand sites."""
    s = style.upper()
    if s.startswith('G') and s[1:].isdigit():
        return s[1:]
    return s


def is_broken_spec_url(url: str | None) -> bool:
    u = (url or '').strip()
    if not u:
        return True
    if _BROKEN_SANMAR_PRODUCT_PAGE.match(u):
        return True
    if _BROKEN_SANMAR_CDN.match(u) or 'SpecSheetMeasurements' in u:
        return True
    if u.startswith('/static/') or u.startswith('static/'):
        return True
    return False


def is_usable_spec_sheet_url(url: str | None) -> bool:
    """True when a stored URL is an external page we can keep (not SanMar dead links)."""
    u = (url or '').strip()
    if not u.startswith('http'):
        return False
    if is_broken_spec_url(u):
        return False
    if u == SIZE_CHART_SENTINEL:
        return False
    return True


def ss_activewear_style_url(style_number: str | None) -> str:
    style = normalize_style_for_spec(style_number)
    sid = SS_ACTIVEWEAR_STYLE_IDS.get(style)
    if not sid:
        return ''
    return f'https://www.ssactivewear.com/p/{sid}'


def brand_spec_sheet_url(brand: str | None, style_number: str | None) -> str:
    """Best public product / size page for this brand + style.

    Returns SIZE_CHART_SENTINEL when the shopper should use the on-site chart.
    """
    style = normalize_style_for_spec(style_number)
    key = _brand_key(brand)

    if not style and not key:
        return ''

    # ── S&S Activewear brands (not SanMar) ──────────────────────────────────
    if key in ('c2sport', 'c2'):
        # Brand site works without login; S&S page as secondary via style id.
        if style:
            return f'https://www.c2sport.com/products/{style}'
        return 'https://www.c2sport.com/'

    if key in ('mvsport', 'mv'):
        ss = ss_activewear_style_url(style)
        if ss:
            return ss
        return 'https://www.mvsport.com/'

    # ── Manufacturer sites ──────────────────────────────────────────────────
    if key in ('bellacanvas', 'bella') or ('bella' in key and 'canvas' in key):
        path = _strip_bella_prefix(style) if style else ''
        if path:
            return f'https://www.bellacanvas.com/{path}'
        return 'https://www.bellacanvas.com/'

    if 'comfortcolors' in key or key == 'comfort':
        # Brand Shopify storefront paths are unreliable; use on-site chart.
        return SIZE_CHART_SENTINEL

    if 'portcompany' in key or key.startswith('port'):
        return SIZE_CHART_SENTINEL

    if 'gildan' in key:
        path = _strip_gildan_noise(style) if style else ''
        if path:
            return f'https://www.gildan.com/us/en/search?q={path}'
        return SIZE_CHART_SENTINEL

    if 'rabbit' in key:
        return SIZE_CHART_SENTINEL

    if 'district' in key:
        return SIZE_CHART_SENTINEL

    if 'sporttek' in key:
        return SIZE_CHART_SENTINEL

    if 'stanley' in key or 'stella' in key:
        return SIZE_CHART_SENTINEL

    # Unknown brand: prefer on-site chart over a broken SanMar guess
    return SIZE_CHART_SENTINEL


def resolve_spec_sheet_url(product_or_url=None, style_number: str | None = None,
                           brand: str | None = None) -> str:
    """Return external Spec Sheet URL, SIZE_CHART_SENTINEL, or ''."""
    existing = ''
    style = normalize_style_for_spec(style_number)
    brand_name = brand

    if product_or_url is not None and not isinstance(product_or_url, str):
        existing = (getattr(product_or_url, 'spec_sheet_url', None) or '').strip()
        if not style:
            style = normalize_style_for_spec(getattr(product_or_url, 'style_number', None))
        if not brand_name:
            brand_name = getattr(product_or_url, 'brand', None)
    elif isinstance(product_or_url, str):
        existing = product_or_url.strip()

    if is_usable_spec_sheet_url(existing):
        return existing

    built = brand_spec_sheet_url(brand_name, style)
    if built:
        return built

    # Last resort: recover style from legacy /p/STYLE and try brand-less C2/MV map
    m = _BROKEN_SANMAR_PRODUCT_PAGE.match(existing)
    if m:
        recovered = normalize_style_for_spec(m.group(1))
        ss = ss_activewear_style_url(recovered)
        if ss:
            return ss
        # Bella-looking codes
        if recovered.startswith('BC') or recovered.isdigit() or (
            len(recovered) > 2 and recovered[0].isdigit()
        ):
            return f'https://www.bellacanvas.com/{_strip_bella_prefix(recovered)}'

    return ''


def resolve_spec_sheet_target(product) -> dict:
    """Template helper: {mode: 'external'|'size_chart'|'', url: str}."""
    url = resolve_spec_sheet_url(product)
    has_chart = bool((getattr(product, 'size_chart', None) or '').strip())
    style = normalize_style_for_spec(getattr(product, 'style_number', None))

    if url == SIZE_CHART_SENTINEL:
        if has_chart:
            return {'mode': 'size_chart', 'url': ''}
        # No chart JSON yet — send shoppers to a live catalog search rather than
        # a dead SanMar PDF. Real browsers can open S&S; bots often get 403.
        if style:
            return {
                'mode': 'external',
                'url': f'https://www.ssactivewear.com/search?q={style}',
            }
        brand = getattr(product, 'brand', None)
        key = _brand_key(brand)
        if key in ('c2sport', 'c2'):
            return {'mode': 'external', 'url': 'https://www.c2sport.com/'}
        if key in ('mvsport', 'mv'):
            return {'mode': 'external', 'url': 'https://www.mvsport.com/'}
        if 'bella' in key:
            return {'mode': 'external', 'url': 'https://www.bellacanvas.com/'}
        return {'mode': '', 'url': ''}

    if url:
        return {'mode': 'external', 'url': url}

    if has_chart:
        return {'mode': 'size_chart', 'url': ''}

    return {'mode': '', 'url': ''}


def rewrite_broken_spec_sheet_urls(db_session, Product) -> int:
    """Replace dead SanMar links with brand/S&S URLs (or clear for on-site chart)."""
    updated = 0
    for product in Product.query.filter(Product.style_number.isnot(None)).all():
        desired = resolve_spec_sheet_url(product)
        if desired == SIZE_CHART_SENTINEL:
            desired = ''  # templates resolve to size-chart mode live
        current = (product.spec_sheet_url or '').strip()
        if current == desired:
            continue
        if (
            not current
            or is_broken_spec_url(current)
            or current != desired
        ):
            # Only rewrite when current is broken / empty / still the old CDN guess
            if not current or is_broken_spec_url(current) or 'sanmar.com' in current.lower():
                product.spec_sheet_url = desired or None
                updated += 1
    if updated:
        db_session.commit()
    return updated


# Back-compat alias used by older tests / imports
def sanmar_cdn_spec_sheet_url(style_number: str | None) -> str:
    """Deprecated — SanMar CDN PDFs are dead. Returns ''."""
    return ''
