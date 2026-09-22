"""Round 2 audit item 10: the "You're ordering for X" banner used to render
on every page once a visitor merely opened a group store, because the
session flag behind it only cleared on "Back to main site". It should only
show on the store's own pages and the customize/product pages reached from
it, not on unrelated pages like the shop or the design gallery.
"""

BANNER_TEXT = "You're ordering for"


def test_banner_shows_on_the_stores_own_page(client, seed):
    html = client.get(f'/c/{seed["collection_slug"]}').get_data(as_text=True)
    assert BANNER_TEXT in html


def test_banner_shows_on_a_customize_page_reached_from_the_store(client, seed):
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert BANNER_TEXT in html


def test_banner_shows_on_a_product_detail_page_reached_from_the_store(client, seed):
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    assert BANNER_TEXT in html


def test_banner_does_not_leak_onto_the_shop_page(client, seed):
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get('/shop/').get_data(as_text=True)
    assert BANNER_TEXT not in html


def test_banner_does_not_leak_onto_the_design_gallery(client, seed):
    client.get(f'/c/{seed["collection_slug"]}')
    resp = client.get('/shop/designs')
    assert resp.status_code == 200
    assert BANNER_TEXT not in resp.get_data(as_text=True)


def test_banner_does_not_leak_onto_the_homepage(client, seed):
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get('/').get_data(as_text=True)
    assert BANNER_TEXT not in html


def test_banner_still_shows_on_cart_so_continue_shopping_returns_to_the_store(client, seed):
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get('/cart/').get_data(as_text=True)
    assert BANNER_TEXT in html
    assert f'/c/{seed["collection_slug"]}' in html


def test_back_to_main_site_still_clears_the_customize_page_too(client, seed):
    client.get(f'/c/{seed["collection_slug"]}')
    client.get('/c/leave?next=/', follow_redirects=False)
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert BANNER_TEXT not in html
