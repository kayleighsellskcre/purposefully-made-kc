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


def test_bella_uses_product_page_not_sanmar_cdn():
    product = _ProductStub(
        style_number='BC3001',
        brand='Bella+Canvas',
        spec_sheet_url='https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001.pdf',
    )
    url = resolve_spec_sheet_url(product)
    assert url == 'https://www.bellacanvas.com/product/3001/'
    assert 'sanmar.com' not in url


def test_bella_cvc_uses_style_specific_product_page():
    product = _ProductStub(
        style_number='BC3001CVC',
        brand='Bella+Canvas',
        spec_sheet_url='https://www.bellacanvas.com/3001CVC',
    )
    url = resolve_spec_sheet_url(product)
    assert url == 'https://www.bellacanvas.com/product/3001CVC/'


def test_bella_prefers_product_page_over_stale_spec_pdf():
    product = _ProductStub(
        style_number='BC3005',
        brand='Bella+Canvas',
        spec_sheet_url='https://www.bellacanvas.com/spec/3005%20specs.pdf',
    )
    assert resolve_spec_sheet_url(product) == 'https://www.bellacanvas.com/product/3005/'


_SS_SPEC = (
    'https://www.ssactivewear.com/ShopNow/ItemSpecSheet.aspx'
    '?ID={}&LanguageCode=en'
)


def test_c2_sport_uses_ss_item_spec_sheet():
    product = _ProductStub(style_number='5100', brand='C2 Sport')
    assert resolve_spec_sheet_url(product) == _SS_SPEC.format(2281)


def test_mv_sport_uses_ss_activewear_style_id():
    product = _ProductStub(style_number='17116', brand='MV Sport')
    assert resolve_spec_sheet_url(product) == _SS_SPEC.format(7466)


def test_mv_sport_womens_styles_have_ss_ids():
    assert resolve_spec_sheet_url(
        _ProductStub(style_number='W23716', brand='MV Sport')
    ) == _SS_SPEC.format(11175)
    assert resolve_spec_sheet_url(
        _ProductStub(style_number='W25167', brand='MV Sport')
    ) == _SS_SPEC.format(16260)


def test_comfort_colors_uses_ss_style_page():
    product = _ProductStub(
        style_number='CC1717',
        brand='Comfort Colors',
        size_chart='{"M":{"chest":"20","length":"28"}}',
    )
    url = resolve_spec_sheet_url(product)
    assert url == _SS_SPEC.format(1822)
    target = resolve_spec_sheet_target(product)
    assert target['mode'] == 'external'
    assert target['url'] == url


def test_gildan_uses_ss_style_page():
    product = _ProductStub(style_number='G64000', brand='Gildan')
    assert resolve_spec_sheet_url(product) == _SS_SPEC.format(32)


def test_port_company_uses_sanmar_spec_sheet_measurements():
    product = _ProductStub(style_number='PC54', brand='Port & Company')
    assert resolve_spec_sheet_url(product) == 'https://www.sanmar.com/p/3985/specSheetMeasurements'


def test_sport_tek_uses_sanmar_spec_sheet_measurements():
    product = _ProductStub(style_number='ST350', brand='Sport-Tek')
    assert resolve_spec_sheet_url(product) == 'https://www.sanmar.com/p/4349/specSheetMeasurements'


def test_sanmar_style_without_known_id_uses_spec_pdf():
    product = _ProductStub(style_number='STSW013', brand='Stanley/Stella')
    url = resolve_spec_sheet_url(product)
    assert url.endswith('SpecSheetMeasurements_STSW013.pdf')
    assert 'companycasuals.com' in url


def test_stanley_stella_uses_product_sheet_pdf():
    product = _ProductStub(style_number='STTU755', brand='Stanley/Stella')
    assert resolve_spec_sheet_url(product).endswith('/STTU755.pdf')
    assert 'stanleystella.com' in resolve_spec_sheet_url(product)


def test_broken_urls_detected():
    assert is_broken_spec_url('https://www.sanmar.com/p/BC3001')
    assert is_broken_spec_url('https://cdnm.sanmar.com/SpecSheetMeasurements/CC1717.pdf')
    assert is_broken_spec_url('https://www.bellacanvas.com/3001CVC')
    assert is_broken_spec_url('https://www.bellacanvas.com/3001')
    assert is_broken_spec_url('https://www.bellacanvas.com/spec/3001%20specs.pdf')
    assert is_broken_spec_url('https://www.mvsport.com/')
    assert is_broken_spec_url('https://www.ssactivewear.com/search?q=PC54')
    assert is_broken_spec_url('https://www.ssactivewear.com/p/2281')
    assert not is_broken_spec_url(_SS_SPEC.format(2281))
    assert not is_broken_spec_url('https://www.bellacanvas.com/product/3001CVC/')
    assert not is_usable_spec_sheet_url('https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001.pdf')
    assert not is_usable_spec_sheet_url('https://www.bellacanvas.com/3001CVC')
    assert not is_usable_spec_sheet_url('https://www.ssactivewear.com/p/2281')


def test_normalize_style_for_spec_uppercases():
    assert normalize_style_for_spec('pc147ls') == 'PC147LS'
    assert normalize_style_for_spec('  bc3001  ') == 'BC3001'


def test_size_chart_sentinel_constant():
    assert SIZE_CHART_SENTINEL.startswith('__')
