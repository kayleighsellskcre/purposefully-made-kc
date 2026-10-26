"""Gift option at checkout: a message for a small card, and a packing slip that can leave the prices off."""
from models import Order, OrderItem, db
from routes.checkout import gift_fields
from tests.conftest import ADMIN_EMAIL
from tests.test_checkout import _cash_payload, _fill_cart


def _order(client, seed, app, **extra):
    _fill_cart(client, seed, app=app, allow_cash=True)
    payload = _cash_payload()
    payload.update(extra)
    body = client.post('/checkout/complete', json=payload).get_json()
    assert body.get('order_number'), body
    return body['order_number']


def _row(app, number):
    with app.app_context():
        o = Order.query.filter_by(order_number=number).first()
        return o.id, o.is_gift, o.gift_message, o.gift_hide_prices


def test_the_checkout_form_offers_a_gift_with_a_message_and_a_prices_choice(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    resp = client.get('/checkout/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="is_gift"' in html and 'id="gift_message"' in html and 'maxlength="250"' in html
    assert 'Leave prices off the packing slip' in html and 'id="giftFields" hidden' in html


def test_a_gift_keeps_its_message_and_asks_to_hide_prices_by_default(client, seed, app):
    number = _order(client, seed, app, is_gift=True, gift_message='Happy birthday!  We love you.')
    _id, is_gift, message, hide = _row(app, number)
    assert (is_gift, message, hide) == (True, 'Happy birthday! We love you.', True)


def test_the_customer_can_untick_hide_prices(client, seed, app):
    number = _order(client, seed, app, is_gift=True, gift_message='Enjoy', gift_hide_prices=False)
    assert _row(app, number)[1:] == (True, 'Enjoy', False)


def test_an_ordinary_order_is_not_a_gift_even_if_a_message_is_sent(client, seed, app):
    number = _order(client, seed, app, is_gift=False, gift_message='ignored', gift_hide_prices=True)
    assert _row(app, number)[1:] == (False, None, False)


def test_the_message_is_cut_to_250_characters(client, seed, app):
    number = _order(client, seed, app, is_gift=True, gift_message='x' * 400)
    assert len(_row(app, number)[2]) == 250


def test_gift_fields_reads_the_form_the_same_way_for_every_payment_path():
    assert gift_fields({}) == {'is_gift': False, 'gift_message': None, 'gift_hide_prices': False}
    assert gift_fields({'is_gift': 'true', 'gift_message': ' Hi\n there '}) == \
        {'is_gift': True, 'gift_message': 'Hi there', 'gift_hide_prices': True}
    assert gift_fields({'is_gift': True, 'gift_hide_prices': 'false'})['gift_hide_prices'] is False
    assert gift_fields({'is_gift': 'on', 'gift_message': ''})['gift_message'] is None


def test_the_confirmation_page_shows_the_gift(client, seed, app):
    number = _order(client, seed, app, is_gift=True, gift_message='Congrats, graduate!')
    html = client.get(f'/checkout/confirmation/{number}').get_data(as_text=True)
    assert 'Gift:' in html and 'Congrats, graduate!' in html and 'prices left off the packing slip' in html


def test_the_owner_sees_the_gift_and_the_print_links_on_the_order(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='For Grandma')
    oid = _row(app, number)[0]
    login(client, ADMIN_EMAIL)
    html = client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert 'For Grandma' in html and 'Leave prices off the slip' in html
    assert f'/admin/orders/{oid}/gift-card' in html and f'/admin/orders/{oid}/packing-slip' in html and 'Packing slip (no prices)' in html


def test_an_ordinary_order_has_a_packing_slip_link_but_no_gift_card(client, seed, app, login):
    number = _order(client, seed, app)
    oid = _row(app, number)[0]
    login(client, ADMIN_EMAIL)
    html = client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert f'/admin/orders/{oid}/packing-slip' in html and 'gift-card' not in html
    assert client.get(f'/admin/orders/{oid}/gift-card').status_code == 404


def test_the_gift_packing_slip_has_no_prices_but_the_items_and_who_it_is_for(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='For Grandma')
    oid = _row(app, number)[0]
    with app.app_context():
        item = Order.query.get(oid).items.first()
        price = f'{item.subtotal:.2f}'
    login(client, ADMIN_EMAIL)
    html = client.get(f'/admin/orders/{oid}/packing-slip').get_data(as_text=True)
    assert 'Packing slip' in html and number in html and 'A gift, made with care' in html
    assert item.product_name in html and 'Size M' in html
    assert f'${price}' not in html and '>Price<' not in html and 'Subtotal' not in html and '$' not in html


def test_a_slip_for_an_ordinary_order_keeps_its_prices(client, seed, app, login):
    number = _order(client, seed, app)
    oid = _row(app, number)[0]
    login(client, ADMIN_EMAIL)
    html = client.get(f'/admin/orders/{oid}/packing-slip').get_data(as_text=True)
    assert '>Price<' in html and 'Subtotal' in html


def test_a_gift_that_did_not_ask_to_hide_prices_shows_them(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='Hi', gift_hide_prices=False)
    oid = _row(app, number)[0]
    login(client, ADMIN_EMAIL)
    assert '>Price<' in client.get(f'/admin/orders/{oid}/packing-slip').get_data(as_text=True)


def test_the_gift_card_is_a_small_print_page_with_the_message(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='Happy birthday, Sam!')
    oid = _row(app, number)[0]
    login(client, ADMIN_EMAIL)
    html = client.get(f'/admin/orders/{oid}/gift-card').get_data(as_text=True)
    assert 'Happy birthday, Sam!' in html and 'size: 5.5in 4.25in' in html and 'window.print()' in html
    assert '$' not in html                                                 # a card never shows a price


def test_a_gift_without_a_message_gets_a_kind_default_on_the_card(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='')
    oid = _row(app, number)[0]
    login(client, ADMIN_EMAIL)
    assert 'Made with love, just for you.' in client.get(f'/admin/orders/{oid}/gift-card').get_data(as_text=True)


def test_the_gift_pages_are_closed_to_everyone_but_the_owner(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='Secret')
    oid = _row(app, number)[0]
    guest = app.test_client()
    for path in (f'/admin/orders/{oid}/gift-card', f'/admin/orders/{oid}/packing-slip'):
        assert guest.get(path).status_code in (302, 401, 403, 404)


def test_a_message_with_markup_is_shown_as_plain_text(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='<script>alert(1)</script>')
    oid = _row(app, number)[0]
    login(client, ADMIN_EMAIL)
    for path in (f'/admin/orders/{oid}/gift-card', f'/admin/orders/{oid}', f'/checkout/confirmation/{number}'):
        assert '<script>alert(1)</script>' not in client.get(path).get_data(as_text=True)


def test_the_label_for_a_gift_reminds_the_packer_to_add_the_card(client, seed, app, login):
    number = _order(client, seed, app, is_gift=True, gift_message='Hi')
    login(client, ADMIN_EMAIL)
    html = client.get('/admin/orders/print-labels?stage=order_received').get_data(as_text=True)
    assert number in html and 'GIFT: add the card' in html
