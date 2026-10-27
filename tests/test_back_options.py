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
