"""The shop filter panel that collapses on phones.

Six stacked dropdowns pushed the first product more than a screen below the
fold on a 390px viewport, so they now sit behind a "Filter Products" button
that CSS only reveals under 768px.

The part worth guarding here is the server-rendered state. If someone follows a
filtered link — the footer's "T-Shirts" entry, say — and the panel renders
collapsed, they land on a shortened list of products with nothing on screen
explaining why. So the panel must start open exactly when a filter is active,
and the same flag has to drive both that and the "Clear Filters" button, or the
two can contradict each other.

What these tests cannot cover is the CSS that does the hiding and the click
handler that toggles it; those need a real browser.
"""

import re

SHOP = '/shop/'


def html_of(client, url=SHOP):
    resp = client.get(url)
    assert resp.status_code == 200, f'{url} returned {resp.status_code}'
    return resp.get_data(as_text=True)


def toggle_tag(html):
    """The opening <button ...> tag of the filter toggle."""
    match = re.search(r'<button[^>]*id="filterToggle"[^>]*>', html)
    assert match, 'filter toggle button is missing from the shop page'
    return match.group(0)


def controls_tag(html):
    match = re.search(r'<div[^>]*id="filterControls"[^>]*>', html)
    assert match, 'filter controls container is missing from the shop page'
    return match.group(0)


# ── Unfiltered: collapsed ────────────────────────────────────────────────────

def test_toggle_button_is_rendered(client):
    assert 'Filter Products' in html_of(client)


def test_panel_starts_collapsed_with_no_filters(client):
    html = html_of(client)
    assert 'open' not in controls_tag(html), (
        f'panel starts open with no filters applied: {controls_tag(html)}'
    )
    assert 'aria-expanded="false"' in toggle_tag(html)


# ── Filtered: starts open, so the customer can see why ──────────────────────

def test_panel_starts_open_when_a_dropdown_filter_is_active(client):
    html = html_of(client, '/shop/?category=Tee')
    assert 'open' in controls_tag(html), (
        'a filtered link renders the panel collapsed, hiding the reason the '
        'product list is short'
    )
    assert 'aria-expanded="true"' in toggle_tag(html)


def test_panel_starts_open_when_a_search_is_active(client):
    html = html_of(client, '/shop/?q=tee')
    assert 'open' in controls_tag(html)
    assert 'aria-expanded="true"' in toggle_tag(html)


def test_clear_filters_and_open_state_agree(client):
    """Both are driven by one flag, so they must never disagree."""
    for url in (SHOP, '/shop/?category=Tee', '/shop/?q=tee', '/shop/?color=Black'):
        html = html_of(client, url)
        panel_open = 'open' in controls_tag(html)
        # The attribute, not the bare call: "function clearFilters()" is always
        # present in the page script, so a looser check would never fail.
        offers_clear = 'onclick="clearFilters()"' in html
        assert panel_open == offers_clear, (
            f'{url}: panel open={panel_open} but clear-filters shown='
            f'{offers_clear}'
        )


# ── Wiring the button needs to actually have ────────────────────────────────

def test_toggle_is_wired_to_the_panel_it_controls(client):
    html = html_of(client)
    assert 'aria-controls="filterControls"' in toggle_tag(html)
    assert 'toggleShopFilters()' in toggle_tag(html)
    assert 'function toggleShopFilters' in html, (
        'the button calls a handler the page never defines'
    )


def test_toggle_is_a_real_button(client):
    """A styled div would not be keyboard reachable."""
    assert toggle_tag(html_of(client)).startswith('<button')


def test_toggle_comes_before_the_controls_it_reveals(client):
    html = html_of(client)
    assert html.index('id="filterToggle"') < html.index('id="filterControls"'), (
        'the toggle renders after the panel, so tab order and reading order '
        'would put the control after the thing it controls'
    )


# ── The search box stays out of the collapse ────────────────────────────────

def test_search_stays_outside_the_collapsed_panel(client):
    """Search is the fastest way to find something on a phone.

    It is one row, so it stays visible while the six dropdowns hide.
    """
    html = html_of(client)
    search_at = html.index('id="shopSearchInput"')
    panel_at = html.index('id="filterControls"')
    assert search_at < panel_at, 'the search box was moved inside the collapse'


# ── Products still render ───────────────────────────────────────────────────

def test_products_still_render(client):
    """Guards against the markup edits breaking the catalogue loop."""
    assert 'product-card' in html_of(client)


def _select_options(html, select_id):
    block = re.search(
        rf'<select[^>]*id="{select_id}"[^>]*>(.*?)</select>',
        html,
        flags=re.DOTALL,
    )
    assert block, f'{select_id} is missing'
    return re.findall(r'<option value="([^"]*)"', block.group(1))


def test_category_filter_omits_empty_styles(client):
    options = _select_options(html_of(client), 'categoryFilter')
    assert 'Tee' in options
    assert 'Hoodie' in options
    for empty in ('Pants', 'Shorts', 'Baseball Tee'):
        assert empty not in options, empty


def test_brand_filter_omits_unsold_brands(client):
    options = _select_options(html_of(client), 'brandFilter')
    assert 'Bella+Canvas' in options or options == ['']
    for empty in ('Gildan', 'Sport-Tek', 'Stanley/Stella', 'C2 Sport'):
        assert empty not in options, empty


def test_age_filter_omits_empty_age_groups(client):
    options = _select_options(html_of(client), 'ageGroupFilter')
    assert 'adult' in options
    assert 'youth' in options
    assert 'toddler' not in options
    assert 'baby' not in options


def test_color_filter_normalizes_names_and_drops_test_values(client, app, seed):
    import json
    from models import ProductColorVariant, db

    stocked = json.dumps({'S': 5, 'M': 5, 'L': 5})
    with app.app_context():
        db.session.add_all([
            ProductColorVariant(
                product_id=seed['tee_id'], color_name='Dtg Black',
                size_inventory=stocked,
            ),
            ProductColorVariant(
                product_id=seed['tee_id'], color_name='athleticheather',
                size_inventory=stocked,
            ),
            ProductColorVariant(
                product_id=seed['tee_id'], color_name='TestColor',
                size_inventory=stocked,
            ),
            ProductColorVariant(
                product_id=seed['tee_id'], color_name='White_Black',
                size_inventory=stocked,
            ),
        ])
        db.session.commit()

    options = _select_options(html_of(client), 'colorFilter')
    assert 'Blacks and Grays' in options
    assert 'Whites and Creams' in options
    assert 'Dtg Black' not in options
    assert 'TestColor' not in options
    assert 'athleticheather' not in options


# ── Color filter: families with swatches, not 400 individual shades ────────

def test_color_filter_offers_families_instead_of_every_shade(client, app, seed):
    import json
    from models import ProductColorVariant, db

    stocked = json.dumps({'S': 5, 'M': 5, 'L': 5})
    with app.app_context():
        db.session.add_all([
            ProductColorVariant(product_id=seed['tee_id'], color_name='Navy', size_inventory=stocked),
            ProductColorVariant(product_id=seed['tee_id'], color_name='Forest Green', size_inventory=stocked),
        ])
        db.session.commit()

    html = html_of(client)
    select_html = re.search(r'<select id="colorFilter".*?</select>', html, re.S).group(0)
    assert 'optgroup' not in select_html
    assert 'color-family-swatches' in html
    assert 'data-family="Blues"' in html
    assert 'data-family="Greens"' in html
    assert '<option value="Blues"' in select_html
    assert '<option value="Greens"' in select_html
    assert '<option value="Navy"' not in select_html
    assert '<option value="Forest Green"' not in select_html


def test_filtering_by_a_grouped_color_value_still_works(client, app, seed):
    import json
    from models import ProductColorVariant, db

    stocked = json.dumps({'S': 5, 'M': 5, 'L': 5})
    with app.app_context():
        db.session.add(ProductColorVariant(
            product_id=seed['hoodie_id'], color_name='Forest Green', size_inventory=stocked,
        ))
        db.session.commit()

    resp = client.get('/shop/?color=Forest+Green')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Heavy Blend Hooded Sweatshirt' in body
    assert 'Unisex Jersey Short Sleeve Tee' not in body


def _carousel_colors_for(body, product_id):
    start = body.index(f'<div class="color-carousel" data-product-id="{product_id}"')
    depth = 0
    pos = start
    tag_re = re.compile(r'<div\b|</div>')
    for match in tag_re.finditer(body, start):
        depth += -1 if match.group(0).startswith('</div') else 1
        pos = match.end()
        if depth == 0:
            break
    return re.findall(r'data-color="([^"]*)"', body[start:pos])


def test_filtering_by_a_color_family_includes_every_shade_in_it(client, app, seed):
    import json
    from models import ProductColorVariant, db

    stocked = json.dumps({'S': 5, 'M': 5, 'L': 5})
    with app.app_context():
        db.session.add(ProductColorVariant(
            product_id=seed['hoodie_id'], color_name='Forest Green', size_inventory=stocked,
        ))
        db.session.commit()

    resp = client.get('/shop/?color=Greens')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Heavy Blend Hooded Sweatshirt' in body
    assert 'Unisex Jersey Short Sleeve Tee' not in body


def test_selected_color_swatches_mark_aria_pressed(client, seed):
    html = html_of(client, '/shop/?color=Blacks+and+Grays&color=Whites+and+Creams')
    blacks = re.search(r'<button[^>]*data-family="Blacks and Grays"[^>]*>', html).group(0)
    whites = re.search(r'<button[^>]*data-family="Whites and Creams"[^>]*>', html).group(0)
    assert 'aria-pressed="true"' in blacks
    assert 'aria-pressed="true"' in whites
    assert 'is-selected' in blacks
    assert 'is-selected' in whites


def test_color_filter_limits_each_card_carousel_to_that_family(client, seed):
    body = html_of(client, '/shop/?color=Blacks+and+Grays')
    colors = _carousel_colors_for(body, seed['tee_id'])
    assert colors
    assert 'Black' in colors
    assert 'White' not in colors


def test_two_color_families_keep_both_in_the_carousel(client, app, seed):
    import json
    from models import ProductColorVariant, db

    stocked = json.dumps({'S': 5, 'M': 5, 'L': 5})
    with app.app_context():
        db.session.add(ProductColorVariant(
            product_id=seed['tee_id'], color_name='Forest Green',
            front_image_url='/static/img/logo.png',
            size_inventory=stocked,
        ))
        db.session.commit()

    body = html_of(client, '/shop/?color=Greens&color=Whites+and+Creams')
    colors = _carousel_colors_for(body, seed['tee_id'])
    assert 'Forest Green' in colors
    assert 'White' in colors
    assert 'Black' not in colors
    assert 'data-family="Greens"' in body
    assert 'data-family="Whites and Creams"' in body


def test_two_color_families_keep_products_from_either(client, app, seed):
    import json
    from models import ProductColorVariant, db

    stocked = json.dumps({'S': 5, 'M': 5, 'L': 5})
    with app.app_context():
        db.session.add(ProductColorVariant(
            product_id=seed['hoodie_id'], color_name='Forest Green',
            front_image_url='/static/img/logo.png',
            size_inventory=stocked,
        ))
        db.session.commit()

    body = html_of(client, '/shop/?color=Greens&color=Whites+and+Creams')
    assert 'Heavy Blend Hooded Sweatshirt' in body
    assert 'Unisex Jersey Short Sleeve Tee' in body
    hoodie_colors = _carousel_colors_for(body, seed['hoodie_id'])
    assert hoodie_colors == ['Forest Green']


def test_kids_age_filter_includes_baby_toddler_and_youth():
    from types import SimpleNamespace

    from utils.product_filters import matches_filters

    baby = SimpleNamespace(
        age_group='baby', name='Infant Tee', category='Tee', style_number='BC3001B',
    )
    youth = SimpleNamespace(
        age_group='youth', name='Youth Tee', category='Tee', style_number='BC3001Y',
    )
    toddler = SimpleNamespace(
        age_group='toddler', name='Toddler Tee', category='Tee', style_number='BC3001T',
    )
    adult = SimpleNamespace(
        age_group='adult', name='Adult Tee', category='Tee', style_number='BC3001',
    )
    assert matches_filters(baby, age_group='kids')
    assert matches_filters(youth, age_group='kids')
    assert matches_filters(toddler, age_group='kids')
    assert not matches_filters(adult, age_group='kids')
    assert matches_filters(baby, age_group='baby')
    assert not matches_filters(youth, age_group='baby')


def test_footer_baby_and_kids_link_uses_the_combined_filter(client, seed):
    html = html_of(client, '/')
    assert 'age_group=kids' in html
    assert "age_group=Baby'" not in html
