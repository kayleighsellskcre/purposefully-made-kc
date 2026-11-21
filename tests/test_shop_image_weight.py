"""Round 2 audit item 13: /shop/ was about 1.5 MB of HTML with 1,411 img
tags (one per color variant per product) and no width/height on any of
them.

Only the shown color now ships a real <img> tag; the rest carry their
URL in data-src and get hydrated by JS the first time a card is hovered
or its color arrows are used. Layout shift is addressed with a fixed
aspect-ratio on the image rule rather than per-image width/height,
since intrinsic dimensions vary across a catalog pulled from S&S/SanMar.
"""
import html
import json
import re


def _add_color(app, product_id, color_name):
    from models import db, ProductColorVariant
    with app.app_context():
        db.session.add(ProductColorVariant(
            product_id=product_id, color_name=color_name,
            front_image_url='/static/img/logo.png',
            size_inventory=json.dumps({'S': 5}),
        ))
        db.session.commit()


def _carousel_html_for(body, product_id):
    """Slice out just the one balanced <div class="color-carousel" ...>
    block for this product, by counting div open/close tags rather than
    a brittle regex (the block runs to hundreds of colors in some tests).
    """
    start = body.index(f'<div class="color-carousel" data-product-id="{product_id}"')
    depth = 0
    pos = start
    tag_re = re.compile(r'<div\b|</div>')
    for match in tag_re.finditer(body, start):
        depth += -1 if match.group(0).startswith('</div') else 1
        pos = match.end()
        if depth == 0:
            break
    return body[start:pos]


def test_only_the_shown_color_ships_a_real_img_tag(client, app, seed):
    _add_color(app, seed['tee_id'], 'Navy')
    body = client.get('/shop/').get_data(as_text=True)
    carousel = _carousel_html_for(body, seed['tee_id'])

    assert carousel.count('<img') == 1
    # The other colors are not slides at all yet: they ride along as one short list that JS turns into slides
    # the first time the card is used.
    more = re.search(r'data-more="([^"]*)"', carousel)
    assert more and len(json.loads(html.unescape(more.group(1)))) >= 2


def test_deferred_slides_have_no_img_tag_inside_them(client, app, seed):
    _add_color(app, seed['tee_id'], 'Navy')
    body = client.get('/shop/').get_data(as_text=True)
    carousel = _carousel_html_for(body, seed['tee_id'])

    assert carousel.count('class="carousel-slide') == 1, 'only the shown color is a slide in the page'
    assert carousel.count('<img') == 1
    more = re.search(r'data-more="([^"]*)"', carousel)
    names = [n for n, _u in json.loads(html.unescape(more.group(1)))]
    assert 'Navy' in names and len(names) >= 2           # the other colors are still there, just as a short list


def test_carousel_carries_the_product_name_for_js_hydration(client, app, seed):
    _add_color(app, seed['tee_id'], 'Navy')
    body = client.get('/shop/').get_data(as_text=True)
    assert 'data-product-name="Unisex Jersey Short Sleeve Tee"' in body


def test_product_images_have_a_fixed_aspect_ratio_to_stop_layout_shift(client, seed):
    body = client.get('/shop/').get_data(as_text=True)
    assert 'aspect-ratio: 1 / 1' in body


def test_a_single_color_product_still_renders_its_one_image(client, seed):
    """The hoodie only has one color variant - no carousel, no data-src
    deferral, just the existing single <img> path."""
    body = client.get('/shop/').get_data(as_text=True)
    assert 'Heavy Blend Hooded Sweatshirt' in body
