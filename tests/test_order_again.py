"""Order again: past orders go back in the cart as they were made."""
import json
from datetime import datetime, timedelta

from models import Collection, Design, Order, OrderItem, Product, User, db
from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL


def _order(app, seed, number='PMKC-OA1', email=CUSTOMER_EMAIL, items=()):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        order = Order(order_number=number, user_id=user.id, email=email, first_name='Casey', last_name='Customer',
                      subtotal=60.0, total=60.0, payment_status='paid', status='completed', payment_method='stripe',
                      paid_at=datetime.utcnow())
        db.session.add(order)
        db.session.flush()
        for item in items:
            db.session.add(OrderItem(order_id=order.id, subtotal=item.get('unit_price', 30.0) * item.get('quantity', 1),
                                     **{'unit_price': 30.0, 'quantity': 1, 'size': 'M', 'color': 'Black', **item}))
        db.session.commit()
        return order.order_number


def _cart(client):
    with client.session_transaction() as sess:
        return list(sess.get('cart') or [])


def test_a_plain_order_comes_back_with_its_size_color_and_artwork(app, seed, customer_client):
    number = _order(app, seed, items=[{'product_id': seed['tee_id'], 'size': 'L', 'color': 'White', 'quantity': 2,
                                       'design_id': seed['free_design_id'], 'placement': 'center_chest',
                                       'proof_image': '/static/proof.png'}])
    resp = customer_client.post(f'/account/reorder/{number}', data={})
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/cart/')
    line = _cart(customer_client)[0]
    assert (line['product_id'], line['size'], line['color'], line['quantity']) == (seed['tee_id'], 'L', 'White', 2)
    assert line['design_id'] == seed['free_design_id'] and line['placement'] == 'center_chest'
    assert line['design_url'].endswith('gallery-logo.png') and line['proof_front_url'] == '/static/proof.png'
    assert line['is_blank'] is False


def test_the_price_is_todays_price_not_the_old_one(app, seed, customer_client):
    number = _order(app, seed, items=[{'product_id': seed['tee_id'], 'unit_price': 1.0}])
    with app.app_context():
        db.session.get(Product, seed['tee_id']).base_price = 33.0
        db.session.commit()
    customer_client.post(f'/account/reorder/{number}', data={})
    from utils.pricing import calculate_unit_price
    with app.app_context():
        expected = calculate_unit_price(db.session.get(Product, seed['tee_id']), size='M', placement=None,
                                        has_back_design=False, back_design_parts=None, is_blank=True, design_fee=0.0)
    assert _cart(customer_client)[0]['unit_price'] == expected != 1.0


def test_a_back_name_and_number_come_back(app, seed, customer_client):
    meta = {'name': 'SMITH', 'number': '12', 'font': 'block', 'text_color': '#ffffff'}
    number = _order(app, seed, items=[{'product_id': seed['tee_id'], 'back_design_meta': json.dumps(meta)}])
    customer_client.post(f'/account/reorder/{number}', data={})
    line = _cart(customer_client)[0]
    assert line['back_design_kind'] == 'personalization'
    assert line['back_design_meta']['name'] == 'SMITH' and line['back_design_meta']['number'] == '12'


def test_the_same_order_twice_adds_to_the_quantity(app, seed, customer_client):
    number = _order(app, seed, items=[{'product_id': seed['tee_id'], 'quantity': 2}])
    customer_client.post(f'/account/reorder/{number}', data={})
    customer_client.post(f'/account/reorder/{number}', data={})
    cart = _cart(customer_client)
    assert len(cart) == 1 and cart[0]['quantity'] == 4


def test_items_that_cannot_be_ordered_again_are_left_out_with_a_reason(app, seed, customer_client):
    number = _order(app, seed, items=[
        {'product_id': seed['tee_id'], 'product_name': 'Good Tee'},
        {'product_id': seed['inactive_id'], 'product_name': 'Retired Style'},
        {'product_id': seed['hoodie_id'], 'product_name': 'Hoodie', 'design_id': 99999},
    ])
    resp = customer_client.post(f'/account/reorder/{number}', data={}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert len(_cart(customer_client)) == 1
    assert 'Retired Style was left out because we no longer carry this style' in html
    assert 'Hoodie was left out because the artwork is no longer on file' in html


def test_nothing_orderable_keeps_you_on_the_order_page(app, seed, customer_client):
    number = _order(app, seed, items=[{'product_id': seed['inactive_id'], 'product_name': 'Retired Style'}])
    resp = customer_client.post(f'/account/reorder/{number}', data={})
    assert resp.status_code == 302 and f'/account/orders/{number}' in resp.headers['Location']
    assert _cart(customer_client) == []


def test_a_closed_group_store_line_is_left_out_but_an_open_one_is_added(app, seed, customer_client):
    with app.app_context():
        store = db.session.get(Collection, seed['collection_id'])
        store.order_deadline = datetime.utcnow() - timedelta(days=3)
        open_store = Collection(name='Open Store', slug='open-store', is_active=True)
        db.session.add(open_store)
        db.session.commit()
        closed_id, open_id = store.id, open_store.id
    number = _order(app, seed, items=[
        {'product_id': seed['tee_id'], 'collection_id': closed_id, 'product_name': 'Closed Tee'},
        {'product_id': seed['hoodie_id'], 'collection_id': open_id, 'product_name': 'Open Hoodie'}])
    html = customer_client.post(f'/account/reorder/{number}', data={}, follow_redirects=True).get_data(as_text=True)
    cart = _cart(customer_client)
    assert [c['collection_id'] for c in cart] == [open_id]
    assert 'Closed Tee was left out' in html


def test_you_can_only_order_again_from_your_own_orders(app, seed, customer_client):
    number = _order(app, seed, number='PMKC-OA9', email=OTHER_EMAIL, items=[{'product_id': seed['tee_id']}])
    assert customer_client.post(f'/account/reorder/{number}', data={}).status_code == 404


def test_the_order_pages_say_order_again(app, seed, customer_client):
    number = _order(app, seed, items=[{'product_id': seed['tee_id']}])
    for path in ('/account/orders', f'/account/orders/{number}'):
        assert 'Order again' in customer_client.get(path).get_data(as_text=True)


def test_the_completed_email_offers_order_again_to_accounts_only(app, seed):
    from utils.customer_emails import completed_email
    number = _order(app, seed, items=[{'product_id': seed['tee_id']}])
    with app.app_context():
        order = Order.query.filter_by(order_number=number).first()
        built = completed_email(order)
        assert built[4]['label'] == 'Order again' and built[4]['url'].endswith(f'/account/orders/{number}')
        order.user_id = None
        assert len(completed_email(order)) == 4
