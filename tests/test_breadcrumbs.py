"""Shoppers landing on a product or customize page need a way back."""


def _assert_home_shop_product_trail(html):
    assert 'aria-label="Breadcrumb"' in html
    assert 'Home' in html
    assert 'href="/"' in html
    assert 'href="/shop/"' in html
    assert 'Unisex Jersey Short Sleeve Tee' in html
    assert 'aria-current="page"' in html


def test_customize_has_a_home_shop_product_trail(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    _assert_home_shop_product_trail(html)


def test_product_detail_has_a_home_shop_product_trail(client, seed):
    html = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    _assert_home_shop_product_trail(html)
