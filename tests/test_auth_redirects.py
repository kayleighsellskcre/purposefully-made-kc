"""Regression tests for preserving safe post-auth destinations."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlparse

from tests.conftest import CUSTOMER_EMAIL, PASSWORD


def _location_parts(response):
    return urlparse(response.headers["Location"])


def test_sign_in_returns_to_requested_group_order(client, seed):
    destination = "/shop/group-orders/create?mode=whole"
    response = client.post(
        "/auth/login?next=" + quote(destination, safe=""),
        data={"email": CUSTOMER_EMAIL, "password": PASSWORD},
    )

    location = _location_parts(response)
    assert response.status_code == 302
    assert location.path == "/shop/group-orders/create"
    assert location.query == "mode=whole"


def test_registration_returns_to_requested_group_order(client, seed):
    destination = "/shop/group-orders/create?mode=amount"
    response = client.post(
        "/auth/register?next=" + quote(destination, safe=""),
        data={
            "first_name": "New",
            "last_name": "Organizer",
            "email": "new-organizer@example.com",
            "phone": "",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )

    location = _location_parts(response)
    assert response.status_code == 302
    assert location.path == "/shop/group-orders/create"
    assert location.query == "mode=amount"


def test_external_post_auth_destination_is_rejected(client, seed):
    response = client.post(
        "/auth/login?next=https%3A%2F%2Fevil.example%2F",
        data={"email": CUSTOMER_EMAIL, "password": PASSWORD},
    )

    assert response.status_code == 302
    assert _location_parts(response).path == "/"


def test_failed_sign_in_keeps_the_requested_destination(client, seed):
    destination = "/shop/group-orders/create?mode=whole"
    response = client.post(
        "/auth/login?next=" + quote(destination, safe=""),
        data={"email": CUSTOMER_EMAIL, "password": "wrong-password"},
    )

    location = _location_parts(response)
    assert response.status_code == 302
    assert location.path == "/auth/login"
    assert location.query == "next=%2Fshop%2Fgroup-orders%2Fcreate%3Fmode%3Dwhole"


class _AuthPageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.form_actions = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.hrefs.append(attrs["href"])
        if tag == "form" and attrs.get("action"):
            self.form_actions.append(attrs["action"])


def test_sign_in_page_keeps_destination_in_form_and_create_account_link(client):
    destination = "/shop/group-orders/create?mode=whole"
    response = client.get("/auth/login", query_string={"next": destination})
    links = _AuthPageLinks()
    links.feed(response.get_data(as_text=True))

    register = next(urlparse(href) for href in links.hrefs if urlparse(href).path == "/auth/register")
    login_form = next(urlparse(action) for action in links.form_actions if urlparse(action).path == "/auth/login")
    assert parse_qs(register.query)["next"] == [destination]
    assert parse_qs(login_form.query)["next"] == [destination]
