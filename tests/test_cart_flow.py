"""The cart, end to end: add, edit, change quantity, remove, and persistence.

The cart lives in the session and there is no JSON endpoint that reports it, so
these read `session['cart']` directly and check the rendered page for anything
the shopper is meant to see.
"""
import pytest


def add_to_cart(client, seed, **over):
    payload = {
        'product_id': seed['tee_id'],
        'size': 'M',
        'color': 'Black',
        'quantity': 1,
        'placement': 'center_chest',
    }
    payload.update(over)
    return client.post('/cart/add', json=payload)


def cart_items(client):
    with client.session_transaction() as sess:
        return list(sess.get('cart') or [])


def subtotal(client):
    return round(sum(i['unit_price'] * i['quantity'] for i in cart_items(client)), 2)


# ── Adding ───────────────────────────────────────────────────────────────────

def test_adding_an_item_succeeds(client, seed):
    resp = add_to_cart(client, seed)
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_an_added_item_keeps_the_options_that_were_chosen(client, seed):
    add_to_cart(client, seed, size='L', color='White', quantity=2,
                placement='left_chest')
    items = cart_items(client)
    assert len(items) == 1
    item = items[0]
    assert item['size'] == 'L'
    assert item['color'] == 'White'
    assert item['quantity'] == 2
    assert item['placement'] == 'left_chest'


def test_the_cart_page_shows_the_item(client, seed):
    add_to_cart(client, seed)
    body = client.get('/cart/').get_data(as_text=True)
    assert 'Unisex Jersey Short Sleeve Tee' in body


def test_the_add_response_reports_the_new_count(client, seed):
    add_to_cart(client, seed, quantity=2)
    resp = add_to_cart(client, seed, size='L', quantity=3)
    assert resp.get_json()['cart_count'] == 5


def test_adding_an_unknown_product_is_refused(client, seed):
    resp = add_to_cart(client, seed, product_id=999999)
    assert resp.status_code == 404
    assert cart_items(client) == []


def test_a_size_is_required(client, seed):
    resp = add_to_cart(client, seed, size='')
    assert resp.status_code == 400
    assert cart_items(client) == []


def test_a_colour_is_required(client, seed):
    resp = add_to_cart(client, seed, color='')
    assert resp.status_code == 400
    assert cart_items(client) == []


def test_more_than_the_stock_on_hand_is_refused(client, seed):
    resp = add_to_cart(client, seed, quantity=10_000)
    assert resp.status_code == 400
    assert cart_items(client) == []


# ── Distinct options stay distinct ───────────────────────────────────────────

def test_two_sizes_of_the_same_shirt_are_separate_lines(client, seed):
    add_to_cart(client, seed, size='M')
    add_to_cart(client, seed, size='L')
    assert len(cart_items(client)) == 2


def test_two_colours_of_the_same_shirt_are_separate_lines(client, seed):
    add_to_cart(client, seed, color='Black')
    add_to_cart(client, seed, color='White')
    assert len(cart_items(client)) == 2


def test_two_placements_are_separate_lines(client, seed):
    add_to_cart(client, seed, placement='center_chest')
    add_to_cart(client, seed, placement='left_chest')
    assert len(cart_items(client)) == 2


def test_adding_the_identical_item_twice_raises_the_quantity(client, seed):
    add_to_cart(client, seed, quantity=1)
    add_to_cart(client, seed, quantity=2)
    items = cart_items(client)
    assert len(items) == 1
    assert items[0]['quantity'] == 3


def test_two_different_products_both_stay_in_the_cart(client, seed):
    add_to_cart(client, seed, product_id=seed['tee_id'])
    add_to_cart(client, seed, product_id=seed['hoodie_id'], color='Black')
    assert len(cart_items(client)) == 2
    assert {i['product_id'] for i in cart_items(client)} == {
        seed['tee_id'], seed['hoodie_id']
    }


def test_a_design_stays_attached_to_its_own_line(customer_client, seed):
    add_to_cart(customer_client, seed, design_id=seed['free_design_id'])
    add_to_cart(customer_client, seed, design_id=seed['fee_4_design_id'])
    items = cart_items(customer_client)
    assert len(items) == 2
    assert {str(i['design_id']) for i in items} == {
        str(seed['free_design_id']), str(seed['fee_4_design_id'])
    }


def test_a_design_carries_its_fee_onto_the_line(customer_client, seed):
    add_to_cart(customer_client, seed, design_id=seed['fee_20_design_id'])
    item = cart_items(customer_client)[0]
    # $30 tee + $20 from-scratch design fee
    assert item['unit_price'] == pytest.approx(50.00)


def test_a_shopper_cannot_attach_another_customers_private_design(guest, seed):
    """A private design belongs to one customer; a guest must not price it in."""
    add_to_cart(guest, seed, design_id=seed['fee_20_design_id'])
    item = cart_items(guest)[0]
    assert item['design_id'] is None
    # Rejecting the design leaves a blank garment: $30 tee less the $12 blank
    # discount. The $20 recreation fee must not appear.
    assert item['unit_price'] == pytest.approx(18.00), 'a private design fee leaked'


# ── Editing ──────────────────────────────────────────────────────────────────

def test_changing_the_quantity_updates_the_line(client, seed):
    add_to_cart(client, seed)
    resp = client.post('/cart/update/0', json={'quantity': 4})
    assert resp.status_code == 200
    assert cart_items(client)[0]['quantity'] == 4


def test_changing_the_quantity_updates_the_total(client, seed):
    add_to_cart(client, seed)
    one = subtotal(client)
    client.post('/cart/update/0', json={'quantity': 3})
    assert subtotal(client) == pytest.approx(one * 3)


def test_a_quantity_below_one_is_refused(client, seed):
    add_to_cart(client, seed, quantity=2)
    resp = client.post('/cart/update/0', json={'quantity': 0})
    assert resp.status_code == 400
    assert cart_items(client)[0]['quantity'] == 2


def test_a_quantity_beyond_stock_is_refused(client, seed):
    add_to_cart(client, seed)
    resp = client.post('/cart/update/0', json={'quantity': 10_000})
    assert resp.status_code == 400
    assert cart_items(client)[0]['quantity'] == 1


def test_updating_a_line_that_is_not_there_is_a_404(client, seed):
    add_to_cart(client, seed)
    resp = client.post('/cart/update/99', json={'quantity': 2})
    assert resp.status_code == 404
    assert len(cart_items(client)) == 1


def test_removing_a_line_leaves_the_others_alone(client, seed):
    add_to_cart(client, seed, size='M')
    add_to_cart(client, seed, size='L')
    client.post('/cart/remove/0')
    items = cart_items(client)
    assert len(items) == 1
    assert items[0]['size'] == 'L'


def test_removing_a_line_that_is_not_there_is_a_404(client, seed):
    add_to_cart(client, seed)
    assert client.post('/cart/remove/99').status_code == 404
    assert len(cart_items(client)) == 1


def test_clearing_the_cart_empties_it(client, seed):
    add_to_cart(client, seed)
    add_to_cart(client, seed, size='L')
    client.post('/cart/clear')
    assert cart_items(client) == []


# ── Totals ───────────────────────────────────────────────────────────────────

def test_the_cart_page_total_matches_the_lines(client, seed):
    design = seed['free_design_id']
    add_to_cart(client, seed, product_id=seed['tee_id'], quantity=2,
                design_id=design)
    add_to_cart(client, seed, product_id=seed['hoodie_id'], color='Black',
                design_id=design)
    expected = subtotal(client)   # 2 x $30 + $45
    assert expected == pytest.approx(105.00)
    assert f'{expected:.2f}' in client.get('/cart/').get_data(as_text=True)


def test_a_garment_with_no_artwork_gets_the_blank_discount(client, seed):
    add_to_cart(client, seed)
    assert cart_items(client)[0]['is_blank'] is True
    assert cart_items(client)[0]['unit_price'] == pytest.approx(18.00)


def test_an_extended_size_surcharge_reaches_the_cart(client, seed):
    add_to_cart(client, seed, size='2XL', design_id=seed['free_design_id'])
    assert cart_items(client)[0]['unit_price'] == pytest.approx(32.00)


def test_a_youth_extended_size_carries_no_surcharge(client, seed):
    add_to_cart(client, seed, product_id=seed['youth_id'], size='2XL',
                color='Black', design_id=seed['free_design_id'])
    assert cart_items(client)[0]['unit_price'] == pytest.approx(24.00)


def test_a_small_chest_logo_is_two_dollars_less(client, seed):
    add_to_cart(client, seed, placement='left_chest',
                design_id=seed['free_design_id'])
    assert cart_items(client)[0]['unit_price'] == pytest.approx(28.00)


def test_the_empty_cart_page_says_so_rather_than_erroring(client):
    resp = client.get('/cart/')
    assert resp.status_code == 200
    assert 'empty' in resp.get_data(as_text=True).lower()


# ── Persistence and isolation ────────────────────────────────────────────────

def test_the_cart_survives_moving_between_pages(client, seed):
    add_to_cart(client, seed)
    client.get('/')
    client.get('/shop/')
    client.get(f'/shop/product/{seed["tee_id"]}')
    assert len(cart_items(client)) == 1


def test_one_shoppers_cart_is_invisible_to_another(app, seed):
    first = app.test_client()
    add_to_cart(first, seed)
    second = app.test_client()
    assert cart_items(second) == []


def test_signing_in_as_someone_else_does_not_inherit_their_cart(client, seed, login):
    """get_cart() clears the basket when the owner changes, on purpose."""
    from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL

    login(client, CUSTOMER_EMAIL)
    add_to_cart(client, seed)
    assert len(cart_items(client)) == 1

    client.get('/auth/logout')
    login(client, OTHER_EMAIL)
    assert cart_items(client) == [], 'a cart followed a different account'


# ── Checkout entry ───────────────────────────────────────────────────────────

def test_checkout_with_an_empty_cart_sends_you_back(client):
    resp = client.get('/checkout/', follow_redirects=False)
    assert resp.status_code == 302
    assert '/cart' in resp.headers['Location']


def test_checkout_opens_with_something_in_the_cart(client, seed):
    add_to_cart(client, seed)
    assert client.get('/checkout/').status_code == 200
