"""Rate limits on the routes that send mail or check a credential.

TestConfig sets RATELIMIT_ENABLED = False so the rest of the suite is not
order-dependent, which also means nothing here is covered by default. These
tests switch the limiter on for the duration of one test and then put it back.

Two behaviours matter. Submissions are capped, so the public contact form
cannot be used as a relay into the owner's inbox and a password cannot be
guessed indefinitely. And merely *viewing* a form is never capped: every one of
these routes answers GET and POST from a single view, so a limit that counted
both would lock a customer out of a form they had not submitted.
"""
import pytest

from app import limiter


@pytest.fixture()
def limits_on(app):
    """Enable the limiter and clear any counts left by another test."""
    was_enabled = app.config.get('RATELIMIT_ENABLED')
    app.config['RATELIMIT_ENABLED'] = True
    limiter.enabled = True
    try:
        limiter.reset()
    except Exception:
        pass
    yield
    try:
        limiter.reset()
    except Exception:
        pass
    app.config['RATELIMIT_ENABLED'] = was_enabled
    limiter.enabled = bool(was_enabled)


def contact_post(client, n=1):
    last = None
    for i in range(n):
        last = client.post('/contact', data={
            'name': 'Spam Bot',
            'email': f'bot{i}@example.com',
            'subject': 'Hello',
            'message': 'Buy my thing',
        }, follow_redirects=False)
    return last


# ── Viewing a form is never limited ──────────────────────────────────────────

@pytest.mark.parametrize('path', [
    '/contact', '/auth/login', '/auth/register', '/auth/forgot-password',
])
def test_viewing_a_form_is_never_rate_limited(client, seed, limits_on, path):
    """The bug this guards: a bare limit counts GETs too.

    The tightest limit in play is 5 per hour, so fifteen views would trip it.
    """
    for _ in range(15):
        resp = client.get(path)
        assert resp.status_code != 429, f'GET {path} was rate limited'


# ── Submissions are limited ──────────────────────────────────────────────────

def test_contact_form_submissions_are_capped(client, seed, limits_on):
    """Five per hour, so the sixth POST is refused."""
    contact_post(client, 5)
    assert contact_post(client).status_code == 429


def test_contact_form_allows_a_reasonable_number_of_tries(client, seed, limits_on):
    """A customer who mistypes their address and resubmits must not be blocked."""
    for i in range(5):
        resp = contact_post(client)
        assert resp.status_code != 429, f'blocked on legitimate attempt {i + 1}'


def test_repeated_failed_logins_are_capped(client, seed, limits_on):
    """Ten per minute, so password guessing is not unbounded."""
    saw_429 = False
    for _ in range(12):
        resp = client.post('/auth/login', data={
            'email': 'customer-test@example.com',
            'password': 'wrong-password',
        })
        if resp.status_code == 429:
            saw_429 = True
            break
    assert saw_429, 'unlimited login attempts allowed'


def test_registration_is_capped(client, seed, limits_on):
    """Five per hour, so the account table cannot be filled by a script."""
    saw_429 = False
    for i in range(7):
        resp = client.post('/auth/register', data={
            'first_name': 'Bot', 'last_name': 'Account',
            'email': f'bot-signup-{i}@example.com',
            'password': 'TestPassw0rd!23',
            'confirm_password': 'TestPassw0rd!23',
        })
        if resp.status_code == 429:
            saw_429 = True
            break
    assert saw_429, 'unlimited registrations allowed'


def test_password_reset_requests_are_capped(client, seed, limits_on):
    """Otherwise this route floods a real inbox on demand."""
    saw_429 = False
    for _ in range(7):
        resp = client.post('/auth/forgot-password',
                           data={'email': 'customer-test@example.com'})
        if resp.status_code == 429:
            saw_429 = True
            break
    assert saw_429, 'unlimited password reset emails allowed'


# ── Limits are off by default in tests ───────────────────────────────────────

def test_limiter_is_disabled_for_the_rest_of_the_suite(client, seed):
    """Without this the other ~500 tests would start failing on run order."""
    for _ in range(8):
        assert contact_post(client).status_code != 429
