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
    assert 'Black' in options
    assert 'Athletic Heather' in options
    assert 'White Black' in options
    assert 'Dtg Black' not in options
    assert 'TestColor' not in options
    assert 'athleticheather' not in options
