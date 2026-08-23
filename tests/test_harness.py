"""Proves the test harness itself is sound before other tests rely on it."""
from models import db, User, Product, Order


def test_app_runs_on_sqlite(app):
    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite://'
    assert app.config['TESTING'] is True


def test_never_points_at_production(app):
    """A regression guard: if this ever fails, tests are about to hit live data."""
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    assert 'postgres' not in uri
    assert 'railway' not in uri


def test_seed_creates_catalog(app, seed):
    with app.app_context():
        assert Product.query.count() == 4
        assert User.query.count() == 3
        assert Order.query.count() == 0


def test_schema_is_reset_between_tests(app, seed):
    """Confirms _clean_db actually drops rows, so tests cannot leak into each other."""
    with app.app_context():
        assert Order.query.count() == 0
        db.session.add(Order(
            order_number='LEAK-CHECK-1', email='x@example.com',
            subtotal=1.0, total=1.0,
        ))
        db.session.commit()
        assert Order.query.count() == 1


def test_previous_test_did_not_leak(app, seed):
    with app.app_context():
        assert Order.query.filter_by(order_number='LEAK-CHECK-1').first() is None


def test_home_page_renders(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'Purposefully Made KC' in resp.data


def test_customer_can_log_in(customer_client):
    # /account/ intentionally redirects to /account/orders, so hit the real page.
    resp = customer_client.get('/account/orders')
    assert resp.status_code == 200


def test_guest_is_redirected_from_account(guest):
    resp = guest.get('/account/orders', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_admin_can_reach_admin(admin_client):
    resp = admin_client.get('/admin/')
    assert resp.status_code == 200


def test_guest_cannot_reach_admin(guest):
    resp = guest.get('/admin/', follow_redirects=False)
    assert resp.status_code in (302, 401, 403, 404)


def test_mail_is_suppressed(app):
    assert app.config['MAIL_SUPPRESS_SEND'] is True
