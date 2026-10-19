"""Stage 9: every page that can be opened without picking a record still opens (no server errors),
for visitors and for the admin, and the design gallery stays quick with a big library."""
import time

import pytest

from models import Design, DesignCategoryLink, db

SKIP_WORDS = ('logout', 'delete', 'remove', 'cron', 'webhook', 'sync', 'send', 'reset', 'run', 'refresh', 'backup', 'export',
              'download', 'scan', 'process', 'oauth', 'callback', 'auth', 'stripe', 'square', 'twilio', 'brevo', 'unsubscribe',
              'impersonate', 'regenerate', 'import', 'purge', 'clear', 'test-', 'sitemap', 'cancel', 'archive', 'restore')


def _pages(app):
    out = []
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods or rule.arguments or rule.endpoint == 'static':
            continue
        if any(w in rule.rule.lower() for w in SKIP_WORDS):
            continue
        out.append(rule.rule)
    return sorted(set(out))


def test_every_open_page_loads_for_visitors(app, seed):
    client = app.test_client()
    failures = []
    for path in _pages(app):
        if path.startswith('/admin'):
            continue
        r = client.get(path)
        if r.status_code >= 500:
            failures.append((path, r.status_code))
    assert not failures, failures


def test_every_admin_page_loads_for_the_admin(app, seed, admin_client):
    failures = []
    for path in _pages(app):
        if not path.startswith('/admin'):
            continue
        r = admin_client.get(path)
        if r.status_code >= 500:
            failures.append((path, r.status_code))
    assert not failures, failures


def test_the_design_pages_load_with_a_big_library(app, seed, client, admin_client):
    with app.app_context():
        keys = ['kansas-city', 'faith-inspiration', 'sports-game-day', 'school-spirit', 'funny-sarcastic']
        for i in range(1200):
            d = Design(filename=f'b{i}.png', file_path=f'uploads/designs/b{i}.png', title=f'Big Library Design {i}',
                       is_gallery=True, folder='sports')
            db.session.add(d)
            db.session.flush()
            db.session.add(DesignCategoryLink(design_id=d.id, category_key=keys[i % 5], is_primary=True))
        db.session.commit()
    for url, budget in (('/shop/designs', 6.0), ('/shop/designs?collection=faith-inspiration', 6.0),
                        ('/shop/designs?q=library', 6.0), ('/admin/design-library', 6.0),
                        ('/admin/design-library/browse', 6.0)):
        start = time.time()
        r = (admin_client if url.startswith('/admin') else client).get(url)
        took = time.time() - start
        assert r.status_code == 200, url
        if url.endswith('q=library'):
            assert 'Showing the first 300 of 1200 designs' in r.get_data(as_text=True)
            assert len(r.data) < 900 * 1024
        assert took < budget, (url, round(took, 2))


def test_checkout_card_errors_use_kind_wording_and_show_the_shop_phone(client, seed):
    client.post('/cart/add', data={'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
                                   'placement': 'center_chest', 'design_id': seed['free_design_id']})
    html = client.get('/checkout/').get_data(as_text=True)
    assert 'function friendlyCardError' in html and 'expiration date does not look right' in html
    assert '785.249.1464' in html
