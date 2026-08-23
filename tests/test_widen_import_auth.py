"""The Widen bulk image-import endpoints must fail closed.

`POST /widen-import` and `POST /admin/import-widen` upsert image URLs for every
product. Both skip the login session on purpose so the import can be posted
cross-origin from medialibrary1.com, and both answer with
`Access-Control-Allow-Origin: *`. A shared secret is therefore the only control
on a route that can repoint every product image on the storefront.

That secret used to be the literal string 'widen-import-2024', written into
app.py and routes/admin.py. It was readable by anyone who could read the
repository and could not be rotated without a deploy. It now comes from
WIDEN_IMPORT_SECRET, with no default, so the endpoints are inert unless an
import is deliberately being run.
"""
import json

import pytest

from models import db, Product, ProductColorVariant

ENDPOINTS = ['/widen-import', '/admin/import-widen']

# The value that used to be accepted. If this ever works again, the hardcoded
# credential has come back.
RETIRED_SECRET = 'widen-import-2024'


def post_import(client, path, secret, style='3001'):
    return client.post(
        path,
        data=json.dumps({
            'secret': secret,
            'images': {
                style: {'Black': {'front': 'https://evil.example/x.png',
                                  'back': 'https://evil.example/y.png'}},
            },
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


# ── Disabled unless explicitly configured ────────────────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_rejected_when_no_secret_is_configured(client, seed, no_secret, path):
    """With the variable unset there is no way in, whatever is sent."""
    assert post_import(client, path, 'anything').status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_empty_secret_does_not_authenticate(client, seed, no_secret, path):
    """An absent secret must not match an absent configuration."""
    assert post_import(client, path, '').status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_missing_secret_key_is_rejected(client, seed, no_secret, path):
    resp = client.post(path, data=json.dumps({'images': {}}),
                       content_type='application/json')
    assert resp.status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_blank_configured_secret_still_refuses(client, seed, monkeypatch, path):
    """Whitespace is not a credential."""
    monkeypatch.setenv('WIDEN_IMPORT_SECRET', '   ')
    assert post_import(client, path, '   ').status_code == 403


# ── The retired hardcoded credential ────────────────────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_old_hardcoded_secret_no_longer_works(client, seed, no_secret, path):
    assert post_import(client, path, RETIRED_SECRET).status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_old_secret_rejected_even_when_a_new_one_is_set(
        client, seed, with_secret, path):
    assert post_import(client, path, RETIRED_SECRET).status_code == 403


def test_the_literal_secret_is_gone_from_the_source():
    """Rotating the value is pointless if the old one is still in the code."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for relative in ('app.py', os.path.join('routes', 'admin.py')):
        path = os.path.join(root, relative)
        with open(path, encoding='utf-8', errors='replace') as handle:
            for number, line in enumerate(handle, 1):
                # Skip the comment in the test-facing docstring that names it.
                if RETIRED_SECRET in line and 'WIDEN_IMPORT_SECRET' not in line:
                    offenders.append(f'{relative}:{number}')
    assert not offenders, f'hardcoded secret still present at {offenders}'


# ── A correct secret still works ────────────────────────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_correct_secret_is_accepted(client, seed, with_secret, path):
    """The import must still be usable, or this is a regression not a fix."""
    resp = post_import(client, path, with_secret)
    assert resp.status_code == 200, resp.get_data(as_text=True)


@pytest.mark.parametrize('path', ENDPOINTS)
def test_a_wrong_secret_of_the_same_length_is_rejected(
        client, seed, with_secret, path):
    wrong = 'a' * len(with_secret)
    assert post_import(client, path, wrong).status_code == 403


@pytest.mark.parametrize('path', ENDPOINTS)
def test_rejection_does_not_touch_the_database(client, seed, no_secret, path):
    """A refused call must not have written anything on its way out."""
    with client.application.app_context():
        product = Product.query.filter_by(style_number='3001').first()
        before = {
            v.color_name: v.front_image_url
            for v in ProductColorVariant.query.filter_by(
                product_id=product.id).all()
        }

    post_import(client, path, RETIRED_SECRET)

    with client.application.app_context():
        product = Product.query.filter_by(style_number='3001').first()
        after = {
            v.color_name: v.front_image_url
            for v in ProductColorVariant.query.filter_by(
                product_id=product.id).all()
        }
    assert after == before
    assert not any(
        (url or '').startswith('https://evil.example') for url in after.values()
    )


# ── Error responses must not describe the database ──────────────────────────

@pytest.mark.parametrize('path', ENDPOINTS)
def test_unauthorized_response_is_terse(client, seed, no_secret, path):
    """A 403 to an anonymous cross-origin caller should say nothing useful."""
    body = post_import(client, path, 'nope').get_data(as_text=True).lower()
    for leak in ('traceback', 'sqlalchemy', 'psycopg2', 'select ', 'column'):
        assert leak not in body, f'403 body mentions {leak!r}'
