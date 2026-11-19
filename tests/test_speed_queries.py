"""Page speed guards: pages that list many products must not ask the database one question per product."""
import json

from sqlalchemy import event
from sqlalchemy.engine import Engine

from models import db, Product, ProductColorVariant


class _QueryCounter:
    def __enter__(self):
        self.count = 0
        event.listen(Engine, 'before_cursor_execute', self._hit)
        return self

    def __exit__(self, *exc):
        event.remove(Engine, 'before_cursor_execute', self._hit)

    def _hit(self, *args, **kwargs):
        self.count += 1


def _add_products(app, how_many):
    with app.app_context():
        for i in range(how_many):
            p = Product(style_number=f'SPD{i}', name=f'Speed Tee {i}', category='Tee', age_group='adult',
                        base_price=30, wholesale_cost=6, is_active=True,
                        available_sizes=json.dumps(['M']), available_colors=json.dumps(['Black', 'White']))
            db.session.add(p)
            db.session.flush()
            for color in ('Black', 'White'):
                db.session.add(ProductColorVariant(product_id=p.id, color_name=color, color_hex='#000000',
                                                   front_image_url='/static/img/logo.png',
                                                   size_inventory=json.dumps({'M': 5})))
        db.session.commit()


def test_homepage_query_count_does_not_grow_with_the_catalog(app, client):
    with _QueryCounter() as small:
        assert client.get('/').status_code == 200
    _add_products(app, 25)
    with _QueryCounter() as big:
        assert client.get('/').status_code == 200
    # Twenty-five more products must not cost twenty-five more questions.
    assert big.count <= small.count + 3, (small.count, big.count)


def test_prefetch_gives_each_product_its_own_colors(app, client):
    _add_products(app, 3)
    from flask import g
    from utils.mockups import prefetch_color_variants, get_carousel_colors_for_product
    with app.test_request_context('/'):
        products = Product.query.filter(Product.style_number.like('SPD%')).all()
        prefetch_color_variants(products)
        with _QueryCounter() as counter:
            for p in products:
                names = {c['color_name'] for c in get_carousel_colors_for_product(p, app)}
                assert names == {'Black', 'White'}
        assert counter.count == 0


def _add_orders(app, seed, how_many, start=0):
    from models import Order, OrderItem
    with app.app_context():
        for i in range(start, start + how_many):
            o = Order(order_number=f'SPD-{i:04d}', email='x@example.com', first_name='X', last_name='Y',
                      subtotal=30, total=30, status='paid', production_stage='order_received')
            db.session.add(o)
            db.session.flush()
            for _ in range(2):
                db.session.add(OrderItem(order_id=o.id, product_id=seed['tee_id'], product_name='Tee', size='M',
                                         color='Black', quantity=1, unit_price=30, subtotal=30))
        db.session.commit()


def test_admin_order_board_query_count_does_not_grow_with_orders(app, seed, admin_client):
    _add_orders(app, seed, 3)
    with _QueryCounter() as small:
        resp = admin_client.get('/admin/operations/workflow')
        assert resp.status_code == 200
    _add_orders(app, seed, 20, start=3)
    with _QueryCounter() as big:
        resp = admin_client.get('/admin/operations/workflow')
        assert resp.status_code == 200
    assert b'2 items' in resp.data                       # the per-card item count still shows
    assert big.count <= small.count + 3, (small.count, big.count)


def test_item_counts_for_counts_lines_per_order(app, seed):
    from models import Order
    from utils.production_stages import item_counts_for
    _add_orders(app, seed, 2)
    with app.app_context():
        orders = Order.query.all()
        assert item_counts_for(orders) == {o.id: 2 for o in orders}
        assert item_counts_for([]) == {}


def test_press_sheet_query_count_does_not_grow_with_orders(app, seed, admin_client):
    _add_orders(app, seed, 3)
    with _QueryCounter() as small:
        assert admin_client.get('/admin/production/transfers').status_code == 200
    _add_orders(app, seed, 20, start=3)
    with _QueryCounter() as big:
        assert admin_client.get('/admin/production/transfers').status_code == 200
    assert big.count <= small.count + 4, (small.count, big.count)


def test_production_master_and_blank_list_query_count_flat(app, seed, admin_client):
    _add_orders(app, seed, 3)
    counts = {}
    for url in ('/admin/production/master', '/admin/production/blank-apparel-list'):
        with _QueryCounter() as c:
            assert admin_client.get(url).status_code == 200
        counts[url] = c.count
    _add_orders(app, seed, 20, start=3)
    for url, before in counts.items():
        with _QueryCounter() as c:
            assert admin_client.get(url).status_code == 200
        assert c.count <= before + 4, (url, before, c.count)


def test_public_files_carry_no_cookie_so_they_can_be_cached(guest):
    for path in ('/static/img/logo-monogram.png', '/static/js/main.js'):
        resp = guest.get(path)
        assert resp.status_code == 200
        assert not resp.headers.getlist('Set-Cookie'), path
        assert 'Cookie' not in (resp.headers.get('Vary') or '')
        assert 'max-age' in resp.headers.get('Cache-Control', '')


def test_pages_still_set_the_session_cookie(guest):
    resp = guest.get('/')
    assert resp.status_code == 200
    assert any(c.startswith('session=') for c in resp.headers.getlist('Set-Cookie'))
