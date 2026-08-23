"""Favicon, robots.txt, sitemap.xml, error pages, and the admin form crashes."""
import json

from models import db, Product


# ── Favicon and icons ────────────────────────────────────────────────────────

def test_favicon_is_served(client):
    """Regression: base.html linked /static/favicon.ico but the file did not exist."""
    resp = client.get('/static/favicon.ico')
    assert resp.status_code == 200
    assert resp.data[:4] == b'\x00\x00\x01\x00', 'not a real .ico file'


def test_touch_and_png_icons_are_served(client):
    for path in (
        '/static/img/favicon-32.png',
        '/static/img/favicon-192.png',
        '/static/img/apple-touch-icon.png',
    ):
        assert client.get(path).status_code == 200, path


def test_open_graph_image_is_served(client):
    assert client.get('/static/img/logo.png').status_code == 200


def test_pages_link_the_icons(client):
    html = client.get('/').get_data(as_text=True)
    assert 'favicon.ico' in html
    assert 'apple-touch-icon' in html


# ── robots.txt ───────────────────────────────────────────────────────────────

def test_robots_txt_is_served(client):
    resp = client.get('/robots.txt')
    assert resp.status_code == 200
    assert resp.mimetype == 'text/plain'


def test_robots_allows_the_public_site(client):
    body = client.get('/robots.txt').get_data(as_text=True)
    assert 'User-agent: *' in body
    assert 'Allow: /' in body


def test_robots_blocks_private_areas(client):
    body = client.get('/robots.txt').get_data(as_text=True)
    for path in ('/admin/', '/account/', '/cart/', '/checkout/', '/auth/'):
        assert f'Disallow: {path}' in body, path


def test_robots_points_at_the_sitemap(client):
    body = client.get('/robots.txt').get_data(as_text=True)
    assert 'Sitemap:' in body
    assert '/sitemap.xml' in body


# ── sitemap.xml ──────────────────────────────────────────────────────────────

def test_sitemap_is_served_as_xml(client):
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/xml'


def test_sitemap_is_well_formed(client):
    from xml.etree import ElementTree
    body = client.get('/sitemap.xml').get_data(as_text=True)
    root = ElementTree.fromstring(body)
    assert root.tag.endswith('urlset')
    assert len(root) > 0


def test_sitemap_lists_the_key_public_pages(client):
    body = client.get('/sitemap.xml').get_data(as_text=True)
    for path in ('/shop/', '/shop/designs', '/shop/group-orders',
                 '/custom-design/', '/about', '/contact', '/privacy', '/terms'):
        assert f'{path}<' in body or f'{path}</loc>' in body, path


def test_sitemap_lists_active_products(client, seed):
    body = client.get('/sitemap.xml').get_data(as_text=True)
    assert f'/shop/product/{seed["tee_id"]}<' in body
    assert f'/shop/product/{seed["hoodie_id"]}<' in body


def test_sitemap_omits_inactive_products(client, seed):
    body = client.get('/sitemap.xml').get_data(as_text=True)
    assert f'/shop/product/{seed["inactive_id"]}<' not in body


def test_sitemap_omits_private_pages(client):
    body = client.get('/sitemap.xml').get_data(as_text=True)
    for path in ('/admin', '/account', '/cart', '/checkout', '/auth'):
        assert path not in body, path


def test_sitemap_omits_password_protected_collections(client, seed, app):
    from models import Collection
    with app.app_context():
        locked = Collection(name='Locked Store', slug='locked-store',
                            is_active=True, show_in_directory=True)
        locked.set_password('secret123')
        db.session.add(locked)
        db.session.commit()
    body = client.get('/sitemap.xml').get_data(as_text=True)
    assert 'locked-store' not in body


# ── 404 page ─────────────────────────────────────────────────────────────────

def test_unknown_url_returns_a_helpful_404(client):
    resp = client.get('/this-page-does-not-exist')
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert 'Purposefully Made KC' in body
    # A useful 404 offers a way out.
    assert 'href' in body


def test_unknown_product_returns_404(client):
    assert client.get('/shop/product/999999').status_code == 404


# ── Admin product form: the float(None) crash ───────────────────────────────

def _product_form(**over):
    form = {
        'style_number': '3001', 'name': 'Unisex Jersey Short Sleeve Tee',
        'category': 'Tee', 'description': 'A tee.',
        'base_price': '30.00', 'wholesale_cost': '6.00',
        'available_sizes': 'S,M,L', 'available_colors': 'Black,White',
    }
    form.update(over)
    return form


def test_editing_a_product_with_a_blank_price_does_not_crash(admin_client, seed):
    """Regression: float(None) raised TypeError and returned a 500 five times in production."""
    resp = admin_client.post(
        f'/admin/products/{seed["tee_id"]}/edit',
        data=_product_form(base_price=''),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert 'base price' in resp.get_data(as_text=True).lower()


def test_editing_a_product_with_a_missing_price_does_not_crash(admin_client, seed):
    form = _product_form()
    form.pop('base_price')
    resp = admin_client.post(
        f'/admin/products/{seed["tee_id"]}/edit', data=form, follow_redirects=True,
    )
    assert resp.status_code == 200


def test_editing_a_product_with_a_non_numeric_price_does_not_crash(admin_client, seed):
    resp = admin_client.post(
        f'/admin/products/{seed["tee_id"]}/edit',
        data=_product_form(base_price='thirty dollars'),
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_a_rejected_edit_leaves_the_price_unchanged(admin_client, seed, app):
    admin_client.post(
        f'/admin/products/{seed["tee_id"]}/edit',
        data=_product_form(base_price=''),
        follow_redirects=True,
    )
    with app.app_context():
        assert Product.query.get(seed['tee_id']).base_price == 30.00


def test_a_valid_edit_still_saves(admin_client, seed, app):
    resp = admin_client.post(
        f'/admin/products/{seed["tee_id"]}/edit',
        data=_product_form(base_price='32.50', name='Renamed Tee'),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        product = Product.query.get(seed['tee_id'])
        assert product.base_price == 32.50
        assert product.name == 'Renamed Tee'


def test_a_price_with_a_dollar_sign_is_accepted(admin_client, seed, app):
    admin_client.post(
        f'/admin/products/{seed["tee_id"]}/edit',
        data=_product_form(base_price='$1,234.50'),
        follow_redirects=True,
    )
    with app.app_context():
        assert Product.query.get(seed['tee_id']).base_price == 1234.50


def test_a_blank_wholesale_cost_is_treated_as_zero(admin_client, seed, app):
    admin_client.post(
        f'/admin/products/{seed["tee_id"]}/edit',
        data=_product_form(wholesale_cost=''),
        follow_redirects=True,
    )
    with app.app_context():
        assert Product.query.get(seed['tee_id']).wholesale_cost == 0


def test_adding_a_product_with_a_blank_price_does_not_crash(admin_client, seed, app):
    with app.app_context():
        before = Product.query.count()
    resp = admin_client.post(
        '/admin/products/add',
        data=_product_form(style_number='NEW-1', base_price=''),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert Product.query.count() == before, 'an invalid product was created'


def test_adding_a_valid_product_works(admin_client, seed, app):
    resp = admin_client.post(
        '/admin/products/add',
        data=_product_form(style_number='NEW-2', name='Brand New Tee', base_price='28'),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        product = Product.query.filter_by(style_number='NEW-2').one()
        assert product.base_price == 28.0
