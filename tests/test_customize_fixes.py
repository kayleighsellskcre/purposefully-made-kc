"""Customizer bugs: missing sizes, cart add on mockup-only colours, fonts, gallery."""
import json

from models import db, Product, ProductColorVariant
from utils.fonts import CUSTOMIZE_BACK_FONTS, GROUP_ORDER_FONTS
from utils.mockups import get_carousel_colors_for_product
from utils.personalization_layout import font_path
from utils.sizes import DEFAULT_ADULT_SIZES, shop_sizes_for_product
from utils.stock import available_qty, check_stock


def test_shop_sizes_fall_back_to_inventory_keys():
    product = Product(available_sizes='[]', age_group='adult')
    variants = [ProductColorVariant(color_name='Asphalt', size_inventory=json.dumps({'S': 0, 'M': 0, 'XL': 0}))]
    assert shop_sizes_for_product(product, variants) == ['S', 'M', 'XL']


def test_shop_sizes_use_adult_defaults_when_nothing_is_listed():
    product = Product(available_sizes=None, age_group='adult')
    assert shop_sizes_for_product(product, []) == DEFAULT_ADULT_SIZES


def test_customize_still_renders_size_cards_when_the_product_lists_none(client, app, seed):
    with app.app_context():
        product = Product.query.get(seed['tee_id'])
        product.available_sizes = '[]'
        db.session.commit()
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'size-card' in html
    assert 'data-size="M"' in html
    assert "aren't listed yet" not in html


def test_a_colour_without_a_warehouse_row_is_not_treated_as_out_of_stock(app, seed):
    with app.app_context():
        product = Product.query.get(seed['tee_id'])
        assert available_qty(product, 'Asphalt', 'M') is None
        ok, err, _ = check_stock(product, 'Asphalt', 'M', 1, cart=[])
        assert ok is True
        assert err is None


def test_adding_a_mockup_only_colour_succeeds(client, seed):
    resp = client.post('/cart/add', json={
        'product_id': seed['tee_id'],
        'size': 'M',
        'color': 'Asphalt',
        'quantity': 1,
        'placement': 'center_chest',
    })
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_shop_card_counts_colours_that_have_no_photo(app, seed):
    with app.app_context():
        product = Product.query.get(seed['hoodie_id'])
        colors = get_carousel_colors_for_product(product, app)
        names = {c['color_name'] for c in colors}
        assert 'Black' in names
        assert 'Sport Grey' in names
        assert len(colors) >= 2


def test_customize_page_includes_varsity_regular_and_a_gallery_dropdown(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'Varsity Regular' in html
    assert 'galleryDesignSelect' in html
    assert 'html2canvas' not in html
    assert '+$6.00' in html
    assert 'back-design-fee-amount' in html
    assert '$6.0"' not in html


def test_varsity_regular_font_file_is_present():
    assert font_path('Varsity Regular') is not None


def test_group_order_font_list_includes_varsity_regular():
    values = [value for value, _label in GROUP_ORDER_FONTS]
    assert 'Varsity Regular' in values
    assert 'Varsity Regular' in [value for value, _label in CUSTOMIZE_BACK_FONTS]


def test_group_order_create_form_offers_varsity_regular(customer_client):
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'Varsity Regular' in html
