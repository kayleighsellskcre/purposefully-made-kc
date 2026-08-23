"""Accessibility guarantees for the customer-facing pages.

These cover the things that actually stopped people using the site rather than
everything an automated checker can flag:

- A keyboard user had to tab through eleven navigation links on every page
  before reaching the content, because there was no skip link.
- The customizer's colour, size and placement choices were <div onclick>, which
  cannot be reached by Tab or activated by Enter. A customer navigating by
  keyboard could not choose a colour, and so could not buy anything.
- The flash container was only rendered when a message already existed, so
  "Added to cart" and upload errors were inserted into a region that did not
  exist yet and were never announced.
- Search fields and quantity inputs had a placeholder but no label.

Parsing is done with the standard library so the test suite needs no extra
dependency.
"""
from html.parser import HTMLParser

import pytest

VOID_ELEMENTS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
}

HEADINGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')


class Page(HTMLParser):
    """A minimal DOM: enough to ask about labels, landmarks and headings."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []          # [(tag, {attrs}), ...] in document order
        self.headings = []      # ['h1', 'h3', ...] in document order
        self.ids = set()
        self.label_targets = set()   # every <label for="..."> value
        self._text_stack = []
        self.text_by_index = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = {k: (v if v is not None else '') for k, v in attrs}
        self.tags.append((tag, attributes))
        if 'id' in attributes:
            self.ids.add(attributes['id'])
        if tag == 'label' and attributes.get('for'):
            self.label_targets.add(attributes['for'])
        if tag in HEADINGS:
            self.headings.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def find(self, tag, **conditions):
        """Every `tag` whose attributes match all the given conditions."""
        found = []
        for name, attributes in self.tags:
            if name != tag:
                continue
            if all(attributes.get(k) == v for k, v in conditions.items()):
                found.append(attributes)
        return found

    def all_of(self, *tags):
        return [(n, a) for n, a in self.tags if n in tags]


def parse(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f'{path} returned {resp.status_code}'
    return Page(resp.get_data(as_text=True))


PUBLIC_PAGES = [
    '/',
    '/shop/',
    '/shop/designs',
    '/shop/group-orders',
    '/custom-design/',
    '/about',
    '/contact',
    '/privacy',
    '/terms',
    '/cart/',
    '/auth/login',
    '/auth/register',
]


# ── Skip link and landmarks ──────────────────────────────────────────────────

@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_page_has_a_skip_link(client, path):
    page = parse(client, path)
    skip = page.find('a', href='#main-content')
    assert skip, f'{path} has no skip-to-content link'


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_skip_link_target_exists(client, path):
    """A skip link pointing at nothing is worse than none: it looks available
    and silently does nothing."""
    page = parse(client, path)
    assert 'main-content' in page.ids, f'{path} has no #main-content to skip to'


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_page_has_the_expected_landmarks(client, path):
    page = parse(client, path)
    present = {name for name, _ in page.tags}
    for landmark in ('header', 'nav', 'main', 'footer'):
        assert landmark in present, f'{path} is missing <{landmark}>'


def test_skip_link_is_the_first_focusable_thing(client):
    """It has to come before the navigation or it cannot skip it."""
    page = parse(client, '/')
    for name, attributes in page.tags:
        if name == 'a' and attributes.get('href'):
            assert attributes['href'] == '#main-content', (
                'the first link on the page is not the skip link'
            )
            return
    pytest.fail('no links found')


def test_main_landmark_is_focusable(client):
    """The browser will not move focus to a plain <main>, so the skip link would
    scroll without moving the keyboard position."""
    page = parse(client, '/')
    main = page.find('main', id='main-content')
    assert main, 'no <main id="main-content">'
    assert main[0].get('tabindex') == '-1'


# ── Live region for messages inserted by JavaScript ──────────────────────────

@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_flash_region_is_always_present(client, path):
    """PMKC.showFlash() appends into this container. A live region has to exist
    before content is put into it, or nothing is announced."""
    page = parse(client, path)
    containers = [
        attributes for name, attributes in page.tags
        if 'flash-messages' in attributes.get('class', '')
    ]
    assert containers, f'{path} has no flash container'
    assert containers[0].get('aria-live') == 'polite', path


def _add_to_cart(client, seed, quantity=1):
    return client.post('/cart/add', json={
        'product_id': seed['tee_id'],
        'size': 'M',
        'color': 'Black',
        'quantity': quantity,
        'placement': 'center_chest',
    })


def test_checkout_card_errors_are_announced(customer_client, seed):
    """A declined card is written into this element by Stripe's callback."""
    _add_to_cart(customer_client, seed)
    page = parse(customer_client, '/checkout/')
    errors = page.find('div', id='card-errors')
    assert errors, 'no #card-errors element'
    assert errors[0].get('role') == 'alert'


# ── Labels ───────────────────────────────────────────────────────────────────

LABELLED_INPUT_TYPES = {
    'text', 'email', 'password', 'search', 'tel', 'number', 'url', 'date',
    'file', '',
}


def _is_labelled(attributes, page):
    if attributes.get('aria-label') or attributes.get('aria-labelledby'):
        return True
    element_id = attributes.get('id')
    return bool(element_id) and element_id in page.label_targets


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_visible_fields_are_labelled(client, path):
    """A placeholder is not a label: it vanishes as soon as the customer types."""
    page = parse(client, path)
    unlabelled = []
    for name, attributes in page.all_of('input', 'select', 'textarea'):
        if name == 'input':
            input_type = attributes.get('type', '').lower()
            if input_type not in LABELLED_INPUT_TYPES:
                continue
        if not _is_labelled(attributes, page):
            unlabelled.append(attributes)
    assert not unlabelled, (
        f'{path} has unlabelled fields: '
        + ', '.join(a.get('id') or a.get('name') or '(anonymous)' for a in unlabelled)
    )


def test_shop_search_field_is_labelled(client):
    page = parse(client, '/shop/')
    assert 'shopSearchInput' in page.label_targets


def test_customize_quantity_is_labelled(client, seed):
    page = parse(client, f'/shop/customize/{seed["tee_id"]}')
    assert 'quantity' in page.label_targets


def test_cart_quantity_inputs_are_labelled(customer_client, seed):
    _add_to_cart(customer_client, seed, quantity=2)
    page = parse(customer_client, '/cart/')
    quantities = [
        a for _, a in page.all_of('input')
        if 'quantity-input' in a.get('class', '')
    ]
    assert quantities, 'no cart quantity inputs found'
    for attributes in quantities:
        assert _is_labelled(attributes, page), attributes


# ── Keyboard operability ─────────────────────────────────────────────────────

def test_customizer_choices_are_keyboard_reachable(client, seed):
    """Colour, size and placement were <div onclick>: not focusable, and not
    activated by Enter. Without these a keyboard user cannot place an order."""
    page = parse(client, f'/shop/customize/{seed["tee_id"]}')
    for class_name in ('color-card', 'size-card', 'placement-option'):
        elements = [
            a for _, a in page.tags
            if class_name in a.get('class', '').split()
        ]
        assert elements, f'no .{class_name} found'
        for attributes in elements:
            assert attributes.get('role') == 'button', class_name
            assert attributes.get('tabindex') == '0', class_name


def test_product_thumbnails_are_buttons(client, seed):
    """They used to be <img onclick>, which Tab cannot reach."""
    page = parse(client, f'/shop/product/{seed["tee_id"]}')
    thumbnail_images = [
        a for _, a in page.all_of('img')
        if 'thumbnail' in a.get('class', '').split()
    ]
    assert not thumbnail_images, 'a thumbnail is still a bare clickable <img>'


def test_no_positive_tabindex(client):
    """A tabindex above 0 overrides the document order for the whole page."""
    for path in PUBLIC_PAGES:
        page = parse(client, path)
        for name, attributes in page.tags:
            raw = attributes.get('tabindex')
            if raw in (None, ''):
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            assert value <= 0, f'{path}: <{name} tabindex="{raw}">'


# ── Dialogs ──────────────────────────────────────────────────────────────────

def test_size_chart_dialog_is_marked_up_as_one(client, app, seed):
    import json

    from models import Product, db

    with app.app_context():
        product = db.session.get(Product, seed['tee_id'])
        product.size_chart = json.dumps({'M': {'chest': 20, 'length': 28}})
        db.session.commit()

    page = parse(client, f'/shop/product/{seed["tee_id"]}')
    modal = page.find('div', id='sizeChartModal')
    assert modal, 'no size chart modal'
    assert modal[0].get('role') == 'dialog'
    assert modal[0].get('aria-modal') == 'true'
    assert modal[0].get('aria-labelledby'), 'dialog has no accessible name'


# ── Images ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_every_image_has_an_alt_attribute(client, path):
    """alt="" is fine for decoration. A missing attribute makes a screen reader
    read the filename instead."""
    page = parse(client, path)
    missing = [a for _, a in page.all_of('img') if 'alt' not in a]
    assert not missing, (
        f'{path}: {len(missing)} <img> without alt: '
        + ', '.join(a.get('src', '?')[:60] for a in missing)
    )


# ── Headings ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_page_has_exactly_one_h1(client, path):
    page = parse(client, path)
    count = page.headings.count('h1')
    assert count == 1, f'{path} has {count} <h1> elements'


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_heading_levels_do_not_skip(client, path):
    page = parse(client, path)
    previous = 0
    for heading in page.headings:
        level = int(heading[1])
        if previous:
            assert level <= previous + 1, (
                f'{path}: {heading} follows h{previous}, skipping a level'
            )
        previous = level


def test_customize_page_has_an_h1(client, seed):
    """It used to open with an h2 and have no h1 at all."""
    page = parse(client, f'/shop/customize/{seed["tee_id"]}')
    assert page.headings.count('h1') == 1


def test_cart_with_items_has_ordered_headings(customer_client, seed):
    _add_to_cart(customer_client, seed)
    page = parse(customer_client, '/cart/')
    assert page.headings.count('h1') == 1
    previous = 0
    for heading in page.headings:
        level = int(heading[1])
        if previous:
            assert level <= previous + 1, f'{heading} follows h{previous}'
        previous = level
