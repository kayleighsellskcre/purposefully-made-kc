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
