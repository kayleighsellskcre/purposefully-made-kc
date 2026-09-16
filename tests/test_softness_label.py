"""Softness label helper on Product."""
from models import Product


def test_softness_label_maps_rating():
    p = Product(style_number='X', name='Test', base_price=1)
    p.softness_rating = 4
    assert p.softness_label == 'Ultra Soft'
    p.softness_rating = 1
    assert p.softness_label == 'Everyday'
    p.softness_rating = None
    assert p.softness_label is None
    p.softness_rating = 9
    assert p.softness_label is None


def test_port_company_tiedye_uses_artisan_soft_label():
    for style in Product.PORT_COMPANY_TIEDYE_STYLES:
        p = Product(style_number=style, name='Port & Company Tie-Dye', base_price=1)
        p.softness_rating = 2
        assert p.softness_label == 'Artisan Soft'
