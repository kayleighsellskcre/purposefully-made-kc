"""Products without a photo must not be sellable."""
import json

from models import Product, ProductColorVariant, db


def _add_imageless_hoodie(app):
    with app.app_context():
        product = Product(
            style_number='PRM2000',
            name='Independent Trading Co. raglan hoodie',
            category='Hoodie',
            age_group='adult',
            base_price=40.00,
            is_active=True,
            available_sizes=json.dumps(['S', 'M', 'L']),
            available_colors=json.dumps(['Black']),
        )
        db.session.add(product)
        db.session.flush()
        db.session.add(ProductColorVariant(
            product_id=product.id,
            color_name='Black',
            color_hex='#000000',
            size_inventory=json.dumps({'S': 10, 'M': 10, 'L': 10}),
        ))
        db.session.commit()
        return product.id


def test_shop_hides_products_without_an_image(client, app):
    pid = _add_imageless_hoodie(app)
    html = client.get('/shop/').get_data(as_text=True)
    assert 'Independent Trading Co. raglan hoodie' not in html
    assert f'/shop/customize/{pid}' not in html
    assert 'Product Image Coming Soon' not in html


def test_group_order_picker_hides_products_without_an_image(customer_client, app):
    _add_imageless_hoodie(app)
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'Independent Trading Co. raglan hoodie' not in html


def test_product_and_customize_pages_redirect_without_an_image(client, app):
    pid = _add_imageless_hoodie(app)
    for path in (f'/shop/product/{pid}', f'/shop/customize/{pid}'):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (301, 302)
        assert resp.headers['Location'].endswith('/shop/')


def test_cart_rejects_products_without_an_image(client, app):
    pid = _add_imageless_hoodie(app)
    resp = client.post('/cart/add', json={
        'product_id': pid,
        'size': 'M',
        'color': 'Black',
        'quantity': 1,
    })
    assert resp.status_code == 400
    assert 'not available' in resp.get_json()['error']


def test_admin_cannot_activate_a_product_without_an_image(admin_client, app):
    pid = _add_imageless_hoodie(app)
    with app.app_context():
        product = Product.query.get(pid)
        product.is_active = False
        db.session.commit()

    resp = admin_client.post(
        f'/admin/products/{pid}/toggle-active',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['ok'] is False
    assert data['is_active'] is False
    assert 'photo' in data['message'].lower()

    with app.app_context():
        assert Product.query.get(pid).is_active is False
