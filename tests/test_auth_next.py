"""Starting a group order, then signing in or creating an account, lands back on the chosen setup."""
import re
from html import unescape
from urllib.parse import parse_qs, urlparse

from models import User
from tests.conftest import CUSTOMER_EMAIL, PASSWORD

WHOLE = '/shop/group-orders/create?mode=whole'


def next_of(url):
    """The decoded ?next= of an address, or ''."""
    return parse_qs(urlparse(url).query).get('next', [''])[0]


def go(path, target=WHOLE):
    """A sign-in or create-account address that remembers the destination."""
    from urllib.parse import quote
    return f'{path}?next={quote(target, safe="")}'


def nexts_in(html, path):
    """Every decoded destination found in links and form actions that point at one auth page."""
    found = re.findall(rf'(?:href|action)="({re.escape(path)}\?[^"]*)"', html)
    return {next_of(unescape(u)) for u in found}


def test_each_start_button_sends_a_visitor_to_sign_in_with_their_choice_kept(guest):
    html = guest.get('/shop/group-orders').get_data(as_text=True)
    assert nexts_in(html, '/auth/login') >= {'/shop/group-orders/create', '/shop/group-orders/create?mode=whole',
                                              '/shop/group-orders/create?mode=amount'}


def test_the_sign_in_page_carries_the_choice_in_its_form_and_its_create_account_link(guest):
    html = guest.get(go('/auth/login')).get_data(as_text=True)
    assert f'name="next" value="{WHOLE}"' in html
    assert nexts_in(html, '/auth/login') == {WHOLE}                 # the form posts back with it
    assert nexts_in(html, '/auth/register') == {WHOLE}              # and so does "Create an Account"


def test_the_create_account_page_carries_it_too_including_the_link_back_to_sign_in(guest):
    html = guest.get(go('/auth/register')).get_data(as_text=True)
    assert f'name="next" value="{WHOLE}"' in html
    assert nexts_in(html, '/auth/register') == {WHOLE}
    assert nexts_in(html, '/auth/login') == {WHOLE}


def test_the_pages_are_unchanged_when_there_is_no_choice(guest):
    for path in ('/auth/login', '/auth/register'):
        html = guest.get(path).get_data(as_text=True)
        assert 'name="next"' not in html and '?next=' not in html


def test_signing_in_returns_to_the_chosen_setup(guest, seed):
    resp = guest.post(go('/auth/login'), data={'email': CUSTOMER_EMAIL, 'password': PASSWORD, 'next': WHOLE})
    assert resp.status_code == 302 and resp.headers['Location'] == WHOLE
    assert 'value="organizer_pays" checked' in guest.get(WHOLE).get_data(as_text=True)


def test_the_choice_survives_a_wrong_password(guest, seed):
    for data in ({'email': CUSTOMER_EMAIL, 'password': 'wrong-password'}, {'email': 'nobody@example.com', 'password': 'x'}):
        resp = guest.post('/auth/login', data={**data, 'next': WHOLE})
        assert resp.status_code == 302 and resp.headers['Location'].startswith('/auth/login')
        assert next_of(resp.headers['Location']) == WHOLE
    resp = guest.post(go('/auth/login'), data={'email': CUSTOMER_EMAIL, 'password': PASSWORD})
    assert resp.headers['Location'] == WHOLE


def test_creating_an_account_returns_to_the_chosen_setup(guest, seed, app):
    resp = guest.post(go('/auth/register'), data={
        'email': 'new.organizer@example.com', 'password': 'LongEnough1!', 'confirm_password': 'LongEnough1!',
        'first_name': 'New', 'last_name': 'Organizer', 'next': WHOLE})
    assert resp.status_code == 302 and resp.headers['Location'] == WHOLE
    with app.app_context():
        assert User.query.filter_by(email='new.organizer@example.com').first() is not None


def test_the_choice_survives_a_registration_mistake(guest, seed):
    for data in ({'email': 'bad', 'password': 'LongEnough1!', 'confirm_password': 'LongEnough1!'},
                 {'email': 'ok@example.com', 'password': 'LongEnough1!', 'confirm_password': 'different'},
                 {'email': 'ok@example.com', 'password': 'short', 'confirm_password': 'short'},
                 {'email': CUSTOMER_EMAIL, 'password': 'LongEnough1!', 'confirm_password': 'LongEnough1!'}):
        resp = guest.post('/auth/register', data={**data, 'first_name': 'A', 'last_name': 'B', 'next': WHOLE})
        assert resp.status_code == 302 and resp.headers['Location'].startswith('/auth/register'), data
        assert next_of(resp.headers['Location']) == WHOLE, data


def test_without_a_choice_nothing_changes(guest, seed):
    assert guest.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': PASSWORD}).headers['Location'].endswith('/')
    guest.get('/auth/logout')
    assert guest.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': 'wrong'}).headers['Location'] == '/auth/login'


def test_a_signed_in_person_opening_sign_in_goes_straight_to_their_choice(guest, seed):
    guest.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': PASSWORD})
    assert guest.get(go('/auth/login')).headers['Location'] == WHOLE
    assert guest.get(go('/auth/register')).headers['Location'] == WHOLE


def test_only_pages_on_this_site_are_ever_used_as_the_destination(guest, seed):
    for evil in ('https://evil.example.com/x', '//evil.example.com', 'javascript:alert(1)', '/\\evil.example.com',
                 'evil.example.com', '/ok\nSet-Cookie: x=1'):
        resp = guest.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': PASSWORD, 'next': evil})
        assert resp.status_code == 302 and 'evil' not in resp.headers['Location'], evil
        assert resp.headers['Location'].endswith('/'), evil
        guest.get('/auth/logout')
    html = guest.get(go('/auth/login', 'https://evil.example.com')).get_data(as_text=True)
    assert 'evil.example.com' not in html


def test_the_company_apparel_sign_in_button_keeps_its_destination_too(guest):
    html = guest.get('/shop/company-apparel').get_data(as_text=True)
    assert '/shop/group-orders/create?mode=company' in nexts_in(html, '/auth/login')
