"""Quiet spam protection on the contact and recreate forms."""
import re
import time

import pytest

from utils import spam_guard


@pytest.fixture()
def strict(app):
    app.config['SPAM_GUARD_STRICT'] = True
    yield
    app.config['SPAM_GUARD_STRICT'] = False
    app.config['TURNSTILE_SITE_KEY'] = None
    app.config['TURNSTILE_SECRET_KEY'] = None


def _token(client):
    html = client.get('/contact').get_data(as_text=True)
    return re.search(r'name="form_started" value="([^"]+)"', html).group(1)


def _seen(monkeypatch):
    import utils.admin_notifications as notes
    box = []
    monkeypatch.setattr(notes, 'notify_contact_message', lambda name, email, subject, message: box.append(message))
    return box


def _post(client, token, **extra):
    data = {'name': 'Amy', 'email': 'amy@example.com', 'subject': 'Hello', 'message': 'Do you do hoodies?', 'form_started': token}
    data.update(extra)
    return client.post('/contact', data=data)


def test_contact_form_carries_a_signed_start_time_and_one_hidden_box(guest, strict):
    html = guest.get('/contact').get_data(as_text=True)
    assert 'name="form_started"' in html and html.count('name="website"') == 1 and 'cf-hp' in html


def test_a_real_visitor_gets_through(guest, strict, monkeypatch):
    box = _seen(monkeypatch)
    token = _token(guest)
    time.sleep(spam_guard.MIN_SECONDS + 0.2)
    assert _post(guest, token).status_code == 302
    assert box == ['Do you do hoodies?']


def test_a_form_sent_instantly_is_dropped_quietly(guest, strict, monkeypatch):
    box = _seen(monkeypatch)
    assert _post(guest, _token(guest)).status_code == 302
    assert box == []


def test_missing_token_filled_honeypot_and_link_spam_are_dropped(guest, strict, monkeypatch):
    box = _seen(monkeypatch)
    token = _token(guest)
    time.sleep(spam_guard.MIN_SECONDS + 0.2)
    _post(guest, '')                                                         # no token
    _post(guest, token, website='http://spam.example')                       # honeypot
    _post(guest, token, message='buy links http://a.example and https://b.example')   # two links
    assert box == []
    _post(guest, token, message='My idea is like https://example.com/pic')   # one link is fine
    assert len(box) == 1


def test_turnstile_is_off_without_keys_and_enforced_with_them(guest, app, strict, monkeypatch):
    box = _seen(monkeypatch)
    assert 'cf-turnstile' not in guest.get('/contact').get_data(as_text=True)
    app.config['TURNSTILE_SITE_KEY'] = 'site-key'
    app.config['TURNSTILE_SECRET_KEY'] = 'secret'
    page = guest.get('/contact').get_data(as_text=True)
    assert 'data-sitekey="site-key"' in page and 'challenges.cloudflare.com/turnstile' in page
    token = re.search(r'name="form_started" value="([^"]+)"', page).group(1)
    time.sleep(spam_guard.MIN_SECONDS + 0.2)
    import requests

    class Resp:
        def __init__(self, ok):
            self.ok = ok

        def json(self):
            return {'success': self.ok}
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: Resp(False))
    _post(guest, token, **{'cf-turnstile-response': 'bad'})
    assert box == []
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: Resp(True))
    _post(guest, token, **{'cf-turnstile-response': 'good'})
    assert len(box) == 1


def test_recreate_form_has_the_same_guard(login, app, seed, strict):
    from tests.conftest import CUSTOMER_EMAIL
    client = app.test_client()
    login(client, CUSTOMER_EMAIL)
    html = client.get('/custom-design/submit').get_data(as_text=True)
    assert 'name="form_started"' in html and 'name="website"' in html


def test_404_heading_has_its_space(guest):
    html = guest.get('/no-such-page-anywhere').get_data(as_text=True)
    assert 'This Page Has <br>Wandered Off' in html
