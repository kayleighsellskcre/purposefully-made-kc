"""The Widen bulk image-import endpoints must fail closed.

`POST /widen-import` and `POST /admin/import-widen` upsert image URLs for every
product. Both answer with `Access-Control-Allow-Origin: *` so the import can be
posted from medialibrary1.com.

They are not equally exposed, which is worth stating because it is easy to get
backwards. `/admin/import-widen` sits under the admin blueprint, whose
`before_request` firewall demands an authenticated admin on every `/admin` URL.
`/widen-import` is attached to no blueprint at all, so nothing checks a session:
the shared secret is the only thing between the open internet and a write to
every product's images.

That secret used to be the literal string 'widen-import-2024', in the source of
both files. It was readable by anyone who could read the repository and could
not be rotated without a deploy. It now comes from WIDEN_IMPORT_SECRET, with no
default, so both endpoints are inert unless an import is deliberately running.
"""
import json
import os

import pytest

from models import Product, ProductColorVariant
from utils import widen_import_auth

# No session required. This is the one that was genuinely open.
OPEN_ENDPOINT = '/widen-import'
# Behind the admin firewall as well as the secret.
ADMIN_ENDPOINT = '/admin/import-widen'
ENDPOINTS = [OPEN_ENDPOINT, ADMIN_ENDPOINT]

# The value that used to be accepted. If this ever works again, the hardcoded
# credential has come back.
RETIRED_SECRET = 'widen-import-2024'

EVIL_URL = 'https://evil.example/x.png'


def post_import(client, path, secret, style='3001'):
    return client.post(
        path,
        data=json.dumps({
            'secret': secret,
            'images': {style: {'Black': {'front': EVIL_URL, 'back': EVIL_URL}}},
        }),
        content_type='application/json',
    )


@pytest.fixture()
def no_secret(monkeypatch):
    monkeypatch.delenv('WIDEN_IMPORT_SECRET', raising=False)


@pytest.fixture()
def with_secret(monkeypatch):
    monkeypatch.setenv('WIDEN_IMPORT_SECRET', 'a-real-rotatable-secret')
    return 'a-real-rotatable-secret'


# ── The guard itself, independent of routing ─────────────────────────────────

def test_guard_refuses_everything_when_unset(no_secret):
    assert widen_import_auth.is_enabled() is False
    assert widen_import_auth.secret_matches('anything') is False
    assert widen_import_auth.secret_matches(RETIRED_SECRET) is False
    assert widen_import_auth.secret_matches('') is False
    assert widen_import_auth.secret_matches(None) is False


def test_guard_accepts_only_the_configured_value(with_secret):
    assert widen_import_auth.is_enabled() is True
    assert widen_import_auth.secret_matches(with_secret) is True
    assert widen_import_auth.secret_matches(with_secret + 'x') is False
    assert widen_import_auth.secret_matches(with_secret[:-1]) is False
    assert widen_import_auth.secret_matches(RETIRED_SECRET) is False


def test_guard_treats_whitespace_as_unset(monkeypatch):
    monkeypatch.setenv('WIDEN_IMPORT_SECRET', '   ')
    assert widen_import_auth.is_enabled() is False
    assert widen_import_auth.secret_matches('   ') is False


def test_guard_ignores_surrounding_whitespace_in_the_variable(monkeypatch):
    """A value pasted into a dashboard often picks up a stray newline."""
    monkeypatch.setenv('WIDEN_IMPORT_SECRET', '  padded-secret \n')
    assert widen_import_auth.secret_matches('padded-secret') is True


def test_guard_rejects_non_string_input(no_secret):
    """get_json can hand us anything at all."""
    for value in (0, 1, [], {}, True):
        assert widen_import_auth.secret_matches(value) is False


# ── Disabled unless explicitly configured ────────────────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_rejected_when_no_secret_is_configured(admin_client, no_secret, path):
    assert post_import(admin_client, path, 'anything').status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_empty_secret_does_not_authenticate(admin_client, no_secret, path):
    assert post_import(admin_client, path, '').status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_missing_secret_key_is_rejected(admin_client, no_secret, path):
    resp = admin_client.post(path, data=json.dumps({'images': {}}),
                             content_type='application/json')
    assert resp.status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_old_hardcoded_secret_no_longer_works(admin_client, no_secret, path):
    assert post_import(admin_client, path, RETIRED_SECRET).status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_old_secret_rejected_even_when_a_new_one_is_set(
        admin_client, with_secret, path):
    assert post_import(admin_client, path, RETIRED_SECRET).status_code == 403


def test_the_literal_secret_is_gone_from_the_source():
    """Rotating the value is pointless if the old one is still in the code."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for relative in ('app.py', os.path.join('routes', 'admin.py')):
        with open(os.path.join(root, relative),
                  encoding='utf-8', errors='replace') as handle:
            for number, line in enumerate(handle, 1):
                if RETIRED_SECRET in line:
                    offenders.append(f'{relative}:{number}')
    assert not offenders, f'hardcoded secret still present at {offenders}'


# ── A correct secret still works ────────────────────────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_correct_secret_is_accepted(admin_client, with_secret, path):
    """The import must still be usable, or this is a regression not a fix."""
    resp = post_import(admin_client, path, with_secret)
    assert resp.status_code == 200, resp.get_data(as_text=True)


@pytest.mark.parametrize('path', ENDPOINTS)
def test_a_wrong_secret_of_the_same_length_is_rejected(
        admin_client, with_secret, path):
    assert post_import(admin_client, path, 'a' * len(with_secret)).status_code == 403


# ── The unauthenticated endpoint ────────────────────────────────────────────

def test_open_endpoint_needs_no_session_but_needs_the_secret(guest, with_secret):
    """Its whole purpose is a cross-origin POST with no cookie.

    So it must work for an anonymous caller who has the secret, which is exactly
    why the secret has to be the real control.
    """
    assert post_import(guest, OPEN_ENDPOINT, with_secret).status_code == 200


def test_open_endpoint_refuses_an_anonymous_caller_without_the_secret(
        guest, no_secret):
    assert post_import(guest, OPEN_ENDPOINT, RETIRED_SECRET).status_code == 403


def test_csrf_also_guards_the_open_endpoint(app, guest, with_secret):
    """Defence in depth, and a caveat about what production actually allows.

    TestConfig disables CSRF, so every other test here reaches the secret check
    directly. In production CSRF is on and this route is in no exempted
    blueprint, so a tokenless cross-origin POST is refused before the secret is
    even read. Worth pinning down, because it means the route cannot currently
    be used for its stated purpose either — noted rather than "fixed", since
    exempting it would remove a layer of protection.
    """
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        resp = post_import(guest, OPEN_ENDPOINT, with_secret)
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    assert resp.status_code != 200
    assert resp.status_code in (400, 403)


def test_open_endpoint_exists_on_a_factory_built_app(app):
    """It used to be bolted onto the module-level app after create_app().

    Every app the factory built — every test, every script — therefore had no
    such route, which is why this file could not test it at all.
    """
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    assert OPEN_ENDPOINT in rules


def test_admin_endpoint_rejects_an_anonymous_caller(guest, with_secret):
    """The admin firewall answers before the secret is ever considered."""
    resp = post_import(guest, ADMIN_ENDPOINT, with_secret)
    assert resp.status_code in (302, 401, 403)
    assert resp.status_code != 200


def test_admin_endpoint_rejects_a_signed_in_non_admin(customer_client, with_secret):
    resp = post_import(customer_client, ADMIN_ENDPOINT, with_secret)
    assert resp.status_code != 200


# ── A refused call must not write ────────────────────────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_rejection_does_not_touch_the_database(admin_client, no_secret, path):
    def image_urls():
        with admin_client.application.app_context():
            product = Product.query.filter_by(style_number='3001').first()
            return {
                v.color_name: v.front_image_url
                for v in ProductColorVariant.query.filter_by(
                    product_id=product.id).all()
            }

    before = image_urls()
    post_import(admin_client, path, RETIRED_SECRET)
    after = image_urls()

    assert after == before
    assert not any((url or '').startswith('https://evil.example')
                   for url in after.values())


# ── Error responses must not describe the database ──────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_unauthorized_response_is_terse(admin_client, no_secret, path):
    """A refusal should say nothing about the schema behind it.

    Checked against the parsed JSON rather than the raw bytes: the site's own
    404 page contains the word "columns" in a layout comment, which made a naive
    substring scan of the body report a leak that was not there.
    """
    resp = post_import(admin_client, path, 'nope')
    assert resp.status_code == 403

    payload = resp.get_json(silent=True)
    assert payload == {'error': 'unauthorized'}, (
        f'unexpected refusal body: {resp.get_data(as_text=True)[:200]}'
    )
