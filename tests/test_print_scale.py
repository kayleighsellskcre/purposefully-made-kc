"""Medium / Standard / Oversized print size: dimensions, price, cart and the transfer sheet agree."""
from models import Product, db
from utils import print_scale as PSC
from utils import print_sizes as PS
from utils.pricing import calculate_unit_price, price_cart_item


def test_widths_follow_the_standard_chart(app, seed):
    std = PS.front_transfer_size('M', None, 'center_chest')['width']
    assert std == 10.0
    assert PS.front_transfer_size('M', None, 'center_chest', scale='medium')['width'] == 6.0
    big = PS.front_transfer_size('M', None, 'center_back', scale='oversized')
    assert big['width'] == 13.0 and big['scale'] == 'oversized'
    # medium sits between a chest logo (4 in) and standard
    assert PS.front_transfer_size('M', None, 'left_chest')['width'] < 6.0 < std


def test_a_tall_oversized_print_is_not_flagged_but_a_huge_one_is(app, seed):
    assert PS.front_transfer_size('M', None, 'center_back', 1, 1.3, scale='oversized')['exceeds_safe_area'] is False
    assert PS.front_transfer_size('M', None, 'center_back', 1, 2.5, scale='oversized')['exceeds_safe_area'] is True


def test_chest_logos_ignore_the_scale(app, seed):
    assert PS.front_transfer_size('M', None, 'left_chest', scale='oversized') == PS.front_transfer_size('M', None, 'left_chest')


def test_youth_and_tanks_never_get_oversized(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        assert 'oversized' in PSC.allowed_scales(tee, 'M', 'center_back')
        assert PSC.effective('oversized', tee, 'YM', 'center_back') in ('standard', 'oversized')
    assert PSC.allowed_scales(None, 'YM', 'center_back') == ['medium', 'standard']


def test_prices(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        base = calculate_unit_price(tee, size='M', placement='center_chest')
        assert calculate_unit_price(tee, size='M', placement='center_chest', print_scale='medium') == base - 1
        assert calculate_unit_price(tee, size='M', placement='center_back', print_scale='oversized') == base + 6
        assert calculate_unit_price(tee, size='M', placement='left_chest', print_scale='oversized') == base - 2
        assert price_cart_item({'size': 'M', 'placement': 'center_back', 'print_scale': 'oversized', 'design_id': 1}, tee) == base + 6


def test_the_owner_can_change_the_prices(app, seed):
    with app.app_context():
        PSC.save_adjustments('-0.50', '8')
        assert PSC.adjustments()['oversized'] == 8.0 and PSC.adjustments()['medium'] == -0.5


def test_site_settings_shows_and_saves_print_sizes(app, seed, admin_client):
    page = admin_client.get('/admin/operations/site-settings').get_data(as_text=True)
    assert 'Print sizes' in page and 'Oversized' in page
    admin_client.post('/admin/operations/site-settings', data={'section': 'print_sizes', 'medium_adjust': '-2', 'oversized_adjust': '7.5'})
    with app.app_context():
        assert PSC.adjustments() == {'medium': -2.0, 'standard': 0.0, 'oversized': 7.5}


def test_the_customizer_gets_the_print_size_choices(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        cfg = PS.client_config(tee)['print_scale']
        assert cfg['factors']['oversized'] == 1.3 and cfg['adjust']['oversized'] == 6.0 and cfg['oversized_ok'] is True
        assert PS.client_config(None)['print_scale']['hints']['medium']


def test_adding_to_the_cart_keeps_the_print_size_and_charges_for_it(app, seed, client):
    from tests.test_cart_flow import add_to_cart, cart_items
    with app.app_context():
        base = calculate_unit_price(db.session.get(Product, seed['tee_id']), size='M', placement='center_back')
    add_to_cart(client, seed, placement='center_back', design_id=seed['free_design_id'], print_scale='oversized')
    line = cart_items(client)[0]
    assert line['print_scale'] == 'oversized' and line['unit_price'] == base + 6
    assert line['transfer_production']['front']['print_scale'] == 'oversized'
    assert line['transfer_production']['front']['placement_label'] == 'Center Back · Oversized'
    assert line['transfer_production']['front']['width'] == 13.0           # the transfer sheet shows what to order


def test_a_size_that_does_not_fit_quietly_becomes_standard(app, seed, client):
    from tests.test_cart_flow import add_to_cart, cart_items
    r = add_to_cart(client, seed, product_id=seed['youth_id'], size='YM', placement='center_back', design_id=seed['free_design_id'], print_scale='oversized')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert cart_items(client)[0]['print_scale'] == 'standard'
    add_to_cart(client, seed, product_id=seed['hoodie_id'], placement='center_chest', design_id=seed['free_design_id'], print_scale='oversized')
    assert cart_items(client)[1]['print_scale'] == 'standard'


def test_two_print_sizes_of_the_same_shirt_are_separate_lines(app, seed, client):
    from tests.test_cart_flow import add_to_cart, cart_items
    add_to_cart(client, seed, placement='center_back', design_id=seed['free_design_id'], print_scale='medium')
    add_to_cart(client, seed, placement='center_back', design_id=seed['free_design_id'], print_scale='oversized')
    assert len(cart_items(client)) == 2


def test_the_customizer_page_offers_print_sizes(app, seed, client):
    html = client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'id="scaleGrid"' in html and '"print_scale"' in html


def test_the_cart_and_checkout_say_the_print_size(app, seed, client):
    from tests.test_cart_flow import add_to_cart
    add_to_cart(client, seed, placement='center_back', design_id=seed['free_design_id'], print_scale='oversized')
    assert 'Print: Oversized' in client.get('/cart/').get_data(as_text=True)
    add_to_cart(client, seed, placement='center_back', design_id=seed['free_design_id'], print_scale='standard')
    assert 'Print: Standard' not in client.get('/cart/').get_data(as_text=True)


def test_an_order_line_names_its_print_size(app, seed):
    import json
    from models import OrderItem
    line = OrderItem(transfer_production=json.dumps({'front': {'print_scale': 'oversized'}}))
    assert line.print_scale_label == 'Oversized print'
    assert OrderItem(transfer_production=json.dumps({'front': {'print_scale': 'standard'}})).print_scale_label == ''
    assert OrderItem().print_scale_label == ''


def test_an_oversized_back_picture_costs_more_and_is_ordered_bigger(client, seed):
    from io import BytesIO
    from pathlib import Path
    from tests.test_back_options import _add, _png_bytes
    _add(client, product_id=seed['tee_id'], size='M', color='Black', quantity=1, placement='center_chest',
         design_id=seed['free_design_id'], back_design_scale='oversized', back_design=(BytesIO(_png_bytes()), 'big.png'))
    with client.session_transaction() as sess:
        item = dict(sess['cart'][0])
    try:
        assert item['back_design_meta'] == {'scale': 'oversized'}
        assert item['unit_price'] == 30.00 + 6.00 + 6.00                     # base, the $6 back picture, the $6 oversized price
        assert PS.front_transfer_size('M', None, 'center_back', scale='oversized')['width'] == 13.0
    finally:
        Path(item['back_design_url'].lstrip('/')).unlink(missing_ok=True)


def test_checkout_reprices_an_oversized_back_picture_and_a_youth_one_stays_standard(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        line = {'back_design_url': '/x/b.png', 'back_design_meta': {'scale': 'oversized'}, 'design_id': seed['free_design_id'], 'size': 'M', 'placement': 'center_chest'}
        assert price_cart_item(line, tee) == 42.00
        youth = db.session.get(Product, seed['youth_id'])
        line['size'] = 'YM'
        assert price_cart_item(line, youth) == price_cart_item({**line, 'back_design_meta': {}}, youth)


def test_the_back_options_are_labelled_and_the_picked_one_stays_readable(app, seed, client):
    html = client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'Upper back, under the collar' in html and 'id="backOversizedTab"' in html
    from pathlib import Path
    css = Path('static/css/main.css').read_text(encoding='utf-8')
    assert 'body:not(.is-admin) .back-design-tab.active { color: #fff; }' in css
