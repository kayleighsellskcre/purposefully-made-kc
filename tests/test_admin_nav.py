"""Admin stays out of the public nav and lives inside My Account.

Customers never saw the Admin link (it was gated), but it still sat in the
main header next to Shop and Contact whenever the owner was signed in. That
reads like a leftover backend control on a customer storefront.
"""
from conftest import ADMIN_EMAIL, CUSTOMER_EMAIL


def test_a_signed_in_customer_does_not_see_admin_in_the_header(client, login):
    login(client, CUSTOMER_EMAIL)
    html = client.get('/shop/').get_data(as_text=True)
    assert 'admin-link' not in html
    assert 'Admin Dashboard' not in html


def test_the_public_header_hides_admin_even_for_the_owner(client, login):
    login(client, ADMIN_EMAIL)
    html = client.get('/shop/').get_data(as_text=True)
    assert 'nav-user-link admin-link' not in html
    assert 'nav-link admin-link' not in html
    assert '>Admin</a>' not in html


def test_admin_dashboard_lives_inside_my_account(client, login):
    login(client, ADMIN_EMAIL)
    html = client.get('/account/orders').get_data(as_text=True)
    assert 'Admin Dashboard' in html
    assert '/admin/' in html


def test_a_customer_account_page_has_no_admin_dashboard(client, login):
    login(client, CUSTOMER_EMAIL)
    html = client.get('/account/orders').get_data(as_text=True)
    assert 'Admin Dashboard' not in html
