"""Admin and Log Out stay nested under My Account.

The public header should read Shop, Gallery, Group Orders, Recreate, About,
Contact, and My Account. Admin and Log Out belong in the account menu, not
as extra top-level links.
"""
import re

from conftest import ADMIN_EMAIL, CUSTOMER_EMAIL


def _account_menu(html):
    match = re.search(r'<div class="nav-account-menu"[^>]*id="navAccountMenu".*?</div>', html, re.S)
    assert match, 'My Account dropdown is missing from the header'
    return match.group(0)


def test_a_signed_in_customer_does_not_see_admin_in_the_header(client, login):
    login(client, CUSTOMER_EMAIL)
    html = client.get('/shop/').get_data(as_text=True)
    assert 'Admin Dashboard' not in html
    menu = _account_menu(html)
    assert 'Log Out' in menu


def test_the_public_header_nests_admin_and_log_out_inside_my_account(client, login):
    login(client, ADMIN_EMAIL)
    html = client.get('/shop/').get_data(as_text=True)
    assert 'id="navAccountBtn"' in html
    assert 'nav-user-link nav-logout-link' not in html
    assert '>Admin</a>' not in html
    menu = _account_menu(html)
    assert 'Admin Dashboard' in menu
    assert 'Log Out' in menu


def test_admin_dashboard_lives_inside_my_account(client, login):
    login(client, ADMIN_EMAIL)
    html = client.get('/account/orders').get_data(as_text=True)
    assert 'Admin Dashboard' in html
    assert '/admin/' in html


def test_a_customer_account_page_has_no_admin_dashboard(client, login):
    login(client, CUSTOMER_EMAIL)
    html = client.get('/account/orders').get_data(as_text=True)
    assert 'Admin Dashboard' not in html
