"""The cart, checkout and admin redraw the shirt from where the customer placed the art in the customizer."""
import json

from utils import preview_layout as PL
from utils.order_artwork import artwork_kit

LAYOUT = {'front': {'x': 0.31, 'y': 0.22, 'w': 0.38, 'h': 0.2, 'ar': 1.25},
          'back': {'x': 0.28, 'y': 0.18, 'w': 0.44, 'h': 0.52, 'ar': 1.25}}


def test_clean_keeps_good_numbers_and_drops_bad_ones():
    assert PL.clean(json.dumps(LAYOUT)) == LAYOUT
    assert PL.clean({'front': {'x': 'a', 'y': 0, 'w': 0.2, 'h': 0.2, 'ar': 1}}) is None
    assert PL.clean({'front': {'x': 0.1, 'y': 0.1, 'w': 9, 'h': 0.2, 'ar': 1}}) is None       # far too wide
    assert PL.clean('not json') is None and PL.clean(None) is None
    assert PL.clean({'back': LAYOUT['back'], 'other': 1}) == {'back': LAYOUT['back']}


def test_the_cart_draws_the_shirt_from_the_customizer_layout(client, seed):
    resp = client.post('/cart/add', json={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1, 'placement': 'center_chest',
        'design_url': '/static/img/logo.png', 'preview_layout': json.dumps(LAYOUT),
    })
    assert resp.status_code == 200
    with client.session_transaction() as sess:
        line = (sess.get('cart') or [])[0]
    assert line['preview_layout']['front'] == LAYOUT['front']
    page = client.get('/cart/').get_data(as_text=True)
    assert 'pm-proof--exact' in page
    flat = ' '.join(page.split())
    assert 'x="310.0" y="275.0" width="380.0" height="250.0"' in flat          # 0.31, 0.22 x 1250, 0.38, 0.2 x 1250


def test_a_line_without_a_layout_keeps_the_old_drawing(client, seed):
    client.post('/cart/add', json={'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
                                   'placement': 'center_chest', 'design_url': '/static/img/logo.png'})
    page = client.get('/cart/').get_data(as_text=True)
    assert 'pm-proof--exact' not in page and 'pm-proof-overlay' in page


def test_the_admin_kit_carries_the_layout_from_the_order_line():
    class Item:
        product = None
        color = 'Black'
        placement = 'center_chest'
        proof_image = None
        proof_back_image = None
        design_file_name = None
        back_design_file_name = None
        back_design_details = {}
        preview_layout = json.dumps(LAYOUT)

    import utils.order_artwork as OA
    real_mockups, real_front, real_back = OA.mockup_urls, OA.front_print_url, OA.back_print_url
    OA.mockup_urls = lambda p, c: ('/static/img/front.png', '/static/img/back.png')
    OA.front_print_url = lambda item: '/static/img/art.png'
    OA.back_print_url = lambda item: None
    try:
        kit = artwork_kit(Item())
    finally:
        OA.mockup_urls, OA.front_print_url, OA.back_print_url = real_mockups, real_front, real_back
    assert kit['front_layout'] == LAYOUT['front'] and kit['layout_front_art'] == '/static/img/art.png'
    assert kit['back_layout'] is None                    # no back print, so nothing to place
