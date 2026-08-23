"""Request every GET route as a guest, a customer, and an admin.

The point is breadth, not depth: nothing here should ever return a 500, and a
protected page must redirect a guest to sign in rather than either crashing or
quietly serving private data. Individual behaviour is covered by the focused
test modules; this is the net that catches a page nobody thought to open.

Routes are discovered from the URL map, so a new page is swept automatically.
"""
import pytest

from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL

# Paths that legitimately do something other than render a page for a browser.
SKIP_EXACT = {
    '/auth/logout',          # ends the session the other assertions rely on
    '/static/<path:filename>',
}

# Prefixes for machine endpoints and long-running jobs. Sweeping these either
# hits a third-party API or costs minutes, so they are tested individually.
SKIP_PREFIXES = (
    '/admin/sync',
    '/admin/import',
    '/admin/sanmar',
    '/admin/ssactivewear',
    '/admin/widen',
    '/admin/catalog/refresh',
    '/admin/backfill',
    '/admin/products/refresh',
    '/admin/test-email',
    '/admin/test-sms',
)


def _fill(rule, seed):
    """Substitute real seeded ids into a rule, or return None if we cannot."""
    values = {}
    for name in rule.arguments:
        converter = rule._converters[name].__class__.__name__
        if name in ('product_id',):
            values[name] = seed['tee_id']
        elif name in ('design_id',):
            values[name] = seed['free_design_id']
        elif name in ('collection_id',):
            values[name] = seed['collection_id']
        elif name in ('user_id', 'customer_id'):
            values[name] = seed['customer_id']
        elif name == 'slug':
            values[name] = seed['collection_slug']
        elif 'Integer' in converter:
            # An id we have no row for; the page should 404, which is fine.
            values[name] = 1
        elif 'Path' in converter or 'String' in converter:
            values[name] = 'test'
        else:
            return None
    try:
        return rule.build(values, append_unknown=False)[1]
    except Exception:
        return None


def _sweepable(app, seed):
    """(path, endpoint) for every GET route worth requesting."""
    out = []
    for rule in app.url_map.iter_rules():
        if 'GET' not in (rule.methods or set()):
            continue
        if rule.rule in SKIP_EXACT or rule.rule.startswith(SKIP_PREFIXES):
            continue
        path = _fill(rule, seed)
        if path is None:
            continue
        out.append((path, rule.endpoint))
    return sorted(set(out))


def test_the_sweep_finds_a_realistic_number_of_routes(app, seed):
    assert len(_sweepable(app, seed)) > 80


def test_no_route_returns_a_server_error_for_a_guest(app, seed, guest):
    failures = []
    for path, endpoint in _sweepable(app, seed):
        resp = guest.get(path, follow_redirects=False)
        if resp.status_code >= 500:
            failures.append(f'{endpoint} {path} -> {resp.status_code}')
    assert not failures, 'guest sweep failures:\n' + '\n'.join(failures)


def test_no_route_returns_a_server_error_for_a_customer(app, seed, client, login):
    login(client, CUSTOMER_EMAIL)
    failures = []
    for path, endpoint in _sweepable(app, seed):
        resp = client.get(path, follow_redirects=False)
        if resp.status_code >= 500:
            failures.append(f'{endpoint} {path} -> {resp.status_code}')
    assert not failures, 'customer sweep failures:\n' + '\n'.join(failures)


def test_no_route_returns_a_server_error_for_an_admin(app, seed, client, login):
    login(client, ADMIN_EMAIL)
    failures = []
    for path, endpoint in _sweepable(app, seed):
        resp = client.get(path, follow_redirects=False)
        if resp.status_code >= 500:
            failures.append(f'{endpoint} {path} -> {resp.status_code}')
    assert not failures, 'admin sweep failures:\n' + '\n'.join(failures)


def test_every_redirect_target_resolves(app, seed, guest):
    """A redirect to a URL that itself 500s is as bad as a 500."""
    failures = []
    for path, endpoint in _sweepable(app, seed):
        resp = guest.get(path, follow_redirects=True)
        if resp.status_code >= 500:
            failures.append(f'{endpoint} {path} -> {resp.status_code}')
    assert not failures, 'redirect chain failures:\n' + '\n'.join(failures)


# ── Authorisation boundaries ─────────────────────────────────────────────────

def _admin_paths(app, seed):
    return [(p, e) for p, e in _sweepable(app, seed) if p.startswith('/admin')]


def test_admin_pages_are_closed_to_guests(app, seed, guest):
    leaked = []
    for path, endpoint in _admin_paths(app, seed):
        resp = guest.get(path, follow_redirects=False)
        if resp.status_code == 200:
            leaked.append(f'{endpoint} {path}')
    assert not leaked, 'admin pages served to a guest:\n' + '\n'.join(leaked)


def test_admin_pages_are_closed_to_a_signed_in_customer(app, seed, client, login):
    login(client, CUSTOMER_EMAIL)
    leaked = []
    for path, endpoint in _admin_paths(app, seed):
        resp = client.get(path, follow_redirects=False)
        if resp.status_code == 200:
            leaked.append(f'{endpoint} {path}')
    assert not leaked, 'admin pages served to a customer:\n' + '\n'.join(leaked)


def test_the_admin_can_open_the_admin_dashboard(app, seed, client, login):
    """Guard against the sweep above passing simply because admin is broken."""
    login(client, ADMIN_EMAIL)
    assert client.get('/admin/').status_code == 200


ACCOUNT_PAGES = [
    '/account/orders',
    '/account/profile',
    '/account/designs',
]


@pytest.mark.parametrize('path', ACCOUNT_PAGES)
def test_account_pages_send_a_guest_to_sign_in(guest, path):
    resp = guest.get(path, follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


@pytest.mark.parametrize('path', ACCOUNT_PAGES)
def test_account_pages_open_for_a_signed_in_customer(customer_client, path):
    assert customer_client.get(path).status_code == 200


def test_the_sign_in_redirect_returns_you_to_where_you_were_going(guest):
    resp = guest.get('/account/profile', follow_redirects=False)
    assert 'next=' in resp.headers['Location']


def test_favourites_are_open_to_guests_and_kept_in_their_session(guest, seed):
    """Guests deliberately get favourites without an account, held in session."""
    assert guest.get('/favorites').status_code == 200
    guest.post('/favorites/add', json={'product_id': seed['tee_id'],
                                       'color_name': 'Black'})
    body = guest.get('/favorites').get_data(as_text=True)
    assert 'Unisex Jersey Short Sleeve Tee' in body


def test_one_guest_cannot_see_another_guests_favourites(app, seed):
    first = app.test_client()
    first.post('/favorites/add', json={'product_id': seed['tee_id'],
                                       'color_name': 'Black'})
    second = app.test_client()
    body = second.get('/favorites').get_data(as_text=True)
    assert 'Unisex Jersey Short Sleeve Tee' not in body
