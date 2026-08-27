"""SanMar spec-sheet URL resolution helpers."""
from utils.spec_sheets import (
    is_usable_spec_sheet_url,
    normalize_style_for_spec,
    resolve_spec_sheet_url,
)


class _ProductStub:
    def __init__(self, style_number=None, spec_sheet_url=None):
        self.style_number = style_number
        self.spec_sheet_url = spec_sheet_url


def test_resolve_broken_product_page_url_to_cdn():
    product = _ProductStub(
        style_number='PC147',
        spec_sheet_url='https://www.sanmar.com/p/PC147',
    )
    assert resolve_spec_sheet_url(product) == (
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147.pdf'
    )


def test_resolve_empty_url_with_style_number_to_cdn():
    product = _ProductStub(style_number='BC3001', spec_sheet_url='')
    assert resolve_spec_sheet_url(product) == (
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001.pdf'
    )


def test_is_usable_spec_sheet_url_accepts_cdn_pdf():
    url = 'https://cdnm.sanmar.com/SpecSheetMeasurements/G64000.pdf'
    assert is_usable_spec_sheet_url(url) is True


def test_normalize_style_for_spec_uppercases():
    assert normalize_style_for_spec('pc147ls') == 'PC147LS'
    assert normalize_style_for_spec('  bc3001  ') == 'BC3001'
