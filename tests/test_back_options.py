"""Two back options: a small image under the collar, and a name stacked down the back for cheer."""
import io
from io import BytesIO
from pathlib import Path

from PIL import Image

from models import Product, db
from utils import personalization_layout as PL
from utils import print_sizes as PS
from utils.back_logo_size import back_logo_placement
from utils.pricing import SINGLE_BACK_DESIGN_FEE, price_cart_item


def _png_bytes():
    out = io.BytesIO()
    Image.new('RGBA', (300, 200), '#cc0000').save(out, format='PNG')
    return out.getvalue()


def _add(client, **fields):
    return client.post('/cart/add', data=fields)


def test_a_small_upper_back_image_costs_the_same_as_one_name_or_number(client, seed):
    _add(client, product_id=seed['tee_id'], size='M', color='Black', quantity=1, placement='center_chest',
         design_id=seed['free_design_id'], back_design_position='upper', back_design=(BytesIO(_png_bytes()), 'neck.png'))
    with client.session_transaction() as sess:
        item = dict(sess['cart'][0])
    try:
        assert item['unit_price'] == 30.00 + SINGLE_BACK_DESIGN_FEE
        assert item['back_design_kind'] == 'image' and item['back_design_meta'] == {'position': 'upper'}
    finally:
        Path(item['back_design_url'].lstrip('/')).unlink(missing_ok=True)


def test_checkout_reprices_an_upper_back_image_at_the_single_fee(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        line = {'back_design_url': '/x/neck.png', 'back_design_meta': {'position': 'upper'}, 'design_id': seed['free_design_id'],
                'size': 'M', 'placement': 'center_chest'}
        assert price_cart_item(line, tee) == 33.00
        line['back_design_meta'] = {}
        assert price_cart_item(line, tee) == 36.00                           # the full back image stays $6


def test_the_upper_back_image_is_ordered_at_the_left_chest_width_and_labelled(app):
    assert PS.placement_label('upper_back') == 'Upper Back'
    assert PS.front_transfer_size('M', None, 'upper_back')['width'] == PS.front_transfer_size('M', None, 'left_chest')['width']
    assert PS.front_transfer_size('M', None, 'upper_back')['width'] < PS.front_transfer_size('M', None, 'center_back')['width']

    class Item:
        back_design_details = {'position': 'upper'}
    assert back_logo_placement(Item()) == 'upper_back'
    Item.back_design_details = {}
    assert back_logo_placement(Item()) == 'center_back'


def test_a_stacked_name_is_a_name_only_priced_as_one_line(client, seed):
    _add(client, product_id=seed['tee_id'], size='M', color='Black', quantity=1, placement='center_chest',
         design_id=seed['free_design_id'], back_design_name='Smith', back_design_number='12', back_design_vertical='true',
         back_design=(BytesIO(_png_bytes()), 'name.png'))
    with client.session_transaction() as sess:
        item = dict(sess['cart'][0])
    try:
        assert item['unit_price'] == 33.00                                    # the number is dropped: a name, not both
        assert item['back_design_meta']['vertical'] is True and item['back_design_meta']['number'] == ''
        back = item['transfer_production']['back']
        assert back['vertical'] is True and back['number'] == ''
    finally:
        Path(item['back_design_url'].lstrip('/')).unlink(missing_ok=True)


def test_a_stacked_name_stays_on_the_upper_back_whatever_its_length():
    for size in ('S', 'M', 'XL', 'YM'):
        for name in ('JO', 'KAYLEIGH', 'ABCDEFGHIJKL', 'ABCDEFGHIJKLMNOP'):
            letter, gap, count = PS.vertical_name_layout(size, None, name)
            total = count * letter + (count - 1) * gap
            assert count == min(len(name), PS.VERTICAL_MAX_LETTERS)
            assert total <= PS.safe_print_height(None, size) * PS.VERTICAL_RUN_RATIO + 0.01
            assert letter >= PS.VERTICAL_MIN_LETTER_IN - 0.001
    assert PS.vertical_letters('Mae Lynn') == list('MAELYNN')                   # spaces are dropped


def test_the_stacked_name_is_rendered_one_centered_letter_per_row(app):
    snapshot = PS.build_item_production(size='M', back_name='Mia', back_number='9', back_font='Bebas Neue',
                                        back_text_color='#ffffff', back_outline=True, back_outline_color='#000000',
                                        back_vertical=True)['back']
    assert snapshot['vertical'] and snapshot['number'] == '' and snapshot['combined_height'] > snapshot['name_height'] * 2
    snapshot = dict(snapshot, complete=True)
    data = PL.render_snapshot_png(snapshot, dpi=100)
    image = Image.open(io.BytesIO(data)).convert('RGBA')
    assert abs(image.height / 100 - snapshot['combined_height']) < snapshot['combined_height'] * 0.08
    band = image.height / 3
    centers = []
    for i in range(3):                                                         # M, I, A: each letter's ink centred on the page
        box = image.crop((0, int(i * band), image.width, int((i + 1) * band))).getchannel('A').getbbox()
        assert box
        centers.append((box[0] + box[2]) / 2)
    assert all(abs(c - image.width / 2) < image.width * 0.06 for c in centers)
    assert PL.validate_snapshot_png(snapshot, data, dpi=100)[0]


def _group_with_back_images(app, seed, kind):
    from models import Collection, Design
    from utils import group_designs as GD
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allow_back_design, coll.back_design_type, coll.restrict_options = True, kind, True
        extra = Design(filename='b2.png', file_path='uploads/designs/b2.png', title='Back two', is_gallery=True)
        db.session.add(extra)
        db.session.flush()
        GD.set_back_ids(coll, [seed['free_design_id'], extra.id])
        db.session.commit()
        return coll.slug


def test_a_group_that_offers_either_option_shows_its_own_back_images(app, seed):
    slug = _group_with_back_images(app, seed, 'both')
    shopper = app.test_client()
    shopper.get(f'/c/{slug}')
    html = shopper.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'id="backPicker"' in html and html.count('class="back-pick') >= 2
    assert 'id="uploadAreaBack" hidden' in html                         # the group's images, not an upload box of their own
    assert 'id="backStackWrap"' in html and 'id="backStackAddImage"' in html     # a stacked name can ride along with the small image


def test_placement_sits_with_the_logo_choice_before_the_back_options(app, seed):
    shopper = app.test_client()
    html = shopper.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 0 < html.index('id="placementSection"') < html.index('id="backDesignSection"')
    assert html.index('Choose Logo or Design') < html.index('id="placementSection"')


def test_a_tapped_logo_opens_its_colors_as_a_card_on_a_phone(app, seed):
    shopper = app.test_client()
    html = shopper.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'isPhoneColorSheet' in html and 'logo-color-close' in html
    css = Path('static/css/main.css').read_text(encoding='utf-8')
    assert '.logo-color-chooser:not([hidden]) { position: fixed' in css


def test_a_stacked_name_can_carry_a_small_image_under_the_collar_for_six_dollars(client, seed):
    _add(client, product_id=seed['tee_id'], size='M', color='Black', quantity=1, placement='center_chest',
         design_id=seed['free_design_id'], back_design_name='Mia', back_design_vertical='true', back_design_combo='true',
         back_design_position='upper', back_design=(BytesIO(_png_bytes()), 'neck.png'))
    with client.session_transaction() as sess:
        item = dict(sess['cart'][0])
    try:
        assert item['unit_price'] == 36.00                                   # $3 for the name + $3 for the image
        meta = item['back_design_meta']
        assert meta['vertical'] is True and meta['neck_image_url'] == item['back_design_url'] and meta['neck_aspect'] == 1.5
        back = item['transfer_production']['back']
        assert back['neck_image_url'] and abs(back['neck_width'] - 4.0) < 0.01
        stack = 3 * back['name_height'] + 2 * back['gap']
        assert abs(back['combined_height'] - (stack + back['neck_height'] + back['neck_gap'])) < 0.01
    finally:
        Path(item['back_design_url'].lstrip('/')).unlink(missing_ok=True)


def test_the_name_and_image_transfer_has_the_image_on_top_and_the_letters_centered_below(app):
    with app.app_context():
        aspect = PL.art_aspect('/static/img/logo.png')
        assert aspect
        snapshot = PS.build_item_production(size='M', back_name='Mia', back_font='Bebas Neue', back_text_color='#ffffff',
                                            back_outline=True, back_outline_color='#000000', back_vertical=True,
                                            back_neck_image_url='/static/img/logo.png', back_neck_aspect=aspect)['back']
        snapshot = dict(snapshot, complete=True)
        data = PL.render_snapshot_png(snapshot, dpi=100)
    image = Image.open(io.BytesIO(data)).convert('RGBA')
    assert abs(image.height / 100 - snapshot['combined_height']) < snapshot['combined_height'] * 0.08
    neck_px = int(snapshot['neck_height'] * 100)
    top = image.crop((0, 0, image.width, neck_px)).getchannel('A').getbbox()
    below = image.crop((0, neck_px + int(snapshot['neck_gap'] * 100), image.width, image.height)).getchannel('A').getbbox()
    assert top and below and top[3] <= neck_px + 2                              # the picture sits above the gap
    assert abs((below[0] + below[2]) / 2 - image.width / 2) < image.width * 0.06  # the letters are centered under it


def test_checkout_reprices_the_name_and_image_at_six_dollars(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        line = {'back_design_url': '/x/neck.png', 'design_id': seed['free_design_id'], 'size': 'M', 'placement': 'center_chest',
                'back_design_meta': {'name': 'MIA', 'vertical': True, 'neck_image_url': '/x/neck.png'}}
        assert price_cart_item(line, tee) == 36.00
        line['back_design_meta'] = {'name': 'MIA', 'vertical': True}
        assert price_cart_item(line, tee) == 33.00
