"""Guard supplier style numbers against garment-identity regressions."""
from scripts.add_new_brands import NEW_PRODUCTS
from scripts.fix_images_from_ss import TARGET_STYLES
from scripts.fix_product_identity import (
    IDENTITY_FIXES,
    _INDEPENDENT_FABRICS,
    resolve_fix,
)


def _new_product(style):
    return next(p for p in NEW_PRODUCTS if p['style_number'] == style)


def test_dt8000_is_recycled_short_sleeve_tee_everywhere():
    source = _new_product('DT8000')
    fix = resolve_fix('DT8000')

    for record in (source, fix):
        assert record['name'] == 'District Re-Tee'
        assert record['category'] == 'Tee'
        assert record['neck_style'] == 'Crew Neck'
        assert record['sleeve_length'] == 'Short Sleeve'
        assert '5.3 oz' in record['fabric_details']
        assert '60% recycled cotton' in record['fabric_details']
        assert '40% recycled polyester' in record['fabric_details']
        assert 'color blends vary' in record['fabric_details']
        assert 'jersey' in record['fabric_details']


def test_other_confirmed_supplier_identities_are_canonical():
    assert resolve_fix('DM130')['category'] == 'Tee'
    assert '50% polyester' in resolve_fix('DM130')['fabric_details']
    assert resolve_fix('RS3401')['name'] == (
        'Rabbit Skins Infant Cotton Jersey Tee'
    )
    assert resolve_fix('RS4400')['category'] == 'Onesie'
    assert resolve_fix('3719T')['sleeve_length'] == 'Long Sleeve'
    assert resolve_fix('3501T')['category'] == 'Long Sleeve'
    assert resolve_fix('ST254')['neck_style'] == 'Quarter-Zip'
    assert TARGET_STYLES['RS3401']['ss_style_id'] == 517
    tank = resolve_fix('CC9360')
    assert tank['category'] == 'Tank'
    assert tank['sleeve_length'] == 'Sleeveless'
    assert resolve_fix('9360')['category'] == 'Tank'


def test_independent_fleece_cannot_regress_to_short_sleeve():
    for style in _INDEPENDENT_FABRICS:
        fix = IDENTITY_FIXES[style]
        assert fix['sleeve_length'] == 'Long Sleeve'
        assert fix['fabric_details']


def test_comfort_colors_9360_is_in_the_sanmar_curated_list():
    from services.sanmar_api import style_is_allowed
    from services.sanmar_catalog import CURATED_BRANDS

    cc = next(b for b in CURATED_BRANDS if b['name'] == 'Comfort Colors')
    assert style_is_allowed('9360', cc['styles'])
    assert style_is_allowed('CC9360', cc['styles'])
    assert style_is_allowed('C9360', cc['styles'])
