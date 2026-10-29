"""Edit a cart line, and the stacked name shows on the back picture in the cart."""
import re

import pytest


def _line(seed, **extra):
    return {'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'placement': 'center_chest', 'quantity': 1,
            'design_url': '/static/img/logo.png', **extra}


def test_every_cart_line_has_an_edit_link_to_its_own_product(app, seed, guest):
    assert guest.post('/cart/add', json=_line(seed)).status_code == 200
    html = guest.get('/cart/').get_data(as_text=True)
    assert re.search(r'href="/shop/customize/[^"?]+\?edit=0"', html) and 'cart-edit-link' in html


def test_the_customizer_opens_with_the_line_filled_in(app, seed, guest):
    guest.post('/cart/add', json=_line(seed, size='L', quantity=3, color='White'))
    page = guest.get(f'/shop/customize/{seed["tee_slug"]}?edit=0').get_data(as_text=True)
    assert 'Update Item' in page and 'You are changing an item from your cart' in page
    assert re.search(r'const EDIT_LINE = \{[^;]*"color": "White"[^;]*"size": "L"', page.replace('\n', ' '))
    plain = guest.get(f'/shop/customize/{seed["tee_slug"]}').get_data(as_text=True)
    assert 'const EDIT_LINE = null' in plain and 'Update Item' not in plain.split('const ADD_LABEL')[0]
    other = guest.get(f'/shop/customize/{seed["tee_slug"]}?edit=9').get_data(as_text=True)      # no such line: an ordinary page
    assert 'const EDIT_LINE = null' in other
    hoodie = guest.get(f'/shop/customize/{seed["hoodie_slug"]}?edit=0').get_data(as_text=True)  # a different product's line is not opened
    assert 'const EDIT_LINE = null' in hoodie


def test_an_edited_line_replaces_the_old_one_instead_of_adding_another(app, seed, guest):
    guest.post('/cart/add', json=_line(seed, size='M', quantity=2))
    guest.post('/cart/add', json=_line(seed, size='XL', quantity=1))
    resp = guest.post('/cart/add', json=_line(seed, size='L', quantity=4, replace_index=0))
    assert resp.status_code == 200
    html = guest.get('/cart/').get_data(as_text=True)
    assert html.count('class="cart-item"') == 2                                   # still two lines, not three
    assert 'Size: L' in html and 'Size: XL' in html and 'Size: M' not in html     # the first line became L, quantity 4
    assert re.search(r'cartQty0"\s+value="4"', html)


def test_a_bad_edit_number_just_adds_a_line(app, seed, guest):
    guest.post('/cart/add', json=_line(seed))
    assert guest.post('/cart/add', json=_line(seed, size='XL', replace_index=7)).status_code == 200
    assert guest.get('/cart/').get_data(as_text=True).count('class="cart-item"') == 2
    assert guest.post('/cart/add', json=_line(seed, replace_index='x')).status_code == 400


def test_a_stacked_name_under_a_small_image_shows_on_the_cart_back_picture(app, seed, guest):
    resp = guest.post('/cart/add', json=_line(seed, back_design_url='/static/img/logo.png', back_design_name='ELENA',
                                               back_design_vertical='true', back_design_combo='true', back_design_position='upper',
                                               back_design_font='Bebas Neue', back_design_text_color='#ffffff',
                                               back_design_outline='true', back_design_outline_color='#000000'))
    assert resp.status_code == 200
    html = guest.get('/cart/').get_data(as_text=True)
    assert 'combo_back' in html and 'back_preview' in html and re.search(r'Back:\s*ELENA', html)


def test_an_older_line_gets_its_back_picture_the_first_time_the_cart_is_shown(app, seed, guest):
    guest.post('/cart/add', json=_line(seed, back_design_url='/static/img/logo.png', back_design_name='ELENA', back_design_vertical='true',
                                       back_design_combo='true', back_design_position='upper', back_design_font='Bebas Neue',
                                       back_design_text_color='#ffffff', back_design_outline='true', back_design_outline_color='#000000'))
    with guest.session_transaction() as sess:                      # as if it was added before the picture was made
        for line in sess['cart']:
            line.pop('back_preview_url', None)
            line.pop('back_preview_style', None)
    html = guest.get('/cart/').get_data(as_text=True)
    assert 'combo_back' in html and 'back_preview' in html


def test_the_winner_page_steps_never_grow_past_their_column():
    css = open('static/css/main.css', encoding='utf-8').read()
    assert '.gift-steps { grid-template-columns: minmax(0, 1fr); }' in css          # a long carousel scrolls inside its card
    assert '.gift-steps > .gift-card, .gift-rail-wrap { min-width: 0; max-width: 100%; }' in css
