"""Customizer layout: swatches, multi-size grid, design tabs, order bar, heart and size guide."""


def _page(client, seed):
    resp = client.get(f'/shop/customize/{seed["tee_slug"]}')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_colors_are_round_swatches_with_names(guest, seed):
    html = _page(guest, seed)
    assert 'class="color-dot"' in html
    assert 'title="Black"' in html and 'aria-label="Black"' in html
    assert '<h3>Color</h3>' in html
    assert 'Select your color.' not in html


def test_color_search_and_filters_only_show_with_many_colors(guest, seed):
    html = _page(guest, seed)
    many = html.count('class="color-card"') > 20
    search = html.split('class="color-search-box"')[1].split('>')[0]
    tabs = html.split('aria-label="Filter colors by family"')[1].split('>')[0]
    assert (' hidden' not in search) == many
    assert (' hidden' not in tabs) == many


def test_sizes_step_is_a_multi_size_grid_in_the_regular_shop(guest, seed):
    html = _page(guest, seed)
    assert 'Sizes and quantities' in html
    assert html.count('class="size-qty"') >= 5
    assert 'Pick a color first to see availability' not in html
    assert 'const MULTI_SIZE = true;' in html
    # the separate Quantity step is gone from view (the input stays for older code)
    assert '<div class="panel-section" hidden>\n                    <h3>Quantity</h3>' in html.replace('\r\n', '\n')


def test_order_bar_holds_total_button_and_shipping_note(guest, seed):
    html = _page(guest, seed)
    bar = html.split('id="orderBar"')[1]
    assert 'id="totalPrice"' in bar and 'id="addToCart"' in bar
    assert 'Shipping is $11.' in bar and 'Pickup is available at checkout.' in bar and 'Estimated ready by' in bar


def test_design_step_has_upload_and_gallery_tabs(guest, seed):
    html = _page(guest, seed)
    assert 'id="designPaneTabs"' in html and 'data-pane="upload"' in html
    assert 'By uploading, you let us add it to our design gallery.' in html


def test_heart_and_size_guide_link(guest, seed):
    html = _page(guest, seed)
    assert 'class="title-heart"' in html and 'js/product-heart.js' in html
    assert 'href="/size-guide"' in html
    detail = guest.get(f'/shop/product/{seed["tee_slug"]}').get_data(as_text=True)
    assert 'class="title-heart"' in detail and 'Not sure of your size?' in detail
