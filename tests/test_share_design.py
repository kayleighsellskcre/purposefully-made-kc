"""Share a design: one link and QR code that opens exactly what a customer made, and counts what it sells."""
from datetime import datetime

from models import Order, OrderItem, SharedDesign, User, db
from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL, PASSWORD
from tests.test_save_for_later import _cart, _line, _set_cart, _signed_in


def _share(shopper, index=0):
    return shopper.post(f'/made/share/cart/{index}', headers={'Accept': 'application/json'})


def _token(resp):
    return resp.get_json()['url'].rsplit('/made/', 1)[1]


def test_sharing_a_cart_item_gives_a_link_and_qr_without_anything_personal(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    resp = _share(shopper)
    data = resp.get_json()
    assert resp.status_code == 200 and data['success'] and '/made/' in data['url'] and data['qr'].endswith('/qr.png')
    with app.app_context():
        share = SharedDesign.query.one()
        assert share.line['design_id'] == seed['free_design_id'] and share.line['color'] == 'Black'
        assert 'size' not in share.line and share.line['quantity'] == 1
        assert not share.line.get('back_design_meta')              # the name and number stay with the person who made it
        assert (share.line.get('transfer_production') or {}).get('back') is None
    assert _share(shopper).get_json()['url'] == data['url']        # sharing the same thing twice reuses the link
    qr = shopper.get(data['qr'])
    assert qr.status_code == 200 and qr.data[:4] == b'\x89PNG'


def test_group_store_items_and_items_without_artwork_cannot_be_shared(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed, collection_id=seed['collection_id']),
                                    _line(seed, design_id=None, design_url=None)])
    shopper = _signed_in(app)
    for index in (0, 1):
        resp = _share(shopper, index)
        assert resp.status_code == 400 and not resp.get_json()['success']
    with app.app_context():
        assert SharedDesign.query.count() == 0


def test_anyone_with_the_link_picks_a_size_and_adds_it_to_their_cart(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    token = _token(_share(_signed_in(app)))
    friend = app.test_client()
    page = friend.get(f'/made/{token}')
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and 'Designed by a Purposefully Made KC customer' in html and 'name="size"' in html
    assert 'SMITH' not in html
    resp = friend.post(f'/made/{token}/add', data={'size': 'L', 'quantity': 2}, follow_redirects=False)
    assert resp.status_code == 302 and '/cart' in resp.headers['Location']
    with friend.session_transaction() as sess:
        line = sess['cart'][0]
    assert line['size'] == 'L' and line['quantity'] == 2 and line['design_id'] == seed['free_design_id']
    assert line['shared_design_id'] and line['unit_price'] > 0
    with app.app_context():
        assert SharedDesign.query.one().views == 1


def test_turning_a_link_off_stops_it_working(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    token = _token(_share(shopper))
    with app.app_context():
        share_id = SharedDesign.query.one().id
    shopper.post(f'/account/shared-designs/{share_id}/toggle')
    assert app.test_client().get(f'/made/{token}').status_code == 404
    assert app.test_client().get(f'/made/{token}/qr.png').status_code == 404
    shopper.post(f'/account/shared-designs/{share_id}/toggle')
    assert app.test_client().get(f'/made/{token}').status_code == 200


def test_only_the_owner_can_turn_a_link_off(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    _token(_share(_signed_in(app)))
    with app.app_context():
        share_id = SharedDesign.query.one().id
    other = _signed_in(app, OTHER_EMAIL)
    assert other.post(f'/account/shared-designs/{share_id}/toggle').status_code == 404
    with app.app_context():
        assert SharedDesign.query.one().is_active


def test_orders_through_the_link_are_counted_for_the_creator(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    _share(shopper)
    with app.app_context():
        share = SharedDesign.query.one()
        order = Order(order_number='PMKC-SHR1', email='f@example.com', first_name='Fi', last_name='Friend', subtotal=60.0,
                      total=60.0, payment_status='paid', status='paid', payment_method='stripe', paid_at=datetime.utcnow())
        unpaid = Order(order_number='PMKC-SHR2', email='f@example.com', first_name='Fi', last_name='Friend', subtotal=30.0,
                       total=30.0, payment_status='pending', status='pending', payment_method='stripe')
        db.session.add_all([order, unpaid])
        db.session.flush()
        for o, qty in ((order, 2), (unpaid, 1)):
            db.session.add(OrderItem(order_id=o.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black',
                                     quantity=qty, unit_price=30.0, subtotal=30.0 * qty, shared_design_id=share.id))
        db.session.commit()
    html = shopper.get('/account/shared-designs').get_data(as_text=True)
    assert '1 order (2 shirts)' in html and 'Turn link off' in html


def test_the_cart_and_a_past_order_offer_the_share_button(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    html = shopper.get('/cart/').get_data(as_text=True)
    assert 'data-share-design="/made/share/cart/0"' in html and 'id="madeShareDialog"' in html
    with app.app_context():
        user = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        order = Order(order_number='PMKC-SHR3', email=CUSTOMER_EMAIL, user_id=user.id, first_name='C', last_name='C', subtotal=30.0,
                      total=30.0, payment_status='paid', status='paid', payment_method='stripe', paid_at=datetime.utcnow())
        db.session.add(order)
        db.session.flush()
        item = OrderItem(order_id=order.id, product_id=seed['tee_id'], design_id=seed['free_design_id'], product_name='Tee', size='M',
                         color='Black', quantity=1, unit_price=30.0, subtotal=30.0)
        db.session.add(item)
        db.session.commit()
        item_id = item.id
    page = shopper.get('/account/orders/PMKC-SHR3').get_data(as_text=True)
    assert f'data-share-design="/made/share/order-item/{item_id}"' in page
    resp = shopper.post(f'/made/share/order-item/{item_id}')
    assert resp.status_code == 200 and resp.get_json()['success']
    assert _signed_in(app, OTHER_EMAIL).post(f'/made/share/order-item/{item_id}').status_code == 404
