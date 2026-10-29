"""The server only opens its own pictures; a bad cart request is answered, not crashed on."""
import pytest


def _base(seed):
    return {'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'placement': 'center_chest', 'quantity': 1}


def test_only_our_own_picture_addresses_are_allowed(app):
    from utils.asset_urls import is_fetchable_url, is_own_asset_url
    with app.app_context():
        app.config['R2_PUBLIC_URL'] = 'https://pub-abc123.r2.dev'
        ok = ['/static/uploads/designs/a.png', '/uploads/designs/a.png', 'https://pub-abc123.r2.dev/designs/a.png',
              'https://purposefullymadekc.com/static/uploads/x.png', 'https://abc.r2.cloudflarestorage.com/b/x.png']
        for url in ok:
            assert is_own_asset_url(url, app), url
        bad = ['http://127.0.0.1:8080/secret', 'http://169.254.169.254/latest/meta-data/', 'https://evil.example/?r2.dev',
               'https://r2.dev.evil.example/a.png', 'https://evil.example/r2.dev/a.png', 'file:///etc/passwd',
               '/static/../app.py', '/static/uploads/../../config.py', '//evil.example/a.png', 'javascript:alert(1)', '']
        for url in bad:
            assert not is_own_asset_url(url, app), url
            assert not is_fetchable_url(url, app), url
        assert is_fetchable_url('https://cdn.ssactivewear.com/Images/Style/1.jpg', app)          # a garment photo host
        assert not is_fetchable_url('https://cdn.ssactivewear.com.evil.example/1.jpg', app)


def test_remote_url_allowed_looks_at_the_host_not_the_text(app):
    from utils.order_artwork import remote_url_allowed
    with app.app_context():
        assert remote_url_allowed(app, 'https://pub-1.r2.dev/a.png')
        assert not remote_url_allowed(app, 'http://169.254.169.254/?r2.dev')
        assert not remote_url_allowed(app, 'https://evil.example/r2.cloudflarestorage.com/a.png')


def test_the_cart_refuses_a_picture_address_that_is_not_ours(app, seed, guest):
    payload = {**_base(seed), 'back_design_url': 'http://127.0.0.1:9/internal', 'back_design_name': 'SAM',
               'back_design_vertical': 'true', 'back_design_combo': 'true'}
    assert guest.post('/cart/add', json=payload).status_code == 400
    assert guest.post('/cart/add', json={**_base(seed), 'design_url': 'https://evil.example/a.png'}).status_code == 400
    ok = guest.post('/cart/add', json={**_base(seed), 'design_url': '/static/uploads/designs/gallery-logo.png'})
    assert ok.status_code == 200


@pytest.mark.parametrize('bad', [
    {'size': 'M', 'color': 'Black'},                           # no product
    {'product_id': 'abc', 'size': 'M', 'color': 'Black'},
    {'quantity': 'lots'},
    {'unit_price': 'free'},
    {'print_specs': '{not json'},
    {'print_specs': '[1, 2]'},
])
def test_a_bad_cart_request_is_answered_not_crashed_on(app, seed, guest, bad):
    payload = {**_base(seed), **bad}
    if 'size' in bad and 'product_id' not in bad:
        payload.pop('product_id')
    assert guest.post('/cart/add', json=payload).status_code == 400
    assert guest.post('/cart/add', data='[]', content_type='application/json').status_code == 400
