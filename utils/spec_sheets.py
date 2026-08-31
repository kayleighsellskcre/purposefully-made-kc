"""Resolve Spec Sheet links by brand / distributor.

SanMar's old product pages (sanmar.com/p/STYLE) and CDN measurement PDFs
(cdnm.sanmar.com/SpecSheetMeasurements/*.pdf) currently return HTML
"File Not Found" and must never be used.

Preferred destinations:
- Bella+Canvas: brand product page (/product/{STYLE}/) which includes size chart
- C2 / MV / Comfort Colors / Gildan / Rabbit Skins: S&S Activewear style page
- Port & Company / Sport-Tek / District: SanMar catalog search (public)
- Stanley/Stella: official ProductSheet PDF when available
"""
from __future__ import annotations

import re
from urllib.parse import quote

# Template sentinel: open the on-site size-chart modal instead of an external URL.
SIZE_CHART_SENTINEL = '__onsite_size_chart__'

# S&S Activewear styleIDs for brands carried on S&S (browser-facing catalog).
# Keys are normalized uppercase style numbers as stored on Product.style_number
# (and common stripped forms for Comfort Colors / Gildan / Rabbit Skins).
SS_ACTIVEWEAR_STYLE_IDS = {
    # C2 Sport
    '5100': 2281,
    '5200': 2485,
    '5600': 2731,
    '5104': 2484,
    # MV Sport
    '17116': 7466,
    '496': 12262,
    'W23716': 11175,
    'W25167': 16260,
    # Comfort Colors (SanMar CC#### and bare ####)
    'CC1717': 1822,
    '1717': 1822,
    'CC1566': 1610,
    '1566': 1610,
    'CC1466': 11675,
    '1466': 11675,
    # Gildan
    'G64000': 32,
    '64000': 32,
    'G18500': 395,
    '18500': 395,
    'G18000': 372,
    '18000': 372,
    'G64400': 1941,
    '64400': 1941,
    'G64500': 2116,  # Softstyle V-Neck (S&S styleName 64V00)
    '64500': 2116,
    '64V00': 2116,
    # Rabbit Skins
    'RS3401': 517,
    '3401': 517,
    'RS3321': 2573,
    '3321': 2573,
    'RS4400': 520,
    '4400': 520,
}

_BROKEN_SANMAR_PRODUCT_PAGE = re.compile(
    r'^https?://(?:www\.)?sanmar\.com/p/([^/?#]+)/?$',
    re.IGNORECASE,
)
_BROKEN_SANMAR_CDN = re.compile(
    r'^https?://cdn[-.]?nm\.sanmar\.com/(?:SpecSheetMeasurements/|medias/.*/SpecSheets/)',
    re.IGNORECASE,
)
# Old builder used https://www.bellacanvas.com/{style} — that 404s for many styles.
# Keep /product/ and /spec/.
_BROKEN_BELLA_SHORT = re.compile(
    r'^https?://(?:www\.)?bellacanvas\.com/([^/?#]+)/?$',
    re.IGNORECASE,
)
# Bella measurement PDFs exist for some styles but 404 for others (3005, 3413, …).
# Prefer /product/ pages; treat leftover /spec/ PDF links as stale so we rewrite.
_BROKEN_BELLA_SPEC_PDF = re.compile(
    r'^https?://(?:www\.)?bellacanvas\.com/spec/',
    re.IGNORECASE,
)
# Brand homepage-only fallbacks are not style-specific.
_WEAK_HOMEPAGE_ONLY = re.compile(
    r'^https?://(?:www\.)?(?:mvsport\.com|c2sport\.com)/?$',
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
    if _BROKEN_BELLA_SPEC_PDF.match(u):
        return True
    m = _BROKEN_BELLA_SHORT.match(u)
    if m:
        first = (m.group(1) or '').lower()
        if first not in ('product', 'spec', 'fit-size-charts', 'search'):
            return True
    if _WEAK_HOMEPAGE_ONLY.match(u):
        return True
    # Old Comfort Colors / Gildan search pages; prefer S&S style pages now.
    if 'comfortcolors.com' in u.lower() and '/search' in u.lower():
        return True
    if 'gildan.com' in u.lower() and '/search' in u.lower():
        return True
    # S&S search is weaker than a direct /p/{id} page when we know the id.
    if 'ssactivewear.com/search' in u.lower():
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
    if not style:
        return ''
    sid = SS_ACTIVEWEAR_STYLE_IDS.get(style)
    if not sid:
        # Try stripped Comfort / Gildan / Rabbit forms
        for alt in (
            _strip_comfort_prefix(style),
            _strip_gildan_noise(style),
            style[2:] if style.startswith('RS') else '',
        ):
            if alt and alt in SS_ACTIVEWEAR_STYLE_IDS:
                sid = SS_ACTIVEWEAR_STYLE_IDS[alt]
                break
    if not sid:
        return ''
    return f'https://www.ssactivewear.com/p/{sid}'


def sanmar_search_url(style_number: str | None) -> str:
    style = normalize_style_for_spec(style_number)
    if not style:
        return ''
    return f'https://www.sanmar.com/search?text={quote(style)}'


def stanley_stella_spec_url(style_number: str | None) -> str:
    style = normalize_style_for_spec(style_number)
    if not style:
        return ''
    # Official bilingual product sheets (measurement + details).
    return f'https://api.stanleystella.com/ProductSheet/en_US/{quote(style)}.pdf'


def brand_spec_sheet_url(brand: str | None, style_number: str | None) -> str:
    """Best public product / size page for this brand + style.

    Returns SIZE_CHART_SENTINEL when the shopper should use the on-site chart.
    """
    style = normalize_style_for_spec(style_number)
    key = _brand_key(brand)

    if not style and not key:
        return ''

    # ── S&S Activewear brands ───────────────────────────────────────────────
    if key in ('c2sport', 'c2'):
        ss = ss_activewear_style_url(style)
        if ss:
            return ss
        if style:
            return f'https://www.c2sport.com/products/{style}'
        return 'https://www.c2sport.com/'

    if key in ('mvsport', 'mv'):
        ss = ss_activewear_style_url(style)
        if ss:
            return ss
        if style:
            return f'https://www.ssactivewear.com/search?q={quote(style)}'
        return 'https://www.mvsport.com/'

    # ── Manufacturer sites ──────────────────────────────────────────────────
    if key in ('bellacanvas', 'bella') or ('bella' in key and 'canvas' in key):
        path = _strip_bella_prefix(style) if style else ''
        if path:
            # Product pages are reliable for every style we carry; many /spec/
            # measurement PDFs 404 (3005, 3413, youth CVC, etc.).
            return f'https://www.bellacanvas.com/product/{quote(path)}/'
        return 'https://www.bellacanvas.com/'

    if 'comfortcolors' in key or key == 'comfort':
        ss = ss_activewear_style_url(style) or ss_activewear_style_url(
            _strip_comfort_prefix(style)
        )
        if ss:
            return ss
        path = _strip_comfort_prefix(style) if style else ''
        if path:
            return f'https://www.ssactivewear.com/search?q={quote(path)}'
        return SIZE_CHART_SENTINEL

    if 'portcompany' in key or key.startswith('port'):
        return sanmar_search_url(style) or SIZE_CHART_SENTINEL

    if 'gildan' in key:
        ss = ss_activewear_style_url(style) or ss_activewear_style_url(
            _strip_gildan_noise(style)
        )
        if ss:
            return ss
        path = _strip_gildan_noise(style) if style else ''
        if path:
            return f'https://www.ssactivewear.com/search?q={quote(path)}'
        return SIZE_CHART_SENTINEL

    if 'rabbit' in key:
        ss = ss_activewear_style_url(style)
        if ss:
            return ss
        path = style[2:] if style.upper().startswith('RS') else style
        if path:
            return f'https://www.ssactivewear.com/search?q={quote(path)}'
        return SIZE_CHART_SENTINEL

    if 'district' in key:
        return sanmar_search_url(style) or SIZE_CHART_SENTINEL

    if 'sporttek' in key:
        return sanmar_search_url(style) or SIZE_CHART_SENTINEL

    if 'stanley' in key or 'stella' in key:
        # Prefer official product sheet PDF; STSW013 and a few legacy codes 404,
        # so fall back to SanMar search for those.
        if style in ('STSW013',):
            return sanmar_search_url(style) or SIZE_CHART_SENTINEL
        return stanley_stella_spec_url(style) or SIZE_CHART_SENTINEL

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

    # Always prefer freshly built brand URLs so catalog improvements apply
    # even when the DB still holds an older "usable" link.
    built = brand_spec_sheet_url(brand_name, style)
    if built:
        return built

    if is_usable_spec_sheet_url(existing):
        return existing

    # Last resort: recover style from legacy /p/STYLE and try brand-less C2/MV map
    m = _BROKEN_SANMAR_PRODUCT_PAGE.match(existing)
    if m:
        recovered = normalize_style_for_spec(m.group(1))
        ss = ss_activewear_style_url(recovered)
        if ss:
            return ss
        if recovered.startswith('BC') or recovered.isdigit() or (
            len(recovered) > 2 and recovered[0].isdigit()
        ):
            path = _strip_bella_prefix(recovered)
            return f'https://www.bellacanvas.com/product/{quote(path)}/'

    return ''


def resolve_spec_sheet_target(product) -> dict:
    """Template helper: {mode: 'external'|'size_chart'|'', url: str}."""
    url = resolve_spec_sheet_url(product)
    has_chart = bool((getattr(product, 'size_chart', None) or '').strip())
    style = normalize_style_for_spec(getattr(product, 'style_number', None))

    if url == SIZE_CHART_SENTINEL:
        if has_chart:
            return {'mode': 'size_chart', 'url': ''}
        brand = getattr(product, 'brand', None)
        key = _brand_key(brand)
        search_q = style
        if 'comfort' in key:
            search_q = _strip_comfort_prefix(style) or style
        if search_q:
            # SanMar brands land better on SanMar search; others on S&S.
            if key.startswith('port') or 'district' in key or 'sporttek' in key:
                return {'mode': 'external', 'url': sanmar_search_url(search_q)}
            return {
                'mode': 'external',
                'url': f'https://www.ssactivewear.com/search?q={quote(search_q)}',
            }
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
    """Replace stale / dead Spec Sheet URLs with current brand/S&S/SanMar targets."""
    updated = 0
    for product in Product.query.filter(Product.style_number.isnot(None)).all():
        desired = brand_spec_sheet_url(product.brand, product.style_number)
        if desired == SIZE_CHART_SENTINEL:
            desired = ''
        if not desired:
            desired = resolve_spec_sheet_url(product)
            if desired == SIZE_CHART_SENTINEL:
                desired = ''
        current = (product.spec_sheet_url or '').strip()
        if current == desired:
            continue
        # Rewrite when empty, broken/weak, or simply out of date vs brand rules.
        if (
            not current
            or is_broken_spec_url(current)
            or current != desired
        ):
            product.spec_sheet_url = desired or None
            updated += 1
    if updated:
        db_session.commit()
    return updated


# Back-compat alias used by older tests / imports
def sanmar_cdn_spec_sheet_url(style_number: str | None) -> str:
    """Deprecated. SanMar CDN PDFs are dead. Returns ''."""
    return ''
