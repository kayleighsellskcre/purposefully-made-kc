"""Round 2 audit item 1: /status and /version must not be public.

Logged-out visitors get a 404 (not a login redirect, so the routes don't
advertise themselves). Logged-in non-admins get a 403. Admins still see them,
and the status page never prints the admin's actual email address.
"""
from conftest import ADMIN_EMAIL, CUSTOMER_EMAIL


def test_status_is_404_for_a_guest(guest):
    resp = guest.get('/status')
    assert resp.status_code == 404


def test_version_is_404_for_a_guest(guest):
    resp = guest.get('/version')
    assert resp.status_code == 404


def test_status_is_403_for_a_signed_in_customer(client, login):
    login(client, CUSTOMER_EMAIL)
    resp = client.get('/status')
    assert resp.status_code == 403


def test_version_is_403_for_a_signed_in_customer(client, login):
    login(client, CUSTOMER_EMAIL)
    resp = client.get('/version')
    assert resp.status_code == 403


def test_status_still_works_for_the_admin(client, login):
    login(client, ADMIN_EMAIL)
    resp = client.get('/status')
    assert resp.status_code == 200
    assert ADMIN_EMAIL.encode() not in resp.data


def test_version_still_works_for_the_admin(client, login):
    login(client, ADMIN_EMAIL)
    resp = client.get('/version')
    assert resp.status_code == 200
    assert resp.is_json


def test_robots_txt_no_longer_lists_status_or_version(guest):
    resp = guest.get('/robots.txt')
    body = resp.data.decode()
    assert '/status' not in body
    assert '/version' not in body
