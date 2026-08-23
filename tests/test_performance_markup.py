"""Markup-level performance guards.

These lock in the two front-end fixes that are easy to undo by accident:

Gallery images are deferred. Inactive carousel slides are hidden with `opacity`
rather than `display:none`, so before this the browser fetched every colour of
every product at full priority — roughly 1350 images on the live catalogue.

The webfont stylesheet does not block the first paint. It is loaded as a print
stylesheet and promoted on load, the same trick three other templates in this
project already use.
"""
import json
import os
import re
from html.parser import HTMLParser

import pytest

from models import db, Product, ProductColorVariant

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ImageCollector(HTMLParser):
    """Collect every <img> tag's attributes, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.images.append(dict(attrs))


def images_in(html):
    parser = ImageCollector()
    parser.feed(html)
    return parser.images


@pytest.fixture()
def many_products(app, seed):
    """More products than the eager-loading cutoff, so laziness is observable.

    With only the seeded catalogue every card is in the first row, so a test
    asserting "something is lazy" would pass without the attribute existing.
    """
    sizes = ['S', 'M', 'L', 'XL']
    with app.app_context():
        for n in range(10):
            product = Product(
                style_number=f'LAZY{n}', name=f'Lazy Test Tee {n}',
                category='Tee', age_group='adult', base_price=25.00,
                is_active=True,
                available_sizes=json.dumps(sizes),
                available_colors=json.dumps(['Black', 'White']),
            )
            db.session.add(product)
            db.session.flush()
            db.session.add(ProductColorVariant(
                product_id=product.id, color_name='Black', color_hex='#000000',
                size_inventory=json.dumps({s: 5 for s in sizes}),
                front_image_url=f'/static/img/products/lazy{n}.jpg',
            ))
        db.session.commit()
    return True


# ── Deferred images ──────────────────────────────────────────────────────────

def test_shop_defers_off_screen_images(client, many_products):
    resp = client.get('/shop/')
    assert resp.status_code == 200

    found = images_in(resp.get_data(as_text=True))
    assert found, 'no images rendered, so this test proves nothing'

    lazy = [img for img in found if img.get('loading') == 'lazy']
    assert lazy, 'every image was eager; off-screen images should be deferred'


def test_shop_keeps_the_first_images_eager(client, many_products):
    """Deferring the image the customer is looking at would hurt, not help.

    A lazy above-the-fold image delays the largest contentful paint, which is
    the opposite of the intent.
    """
    resp = client.get('/shop/')
    found = images_in(resp.get_data(as_text=True))

    eager = [img for img in found if img.get('loading') == 'eager']
    assert eager, 'no image was eager; the first row should load immediately'
    assert any(img.get('fetchpriority') == 'high' for img in eager)


def test_every_shop_image_states_its_loading_intent(client, many_products):
    """No image should be left to the browser's default.

    Catches a new <img> added to the grid without a decision being made.
    """
    resp = client.get('/shop/')
    undecided = [
        img for img in images_in(resp.get_data(as_text=True))
        if img.get('loading') not in ('lazy', 'eager')
    ]
    assert not undecided, (
        'images with no loading attribute: '
        + ', '.join(sorted(img.get('src', '?') for img in undecided))
    )


def test_group_order_page_defers_off_screen_images(client, seed):
    resp = client.get(f"/c/{seed['collection_slug']}")
    assert resp.status_code == 200

    undecided = [
        img for img in images_in(resp.get_data(as_text=True))
        if img.get('loading') not in ('lazy', 'eager')
    ]
    assert not undecided, (
        'images with no loading attribute: '
        + ', '.join(sorted(img.get('src', '?') for img in undecided))
    )


def test_design_gallery_defers_images(client, seed):
    resp = client.get('/shop/design-gallery')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    found = images_in(html)
    if not found:
        pytest.skip('no gallery designs rendered in this fixture')
    assert all(img.get('loading') in ('lazy', 'eager') for img in found)


# ── Non-blocking webfonts ────────────────────────────────────────────────────

def test_webfont_stylesheet_does_not_block_the_first_paint(client):
    """The Google Fonts link must be fetched without holding up rendering."""
    html = client.get('/').get_data(as_text=True)

    font_links = re.findall(r'<link[^>]*fonts\.googleapis\.com[^>]*>', html)
    assert font_links, 'no Google Fonts stylesheet found on the home page'

    # The <noscript> copy is deliberately blocking; that is the fallback for a
    # browser that cannot run the onload promotion.
    noscript = re.search(r'<noscript>.*?</noscript>', html, re.S)
    noscript_text = noscript.group(0) if noscript else ''

    blocking = [
        link for link in font_links
        if link not in noscript_text and 'media="print"' not in link
    ]
    assert not blocking, f'render-blocking font stylesheet: {blocking}'


def test_webfont_has_a_noscript_fallback(client):
    """With JS disabled the onload promotion never fires, so the font needs a
    plain stylesheet to fall back on."""
    html = client.get('/').get_data(as_text=True)
    noscript = re.search(r'<noscript>.*?</noscript>', html, re.S)
    assert noscript, 'no <noscript> block on the home page'
    assert 'fonts.googleapis.com' in noscript.group(0)


def test_webfont_url_still_asks_for_swap(client):
    """Without display=swap the text is invisible until the font arrives."""
    html = client.get('/').get_data(as_text=True)
    for link in re.findall(r'<link[^>]*fonts\.googleapis\.com[^>]*>', html):
        assert 'display=swap' in link, f'font link missing display=swap: {link}'


# ── Dead assets ──────────────────────────────────────────────────────────────

def test_unreferenced_customizer_script_is_gone():
    """static/js/customizer.js was loaded by no template and was 12KB."""
    assert not os.path.exists(os.path.join(ROOT, 'static', 'js', 'customizer.js'))


def test_no_template_references_the_deleted_script():
    """Guards against the delete and a stray <script src> disagreeing."""
    offenders = []
    templates = os.path.join(ROOT, 'templates')
    for folder, _dirs, files in os.walk(templates):
        for name in files:
            if not name.endswith('.html'):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding='utf-8', errors='replace') as handle:
                if 'js/customizer.js' in handle.read():
                    offenders.append(os.path.relpath(path, ROOT))
    assert not offenders, f'templates still load the deleted script: {offenders}'
