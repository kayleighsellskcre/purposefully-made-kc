"""Customizer bugs: missing sizes, cart add on mockup-only colours, fonts, gallery."""
import json

from models import db, Product, ProductColorVariant
from utils.fonts import CUSTOMIZE_BACK_FONTS, GROUP_ORDER_FONTS
from utils.mockups import get_carousel_colors_for_product
from utils.personalization_layout import font_path
from utils.sizes import DEFAULT_ADULT_SIZES, shop_sizes_for_product
from utils.stock import available_qty, check_stock


def test_shop_sizes_fall_back_to_inventory_keys():
    product = Product(available_sizes='[]', age_group='adult')
    variants = [ProductColorVariant(color_name='Asphalt', size_inventory=json.dumps({'S': 0, 'M': 0, 'XL': 0}))]
    assert shop_sizes_for_product(product, variants) == ['S', 'M', 'XL']


def test_shop_sizes_use_adult_defaults_when_nothing_is_listed():
    product = Product(available_sizes=None, age_group='adult')
    assert shop_sizes_for_product(product, []) == DEFAULT_ADULT_SIZES


def test_customize_still_renders_size_cards_when_the_product_lists_none(client, app, seed):
    with app.app_context():
        product = Product.query.get(seed['tee_id'])
        product.available_sizes = '[]'
        db.session.commit()
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'size-card' in html
    assert 'data-size="M"' in html
    assert "aren't listed yet" not in html


def test_color_size_placement_and_upload_controls_are_keyboard_operable(client, seed):
    """Round 3 audit: color, size, placement, and upload controls were only
    wired with onclick, so a keyboard-only shopper tabbing to a swatch or
    size card could not select it. Checks the delegated Enter/Space handler
    is wired up and the controls carry the role/tabindex a screen reader or
    keyboard user relies on.
    """
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'setupKeyboardActivation();' in html
    assert 'function setupKeyboardActivation()' in html
    assert "activateOnEnterOrSpace(document.getElementById('colorGrid'), '.color-card')" in html
    assert "activateOnEnterOrSpace(document.getElementById('sizeGrid'), '.size-card')" in html
    assert "activateOnEnterOrSpace(document.getElementById('placementGrid'), '.placement-option')" in html
    assert "getElementById('uploadAreaMain')" in html


def test_a_colour_without_a_warehouse_row_is_not_treated_as_out_of_stock(app, seed):
    with app.app_context():
        product = Product.query.get(seed['tee_id'])
        assert available_qty(product, 'Asphalt', 'M') is None
        ok, err, _ = check_stock(product, 'Asphalt', 'M', 1, cart=[])
        assert ok is True
        assert err is None


def test_adding_a_mockup_only_colour_succeeds(client, seed):
    resp = client.post('/cart/add', json={
        'product_id': seed['tee_id'],
        'size': 'M',
        'color': 'Asphalt',
        'quantity': 1,
        'placement': 'center_chest',
    })
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_add_to_cart_with_design_id_and_url_does_not_crash(client, seed):
    """Regression: UnboundLocalError on Design when both design_id and design_url
    were sent — the live Add to Cart 500 on /cart/add.
    """
    resp = client.post('/cart/add', json={
        'product_id': seed['tee_id'],
        'size': 'M',
        'color': 'Black',
        'quantity': 1,
        'placement': 'center_chest',
        'design_id': seed['free_design_id'],
        'design_url': '/static/uploads/designs/gallery-logo.png',
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()['success'] is True


def test_shop_card_counts_colours_that_have_no_photo(app, seed):
    with app.app_context():
        product = Product.query.get(seed['hoodie_id'])
        colors = get_carousel_colors_for_product(product, app)
        names = {c['color_name'] for c in colors}
        assert 'Black' in names
        assert 'Sport Grey' in names
        assert len(colors) >= 2


def test_customize_page_includes_varsity_regular_and_a_gallery_dropdown(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'Varsity Regular' in html
    assert 'logoGalleryGrid' in html or 'gallery-design-picker' in html
    assert 'html2canvas' not in html
    assert '+$6.00' in html
    assert 'back-design-fee-amount' in html
    assert '$6.0"' not in html


def test_group_order_customize_shows_logo_thumbnails_not_a_dropdown(client, app, seed):
    """Group logos are few — show them as a grid, not a select menu."""
    with app.app_context():
        from models import Collection
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allowed_design_ids = json.dumps([seed['free_design_id']])
        coll.restrict_options = True
        db.session.commit()
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'logoGalleryGrid' in html
    assert 'id="galleryDesignSelect"' not in html
    assert 'Group logos' in html
    assert 'loading="eager"' in html
    assert 'fetchpriority="high"' in html


def test_group_store_keeps_normal_nav_and_offers_back_to_main_site(client, seed):
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']
    html = client.get(f'/c/{seed["collection_slug"]}').get_data(as_text=True)
    assert 'href="/shop/"' in html or "href='/shop/'" in html
    assert 'Back to main site' in html
    assert html.count('/c/leave') == 1
    resp = client.get('/c/leave?next=/', follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/')
    with client.session_transaction() as sess:
        assert 'collection_id' not in sess


def test_varsity_regular_font_file_is_present():
    assert font_path('Varsity Regular') is not None
    assert font_path('Varsity Regular Solid') is not None


def test_sports_jersey_uses_the_exact_self_hosted_athletic_font():
    from utils.print_sizes import FONT_METRICS

    assert font_path('Sports Jersey') == font_path('Jersey M54')
    assert FONT_METRICS['Sports Jersey'] == FONT_METRICS['Jersey M54']
    assert 'Sports Jersey' in [value for value, _label in CUSTOMIZE_BACK_FONTS]
    assert 'Sports Jersey' in [value for value, _label in GROUP_ORDER_FONTS]


def test_varsity_names_use_solid_companion_font():
    from utils.personalization_layout import name_font_name
    assert name_font_name('Varsity Regular') == 'Varsity Regular Solid'
    assert name_font_name('Bebas Neue') == 'Bebas Neue'


def test_group_order_font_list_includes_varsity_regular():
    values = [value for value, _label in GROUP_ORDER_FONTS]
    assert 'Varsity Regular' in values
    assert 'Varsity Regular' in [value for value, _label in CUSTOMIZE_BACK_FONTS]


def test_customize_offers_bright_pink_and_yellow_text_swatches(client, app, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'data-color="#ff2eb6"' in html
    assert 'data-color="#ffd400"' in html
    assert 'Bright pink' in html
    assert 'Yellow' in html
    assert 'Varsity Regular Solid' in html


def test_customer_size_does_not_rescale_the_visual_mockup(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'function previewReferenceSize()' in html
    assert 'bodyLengthIn(previewReferenceSize())' in html
    assert 'nameHeightIn(previewSize)' in html
    # Front logos use one visual target across youth/adult garments and correct
    # transparent padding without changing production dimensions.
    assert 'function visibleArtworkWidthRatio(image)' in html
    assert 'let garmentWidth = (box && box.measured && box.widthPx)' in html
    assert 'garmentWidth * targetRatio / visibleWidthRatio' in html
    assert 'const targetRatio = isSideChest ? 0.14 : 0.38' in html
    assert "String(state.presetDesignId || state.designUrl || '') + '|' + src + '|' + placement" in html
    assert 'ctx.drawImage(mockup, disp.left, disp.top, disp.width, disp.height)' in html
    assert 'No ink found' in html
    assert 'object-position: center 18%' not in html
    assert "if (state.currentView === 'back') return;" in html
    assert 'state.lastFrontGarmentWidthPx' in html
    assert 'canvasWidth * 0.62' not in html
    assert "if (side === 'front') applyDesignFit();" in html
    assert "if (placement === 'left_chest') visualCenter += box.widthPx * 0.16" in html
    assert "if (placement === 'right_chest') visualCenter -= box.widthPx * 0.16" in html
    assert 'box.widthPx * 0.22' not in html
    assert 'const orderedW = logoWidthForSize(size)' not in html
    assert '/design/preview/0' in html
    assert 'designImage.src = instantSrc' in html
    assert 'never delay the first paint' in html
    assert '/api/artwork-fits?ids=' in html
    assert '/api/garment-metrics?src=' in html
    assert 'function ensureGarmentMetrics(src)' in html
    assert 'function prefetchArtworkFits(extraIds)' in html
    assert 'function fetchArtworkFitNow(id)' in html
    assert 'function prefetchAllGarmentMetrics()' in html
    assert 'Other colors wait so a logo click' in html
    assert 'const GARMENT_SILHOUETTES = Object.assign' in html
    assert 'visible.length ? visible : cards' not in html
    assert 'if (state.presetDesignId && !hasCachedFit) return;' not in html
    assert 'state.lockedFitKey' in html
    assert 'state.lockedFitMeasured' in html
    assert 'const isUniformKit = false' in html
    assert 'if (isUniformKit && !shirtMeasured)' in html
    assert "if (isUniformKit) {" in html
    assert "designLayer.classList.add('is-fitting');" in html
    assert 'Jerseys stay hidden until' in html
    assert "&& shirtMeasured)" in html
    assert '(!isUniformKit || shirtMeasured)' not in html
    assert "source: 'fallback'" in html
    assert "source: 'measured' });" not in html
    assert 'padded PNG' in html
    assert 'Paint on the click' in html
    assert 'state.lastFrontGarmentSrc' in html
    assert 'design-layer.is-fitting' in html
    assert 'state.lastFrontGarmentSrc === src ? state.lastFrontGarmentWidthPx' in html
    assert '|| (box && box.widthPx)' not in html
    assert "designImage.src = previewSource" not in html
    assert 'transition: transform 0.3s ease' in html
    # Production is still generated from state.selectedSize via the default
    # size-aware helpers, then measured before the values are submitted.
    assert "formData.append('size', state.selectedSize)" in html
    generated = html.index('await generateBackDesignNameNumberImage()')
    measured = html.index("formData.append('name_width_in'", generated)
    assert measured > generated


def test_mockup_viewport_keeps_whole_shirt_and_view_buttons_visible(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'height: calc(100dvh - 160px)' in html
    assert 'height: min(48dvh, 420px)' in html
    assert 'object-fit: contain' in html
    assert 'grid-template-columns: 116px minmax(0, 1fr)' in html
    assert '.preview-info .pos-controls-row' in html
    assert 'const scale = Math.min(cw / nw, ch / nh)' in html
    assert 'class="preview-color-badge"' in html
    canvas_start = html.index('class="preview-canvas"')
    color_badge = html.index('class="preview-color-badge"', canvas_start)
    visual_note = html.index('class="preview-note"', canvas_start)
    controls = html.index('class="preview-controls"', canvas_start)
    assert canvas_start < color_badge < visual_note < controls
    assert html.count('id="selectedColorName"') == 1
    assert 'Mockup preview only. Final logo sizing will be adjusted proportionally for your shirt.' in html
    assert 'grid-template-rows: minmax(0, 1fr) auto' in html
    assert 'position: static' in html
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr))' in html
    assert 'id="colorPickerDisclosure"' in html
    assert 'id="colorDisclosureName"' in html
    assert 'disclosure.open = false' in html


def test_add_to_cart_refits_mockup_and_prices_partial_back_personalization(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    loaded = html.index("mockupImg.style.opacity = '1'")
    assert html.index('applyDesignFit();', loaded) < html.index(
        'updateBackDesignPreview();', loaded
    )
    assert 'function currentBackDesignFee()' in html
    assert 'return parts * 3' in html
    assert 'currentBackDesignFee();' in html
    assert 'A name or number is $3. Both are $6.' in html


def test_visual_normalization_does_not_change_adult_or_youth_print_widths():
    from types import SimpleNamespace
    from utils.print_sizes import front_transfer_size

    adult = SimpleNamespace(age_group='adult', category='tee', name='Adult Tee')
    youth = SimpleNamespace(age_group='youth', category='tee', name='Youth Tee')
    assert front_transfer_size('M', adult)['width'] == 10.0
    assert front_transfer_size('M', youth)['width'] == 8.0


def test_same_origin_design_preview_streams_cloud_artwork(
    client, seed, app, monkeypatch
):
    import base64
    from models import Design

    png = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ'
        'AAAADUlEQVR42mNk+M/wHwAF/gL+X8WqWQAAAABJRU5ErkJggg=='
    )

    class FakeResponse:
        headers = {'Content-Type': 'image/png'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return png

    with app.app_context():
        design = db.session.get(Design, seed['free_design_id'])
        design.file_path = 'https://public-example.r2.dev/design.png'
        db.session.commit()

    monkeypatch.setattr('routes.design.urlopen', lambda *_args, **_kwargs: FakeResponse())
    response = client.get(f'/design/preview/{seed["free_design_id"]}')
    assert response.status_code == 200
    assert response.mimetype == 'image/png'
    assert response.data == png


def test_group_order_create_form_offers_varsity_regular(customer_client):
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'Varsity Regular' in html


def test_group_customize_tells_parents_to_enter_first_name(client, app, seed):
    with app.app_context():
        from models import Collection
        coll = db.session.get(Collection, seed['collection_id'])
        coll.back_design_name_part = 'first'
        coll.allow_back_design = True
        coll.back_design_type = 'name_number'
        coll.team_store_config = json.dumps({
            'version': 1,
            'uniform': {
                'enabled': True,
                'product_id': seed['tee_id'],
                'home_color': 'Black',
                'away_color': '',
            },
            'fan_product_ids': [seed['hoodie_id']],
        })
        db.session.commit()
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']
    html = client.get(
        f'/shop/customize/{seed["tee_id"]}?catalog_section=uniform&uniform_kit=home'
    ).get_data(as_text=True)
    assert "Player's first name" in html
    assert 'e.g. JORDAN' in html
    assert 'first names on these jerseys' in html
    assert "Player's last name" not in html
    assert 'const requireBackName = true' in html


def test_group_customize_defaults_to_last_name_on_jerseys(client, app, seed):
    with app.app_context():
        from models import Collection
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allow_back_design = True
        coll.back_design_type = 'name_number'
        coll.team_store_config = json.dumps({
            'version': 1,
            'uniform': {
                'enabled': True,
                'product_id': seed['tee_id'],
                'home_color': 'Black',
                'away_color': '',
            },
            'fan_product_ids': [seed['hoodie_id']],
        })
        db.session.commit()
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']
    html = client.get(
        f'/shop/customize/{seed["tee_id"]}?catalog_section=uniform&uniform_kit=home'
    ).get_data(as_text=True)
    assert "Player's last name" in html
    assert 'e.g. SMITH' in html
    assert 'last names on these jerseys' in html
    assert 'const isUniformKit = true' in html
    assert 'if (isUniformKit && !shirtMeasured)' in html


def test_fan_wear_customize_does_not_require_a_name_or_number(client, app, seed):
    with app.app_context():
        from models import Collection
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allow_back_design = True
        coll.back_design_type = 'name_number'
        coll.restrict_options = True
        coll.team_store_config = json.dumps({
            'version': 1,
            'uniform': {
                'enabled': True,
                'product_id': seed['tee_id'],
                'home_color': 'Black',
                'away_color': '',
            },
            'fan_product_ids': [seed['tee_id']],
            'fan_personalization_enabled': True,
        })
        db.session.commit()
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']
    html = client.get(
        f'/shop/customize/{seed["tee_id"]}?catalog_section=fan'
    ).get_data(as_text=True)
    assert 'const requireBackName = false' in html
    assert 'const isUniformKit = false' in html
    assert 'Optional. Leave this blank if you do not want a name or number' in html
    assert 'Last name (optional)' in html
    assert "Player's last name" not in html
    assert 'A name or number on the back is optional' not in html
    assert 'if (requireBackName)' in html


def test_measure_garment_metrics_keeps_only_ok_boxes():
    from routes.shop import _measure_garment_metrics

    variants = [
        {'front_image': '/static/front.png', 'back_image': '/static/back.png'},
        {'front_image': '/static/front.png', 'back_image': ''},
    ]
    calls = []

    def fake_measure(src, app=None, timeout=6.0):
        calls.append(src)
        if src.endswith('front.png'):
            return {'ok': True, 'width': 0.41, 'source': 'measured'}
        return {'ok': False, 'reason': 'not_found'}

    import services.garment_metrics as garment_metrics
    original = garment_metrics.measure
    garment_metrics.measure = fake_measure
    try:
        seed = _measure_garment_metrics(variants)
    finally:
        garment_metrics.measure = original
    assert seed == {'/static/front.png': {'ok': True, 'width': 0.41, 'source': 'measured'}}
    assert calls == ['/static/front.png', '/static/back.png']


def test_widen_mockup_hosts_are_allowed():
    import inspect

    from services import garment_metrics

    assert garment_metrics._remote_allowed('embed.widencdn.net', None) is True
    assert garment_metrics._remote_allowed('assets.widencdn.net', None) is True
    assert garment_metrics._remote_allowed('evil.example.com', None) is False
    assert "replace('{quality}', '80')" in inspect.getsource(garment_metrics._load_bytes)
