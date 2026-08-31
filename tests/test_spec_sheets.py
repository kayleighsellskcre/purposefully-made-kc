"""Brand-aware Spec Sheet URL resolution."""
from utils.spec_sheets import (
    SIZE_CHART_SENTINEL,
    is_broken_spec_url,
    is_usable_spec_sheet_url,
    normalize_style_for_spec,
    resolve_spec_sheet_target,
    resolve_spec_sheet_url,
)


class _ProductStub:
    def __init__(self, style_number=None, spec_sheet_url=None, brand=None, size_chart=None):
        self.style_number = style_number
        self.spec_sheet_url = spec_sheet_url
        self.brand = brand
        self.size_chart = size_chart


def test_bella_uses_manufacturer_spec_pdf_not_sanmar_cdn():
    product = _ProductStub(
        style_number='BC3001',
        brand='Bella+Canvas',
        spec_sheet_url='https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001.pdf',
    )
    url = resolve_spec_sheet_url(product)
    assert url == 'https://www.bellacanvas.com/spec/3001%20specs.pdf'
    assert 'sanmar.com' not in url


def test_bella_cvc_uses_style_specific_spec_pdf():
    product = _ProductStub(
        style_number='BC3001CVC',
        brand='Bella+Canvas',
        spec_sheet_url='https://www.bellacanvas.com/3001CVC',
    )
    url = resolve_spec_sheet_url(product)
    assert url == 'https://www.bellacanvas.com/spec/3001CVC%20specs.pdf'


def test_c2_sport_uses_brand_site():
    product = _ProductStub(style_number='5100', brand='C2 Sport')
    assert resolve_spec_sheet_url(product) == 'https://www.c2sport.com/products/5100'


def test_mv_sport_uses_ss_activewear_style_id():
    product = _ProductStub(style_number='17116', brand='MV Sport')
    assert resolve_spec_sheet_url(product) == 'https://www.ssactivewear.com/p/7466'


def test_comfort_colors_uses_brand_search():
    product = _ProductStub(
        style_number='CC1717',
        brand='Comfort Colors',
        size_chart='{"M":{"chest":"20","length":"28"}}',
    )
    url = resolve_spec_sheet_url(product)
    assert 'comfortcolors.com' in url
    assert '1717' in url
    target = resolve_spec_sheet_target(product)
    assert target['mode'] == 'external'
    assert '1717' in target['url']


def test_broken_sanmar_and_bella_short_urls_detected():
    assert is_broken_spec_url('https://www.sanmar.com/p/BC3001')
    assert is_broken_spec_url('https://cdnm.sanmar.com/SpecSheetMeasurements/CC1717.pdf')
    assert is_broken_spec_url('https://www.bellacanvas.com/3001CVC')
    assert is_broken_spec_url('https://www.bellacanvas.com/3001')
    assert not is_broken_spec_url('https://www.bellacanvas.com/spec/3001%20specs.pdf')
    assert not is_broken_spec_url('https://www.bellacanvas.com/product/3001CVC/')
    assert not is_usable_spec_sheet_url('https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001.pdf')
    assert not is_usable_spec_sheet_url('https://www.bellacanvas.com/3001CVC')


def test_normalize_style_for_spec_uppercases():
    assert normalize_style_for_spec('pc147ls') == 'PC147LS'
    assert normalize_style_for_spec('  bc3001  ') == 'BC3001'


def test_size_chart_sentinel_constant():
    assert SIZE_CHART_SENTINEL.startswith('__')


def test_port_company_uses_ss_search():
    product = _ProductStub(style_number='PC54', brand='Port & Company')
    assert 'ssactivewear.com/search?q=PC54' in resolve_spec_sheet_url(product)
