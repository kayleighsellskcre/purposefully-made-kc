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
