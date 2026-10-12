"""One cart, one payment, several stores of the same organization.

A parent can put a Basketball jersey, a Volleyball jersey and Fan Wear in one
cart and pay once. Every shirt remembers its store, so each group's admin list
and Excel file still show exactly their own shirts.
"""
import io
from datetime import datetime, timedelta

import openpyxl

from models import Collection, Order, OrderItem, db
from tests.test_group_order_audit import _slug_of
from tests.test_org_fan_store import _fan
from tests.test_org_fan_wear import _build

BASKETBALL = 'Basketball: Rainbow Cheetahs'
VOLLEYBALL = 'Soccer: Rainbow Cheetahs'     # the second team with a jersey (Volleyball is fan wear only)


def _open_cash_everywhere(app):
    with app.app_context():
        for coll in Collection.query.filter(Collection.name.like('%Rainbow Cheetahs')).all():
            coll.allow_cash_pickup = True
        db.session.commit()


def _add_jersey(client, app, name, seed, kit='home'):
    from utils.group_orders import team_store_config
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        uniform = team_store_config(coll)['uniform']
        product_id = uniform['product_ids'][0]
        color = uniform[f'{kit}_color']
        slug = coll.slug
    client.get(f'/c/{slug}')
    resp = client.post('/cart/add', data={
        'product_id': product_id, 'size': 'M', 'color': color, 'quantity': 1,
        'catalog_section': 'uniform', 'uniform_kit': kit, 'placement': 'center_chest',
    })
    assert resp.get_json().get('success'), resp.get_json()
    return resp.get_json()


def _add_fan(client, app, seed):
    _, fan_slug = _fan(app)
    client.get(f'/c/{fan_slug}')
    resp = client.post('/cart/add', data={
        'product_id': seed['hoodie_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
        'catalog_section': 'fan', 'placement': 'center_chest',
    })
    assert resp.get_json().get('success'), resp.get_json()
    return resp.get_json()


def _cart(client):
    with client.session_transaction() as sess:
        return list(sess.get('cart') or [])


def _checkout(client):
    return client.post('/checkout/complete', json={
        'payment_method': 'cash', 'shipping_method': 'pickup', 'email': 'mom@example.com',
        'first_name': 'Mia', 'last_name': 'Mom', 'phone': '816-555-0100', 'checkout_token': 'tok-mixed-1',
    })


# ── Putting things in one cart ───────────────────────────────────────────────

def test_jerseys_from_two_teams_share_one_cart(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    _open_cash_everywhere(app)
    admin_client.get('/auth/logout')
    first = _add_jersey(client, app, BASKETBALL, seed)
    second = _add_jersey(client, app, VOLLEYBALL, seed)
    assert not second.get('notice')                                   # nothing was swapped out
    cart = _cart(client)
    assert len(cart) == 2
    with app.app_context():
        ids = {Collection.query.filter_by(name=n).one().id for n in (BASKETBALL, VOLLEYBALL)}
    assert {i['collection_id'] for i in cart} == ids


def test_a_jersey_and_fan_wear_share_one_cart(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    reply = _add_fan(client, app, seed)
    assert not reply.get('notice')
    assert {i['catalog_section'] for i in _cart(client)} == {'uniform', 'fan'}


def test_the_same_shirt_from_two_stores_stays_two_lines(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    _add_jersey(client, app, VOLLEYBALL, seed)
    _add_jersey(client, app, BASKETBALL, seed)
    quantities = sorted(i['quantity'] for i in _cart(client))
    assert quantities == [1, 2]


def test_a_store_from_another_organization_still_replaces_the_cart(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    client.get('/c/test-elementary')
    resp = client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1, 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    })
    assert resp.get_json().get('success'), resp.get_json()
    assert resp.get_json().get('notice')
    assert {i['collection_id'] for i in _cart(client)} == {seed['collection_id']}


def test_the_cart_page_says_which_team_each_shirt_is_for(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    _add_jersey(client, app, VOLLEYBALL, seed)
    _add_fan(client, app, seed)
    html = client.get('/cart/').get_data(as_text=True)
    for store in (BASKETBALL, VOLLEYBALL, 'Fan Wear: Rainbow Cheetahs'):
        assert f'For {store}' in html
    assert "You're ordering for <strong>Rainbow Cheetahs</strong>" in html
    assert 'Add another team' in html


def test_the_cart_offers_fan_wear_as_its_own_store(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    _, fan_slug = _fan(app)
    assert f'href="/c/{fan_slug}"' in client.get('/cart/').get_data(as_text=True)


def test_a_team_page_sends_fan_wear_shoppers_to_fan_wear_even_with_a_full_cart(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    _, fan_slug = _fan(app)
    page = client.get(f'/c/{_slug_of(app, BASKETBALL)}').get_data(as_text=True)
    assert f'href="/c/{fan_slug}"' in page


# ── Paying once ──────────────────────────────────────────────────────────────

def _place(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    _open_cash_everywhere(app)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    _add_jersey(client, app, VOLLEYBALL, seed)
    _add_fan(client, app, seed)
    resp = _checkout(client)
    assert resp.status_code == 200 and resp.get_json()['success'], resp.get_json()
    return resp.get_json()['order_number']


def test_one_payment_makes_one_order_whose_shirts_remember_their_stores(client, admin_client, app, seed):
    number = _place(client, admin_client, app, seed)
    fan_id, _ = _fan(app)
    with app.app_context():
        assert Order.query.count() == 1
        order = Order.query.filter_by(order_number=number).one()
        bb = Collection.query.filter_by(name=BASKETBALL).one().id
        vb = Collection.query.filter_by(name=VOLLEYBALL).one().id
        assert order.collection_id == bb                                 # the first store added
        assert sorted(i.collection_id for i in order.items) == sorted([bb, vb, fan_id])
        assert order.subtotal == sum(i.subtotal for i in order.items)


def test_every_group_sees_the_order_in_the_admin_list(client, admin_client, app, seed):
    number = _place(client, admin_client, app, seed)
    from tests.conftest import ADMIN_EMAIL, _login
    client.get('/auth/logout')
    _login(client, ADMIN_EMAIL)
    fan_id, _ = _fan(app)
    with app.app_context():
        ids = [Collection.query.filter_by(name=n).one().id for n in (BASKETBALL, VOLLEYBALL)] + [fan_id]
    for cid in ids:
        html = client.get(f'/admin/orders?collection={cid}&status=all').get_data(as_text=True)
        assert number in html, cid
    with app.app_context():
        other = Collection.query.get(seed['collection_id']).id
    assert number not in client.get(f'/admin/orders?collection={other}&status=all').get_data(as_text=True)


def test_admin_collections_counts_the_shared_order_for_every_group(client, admin_client, app, seed):
    _place(client, admin_client, app, seed)
    from utils.group_orders import order_counts_by_collection
    fan_id, _ = _fan(app)
    with app.app_context():
        counts = order_counts_by_collection()
        for name in (BASKETBALL, VOLLEYBALL):
            assert counts[Collection.query.filter_by(name=name).one().id] == 1
        assert counts[fan_id] == 1


def _xlsx_rows(app, collection_id, sheet):
    from routes.collection import _build_group_order_xlsx
    with app.app_context():
        book = openpyxl.load_workbook(io.BytesIO(
            _build_group_order_xlsx(db.session.get(Collection, collection_id), include_internal=True)))
        rows = list(book[sheet].iter_rows(values_only=True))
    return rows[0], rows[1:]


def test_each_groups_excel_lists_only_its_own_shirts_and_what_else_was_in_the_payment(client, admin_client, app, seed):
    number = _place(client, admin_client, app, seed)
    fan_id, _ = _fan(app)
    with app.app_context():
        bb = Collection.query.filter_by(name=BASKETBALL).one().id
        vb = Collection.query.filter_by(name=VOLLEYBALL).one().id
    for cid, section, others in ((bb, 'Home Uniform', {VOLLEYBALL, 'Fan Wear: Rainbow Cheetahs'}),
                                 (vb, 'Home Uniform', {BASKETBALL, 'Fan Wear: Rainbow Cheetahs'}),
                                 (fan_id, 'Family & Fan Wear', {BASKETBALL, VOLLEYBALL})):
        head, rows = _xlsx_rows(app, cid, 'All Orders')
        assert len(rows) == 1, (cid, rows)                               # exactly one shirt, its own
        row = dict(zip(head, rows[0]))
        assert row['Order #'] == number and row['Section'] == section
        assert set(row['Also Ordered From'].split(', ')) == others
        head, rows = _xlsx_rows(app, cid, 'Orders')
        assert dict(zip(head, rows[0]))['Items'] == 1


def test_a_groups_revenue_is_only_its_share_of_a_shared_payment(client, admin_client, app, seed):
    _place(client, admin_client, app, seed)
    with app.app_context():
        order = Order.query.one()
        order.payment_status = 'paid'
        db.session.commit()
        bb = Collection.query.filter_by(name=BASKETBALL).one().id
        share = sum(i.subtotal for i in order.items if i.collection_id == bb)
        total = order.total
    from routes.collection import _build_group_order_xlsx
    with app.app_context():
        book = openpyxl.load_workbook(io.BytesIO(
            _build_group_order_xlsx(db.session.get(Collection, bb), include_internal=True)))
        summary = {r[0]: r[1] for r in book['Summary'].iter_rows(min_row=5, max_row=9, values_only=True)}
    assert round(summary['Total Revenue'], 2) == round(share, 2) and share < total
    assert summary['Total Items'] == 1


def test_orders_made_before_this_change_still_belong_to_their_store(admin_client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        bb = Collection.query.filter_by(name=BASKETBALL).one().id
        order = Order(order_number='OLD-1', collection_id=bb, email='o@example.com', first_name='O', last_name='L',
                      subtotal=30, total=30, status='pending')
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=seed['tee_id'], size='M', color='Black',
                                 quantity=1, unit_price=30, subtotal=30))        # no store recorded on the shirt
        db.session.commit()
    head, rows = _xlsx_rows(app, bb, 'All Orders')
    assert len(rows) == 1 and dict(zip(head, rows[0]))['Order #'] == 'OLD-1'


# ── Safety ───────────────────────────────────────────────────────────────────

def test_a_closed_store_blocks_the_whole_checkout_with_a_clear_message(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    _open_cash_everywhere(app)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    _add_jersey(client, app, VOLLEYBALL, seed)
    with app.app_context():
        vb = Collection.query.filter_by(name=VOLLEYBALL).one()
        vb.order_deadline = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
    resp = _checkout(client)
    assert resp.status_code == 400 or not resp.get_json().get('success')
    with app.app_context():
        assert Order.query.count() == 0


def test_the_checkout_page_names_the_team_for_each_shirt(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    _open_cash_everywhere(app)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    _add_jersey(client, app, VOLLEYBALL, seed)
    html = client.get('/checkout/').get_data(as_text=True)
    assert f'For {BASKETBALL}' in html and f'For {VOLLEYBALL}' in html


def test_the_receipt_says_which_group_each_shirt_is_for(client, admin_client, app, seed, outbox):
    number = _place(client, admin_client, app, seed)
    from routes.checkout import send_order_confirmation_email
    with app.app_context():
        order = Order.query.filter_by(order_number=number).one()
        send_order_confirmation_email(order)
    bodies = ' '.join(m.body for m in outbox)
    assert f'for {BASKETBALL}' in bodies and f'for {VOLLEYBALL}' in bodies and 'for Fan Wear: Rainbow Cheetahs' in bodies
    assert 'Rainbow Cheetahs (' in bodies


# ── Leaving a group order ────────────────────────────────────────────────────

def test_the_shop_button_takes_shoppers_out_of_any_group_order(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    with client.session_transaction() as sess:
        assert sess.get('collection_id')
    assert client.get('/shop/').status_code == 200
    with client.session_transaction() as sess:
        assert not sess.get('collection_id')                 # no longer attached to a group
        assert _cart_len(sess) == 1                          # the cart itself is untouched


def _cart_len(sess):
    return len(sess.get('cart') or [])


def test_shop_items_are_not_tied_to_a_group_after_leaving(client, admin_client, app, seed):
    _build(admin_client, app, seed)
    admin_client.get('/auth/logout')
    _add_jersey(client, app, BASKETBALL, seed)
    client.get('/shop/')
    page = client.get('/').get_data(as_text=True)
    assert "You're ordering for" not in page
