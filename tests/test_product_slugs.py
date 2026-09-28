"""SEO-friendly product slugs instead of /shop/customize/238."""
from models import Product, db
from utils.product_slugs import (
    RESERVED_PRODUCT_SLUGS,
    assign_product_slug,
    slug_from_product,
    unique_slug,
)


def test_slug_uses_brand_and_customer_facing_name():
    product = Product(
        style_number='3001CVC',
        name='Unisex CVC Jersey Tee',
        brand='Bella+Canvas',
    )
    assert slug_from_product(product) == 'bella-canvas-unisex-cvc-jersey-tee'


def test_slug_does_not_repeat_a_brand_already_in_the_name():
    product = Product(
        style_number='BC3001',
        name='BELLA+CANVAS Unisex Jersey Short Sleeve Tee',
        brand='Bella+Canvas',
    )
    assert slug_from_product(product) == 'bella-canvas-unisex-jersey-short-sleeve-tee'


def test_collision_appends_the_style_number():
    taken = {'bella-canvas-unisex-cvc-jersey-tee'}
    assert unique_slug(
        'bella-canvas-unisex-cvc-jersey-tee',
        taken,
        '3001CVC',
    ) == 'bella-canvas-unisex-cvc-jersey-tee-3001cvc'


def test_reserved_shop_paths_are_not_used_as_slugs():
    assert unique_slug('customize', set(), '3001') == 'customize-3001'
    for reserved in RESERVED_PRODUCT_SLUGS:
        assert unique_slug(reserved, set(), 'X1') != reserved


def test_seed_products_get_readable_slugs(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        assert tee.slug == 'bella-canvas-unisex-jersey-short-sleeve-tee'
        assert seed['tee_slug'] == tee.slug


def test_shop_cards_link_to_the_slug_url(client, seed):
    html = client.get('/shop/').get_data(as_text=True)
    assert f'/shop/customize/{seed["tee_slug"]}' in html
    assert f'/shop/customize/{seed["tee_id"]}' not in html


def test_slug_customize_and_product_pages_are_200(client, seed):
    assert client.get(f'/shop/product/{seed["tee_slug"]}').status_code == 200
    assert client.get(f'/shop/customize/{seed["tee_slug"]}').status_code == 200


def test_numeric_product_urls_permanently_redirect_to_the_slug(client, seed):
    product = client.get(
        f'/shop/product/{seed["tee_id"]}', follow_redirects=False,
    )
    assert product.status_code == 301
    assert product.headers['Location'].endswith(f'/shop/product/{seed["tee_slug"]}')

    customize = client.get(
        f'/shop/customize/{seed["tee_id"]}', follow_redirects=False,
    )
    assert customize.status_code == 301
    assert customize.headers['Location'].endswith(
        f'/shop/customize/{seed["tee_slug"]}'
    )


def test_numeric_redirect_keeps_query_string(client, seed):
    resp = client.get(
        f'/shop/customize/{seed["tee_id"]}?design_id=9',
        follow_redirects=False,
    )
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith(
        f'/shop/customize/{seed["tee_slug"]}?design_id=9'
    )


def test_unknown_slug_is_404(client):
    assert client.get('/shop/product/not-a-real-garment').status_code == 404
    assert client.get('/shop/customize/not-a-real-garment').status_code == 404


def test_sitemap_lists_slug_urls_not_numeric_ids(client, seed):
    body = client.get('/sitemap.xml').get_data(as_text=True)
    assert f'/shop/product/{seed["tee_slug"]}' in body
    assert f'/shop/product/{seed["tee_id"]}' not in body


def test_new_products_receive_a_slug(app, _clean_db):
    with app.app_context():
        product = Product(
            style_number='3005CVC',
            name='Unisex Heather CVC V-Neck Tee',
            category='V-Neck',
            base_price=32.00,
            is_active=True,
        )
        db.session.add(product)
        db.session.commit()
        assert product.slug == 'bella-canvas-unisex-heather-cvc-v-neck-tee'
        assign_product_slug(product)
        assert product.slug == 'bella-canvas-unisex-heather-cvc-v-neck-tee'
