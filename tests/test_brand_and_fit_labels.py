"""Round 2 audit item 9: small label fixes.

Brand names must show the same way everywhere (cards showed "BELLA+CANVAS",
the filter showed "Bella+Canvas"; standardized on "Bella+Canvas"). The fit
filter's Unisex option said "Men's (Unisex)" / "Boys (Unisex)" depending on
age group even though the underlying value never changes; it just says
"Unisex" now.
"""
from utils.product_filters import infer_brand


def test_infer_brand_normalizes_known_supplier_casing():
    assert infer_brand({'brand': 'BELLA+CANVAS', 'style_number': 'BC3001'}) == 'Bella+Canvas'
    assert infer_brand({'brand': 'Bella + Canvas', 'style_number': 'BC3001'}) == 'Bella+Canvas'
    assert infer_brand({'brand': 'bella+canvas', 'style_number': 'BC3001'}) == 'Bella+Canvas'


def test_infer_brand_leaves_an_unknown_stored_brand_alone():
    assert infer_brand({'brand': 'Some New Brand', 'style_number': 'X1'}) == 'Some New Brand'


def test_infer_brand_falls_back_to_style_prefix_when_unset():
    assert infer_brand({'brand': '', 'style_number': 'BC3001'}) == 'Bella+Canvas'
    assert infer_brand({'brand': '', 'style_number': 'G185'}) == 'Gildan'


def test_shop_card_and_filter_dropdown_agree_on_brand_casing(client, app, seed):
    from models import db, Product
    with app.app_context():
        product = db.session.get(Product, seed['tee_id'])
        product.brand = 'BELLA+CANVAS'
        db.session.commit()

    body = client.get('/shop/').get_data(as_text=True)
    assert 'BELLA+CANVAS' not in body
    assert 'Bella+Canvas' in body


def test_product_detail_and_customize_pages_show_normalized_brand(client, app, seed):
    from models import db, Product
    with app.app_context():
        product = db.session.get(Product, seed['tee_id'])
        product.brand = 'BELLA+CANVAS'
        db.session.commit()

    detail = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    assert 'BELLA+CANVAS' not in detail
    assert 'Bella+Canvas' in detail

    customize = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'BELLA+CANVAS' not in customize


def test_unisex_fit_option_no_longer_says_mens_or_boys(client, seed):
    body = client.get('/shop/').get_data(as_text=True)
    assert "Men's (Unisex)" not in body
    assert 'Boys (Unisex)' not in body
    assert '>Unisex</option>' in body
