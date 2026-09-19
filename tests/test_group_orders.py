"""The group-order create form, including the 413 that broke it in production."""
import io
import json

from models import db, Collection, Product


def _base_form(seed, **over):
    form = {
        'name': 'Riverview Spirit Wear 2026',
        'products': [str(seed['tee_id'])],
        'allowed_placements': ['center_chest', 'left_chest'],
        'group_kind': 'other',
    }
    form.update(over)
    return form


def _post(client, form):
    return client.post(
        '/shop/group-orders/create', data=form,
        content_type='multipart/form-data', follow_redirects=True,
    )


def _too_large(response):
    body = response.get_data(as_text=True).lower()
    return 'too large' in body or 'too many options' in body


# ── The 413 ──────────────────────────────────────────────────────────────────

def test_a_form_with_many_options_selected_is_accepted(customer_client, seed, app):
    """Regression: /shop/group-orders/create returned 413 six times in production.

    Werkzeug allows 1000 multipart parts by default and counts every checkbox.
    The live catalogue renders 995, so one more colour broke the page. Nothing
    here is large — this body is a few hundred KB of short strings.
    """
    form = _base_form(seed)
    form['allowed_colors'] = [f'Colour {i}' for i in range(1200)]
    resp = _post(customer_client, form)
    assert resp.status_code == 200
    assert not _too_large(resp), 'the form part limit is still too low'
    with app.app_context():
        assert Collection.query.filter_by(name=form['name']).count() == 1


def test_the_part_limit_is_well_clear_of_the_biggest_real_form(app):
    # 995 parts today; leave headroom for the catalogue to keep growing.
    assert app.request_class.max_form_parts >= 3000


def test_a_genuinely_oversized_upload_is_still_refused(customer_client, seed, app):
    limit = app.config['MAX_CONTENT_LENGTH']
    form = _base_form(seed)
    form['cover_image'] = (io.BytesIO(b'x' * (limit + 1024)), 'huge.jpg')
    resp = _post(customer_client, form)
    assert _too_large(resp)
    with app.app_context():
        assert Collection.query.filter_by(name=form['name']).count() == 0


def test_an_oversized_upload_is_named_as_an_upload_problem(customer_client, seed, app):
    limit = app.config['MAX_CONTENT_LENGTH']
    form = _base_form(seed)
    form['cover_image'] = (io.BytesIO(b'x' * (limit + 1024)), 'huge.jpg')
    body = _post(customer_client, form).get_data(as_text=True).lower()
    assert 'upload is too large' in body


def test_ajax_uploads_get_a_json_413_not_an_html_page(customer_client, app):
    limit = app.config['MAX_CONTENT_LENGTH']
    resp = customer_client.post(
        '/design/upload',
        data={'file': (io.BytesIO(b'x' * (limit + 1024)), 'huge.png')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 413
    assert resp.is_json
    assert 'too large' in resp.get_json()['error'].lower()


# ── Creating a group order ───────────────────────────────────────────────────

def test_a_signed_in_customer_can_create_a_group_order(customer_client, seed, app):
    resp = _post(customer_client, _base_form(seed))
    assert resp.status_code == 200
    with app.app_context():
        collection = Collection.query.filter_by(slug='riverview-spirit-wear-2026').one()
        assert collection.is_active is True
        assert collection.created_by_user_id == seed['customer_id']
        assert collection.group_kind == 'other'
        assert [p.id for p in collection.products] == [seed['tee_id']]


def test_uniform_and_fan_wear_are_saved_as_separate_lanes(customer_client, seed, app):
    form = _base_form(
        seed,
        team_store_present='1',
        uniform_enabled='on',
        uniform_product_id=str(seed['tee_id']),
        uniform_home_color='Black',
        uniform_away_color='White',
        products=[str(seed['hoodie_id'])],
    )
    resp = _post(customer_client, form)
    assert resp.status_code == 200
    with app.app_context():
        collection = Collection.query.filter_by(name=form['name']).one()
        config = json.loads(collection.team_store_config)
        assert config['uniform'] == {
            'enabled': True,
            'product_id': seed['tee_id'],
            'product_ids': [seed['tee_id']],
            'home_color': 'Black',
            'away_color': 'White',
            'home_design_id': None,
            'away_design_id': None,
        }
        assert config['fan_product_ids'] == [seed['hoodie_id']]
        assert {p.id for p in collection.products} == {
            seed['tee_id'], seed['hoodie_id'],
        }


def test_a_uniform_only_store_does_not_require_fan_wear(customer_client, seed, app):
    form = _base_form(
        seed,
        team_store_present='1',
        uniform_enabled='on',
        uniform_product_id=str(seed['tee_id']),
        uniform_home_color='Black',
        uniform_away_color='',
        products=[],
    )
    resp = _post(customer_client, form)
    assert resp.status_code == 200
    with app.app_context():
        collection = Collection.query.filter_by(name=form['name']).one()
        assert [p.id for p in collection.products] == [seed['tee_id']]


def test_uniform_requires_a_real_home_color(customer_client, seed, app):
    form = _base_form(
        seed,
        team_store_present='1',
        uniform_enabled='on',
        uniform_product_id=str(seed['tee_id']),
        uniform_home_color='Purple That Does Not Exist',
        products=[],
    )
    body = _post(customer_client, form).get_data(as_text=True).lower()
    assert 'home color is not available' in body
    with app.app_context():
        assert Collection.query.filter_by(name=form['name']).count() == 0


def test_a_guest_is_sent_to_sign_in(guest, seed):
    resp = guest.post('/shop/group-orders/create', data=_base_form(seed))
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_a_group_order_needs_a_name(customer_client, seed, app):
    resp = _post(customer_client, _base_form(seed, name=''))
    assert 'enter a name' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert Collection.query.count() == 1  # only the seeded one


def test_a_group_order_needs_at_least_one_product(customer_client, seed, app):
    form = _base_form(seed)
    form['products'] = []
    resp = _post(customer_client, form)
    assert 'at least one shirt' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert Collection.query.filter_by(name=form['name']).count() == 0


def test_tax_rate_from_the_form_is_ignored_and_fixed_at_9_5(customer_client, seed, app):
    """Tax is fixed at KS 9.5% — form values (even garbage) must not change it."""
    resp = _post(customer_client, _base_form(seed, tax_rate='nine and a half'))
    assert resp.status_code == 200
    with app.app_context():
        collection = Collection.query.filter_by(name='Riverview Spirit Wear 2026').one()
        assert collection.tax_rate == 9.5


def test_created_group_orders_always_get_fixed_tax(customer_client, seed, app):
    resp = _post(customer_client, _base_form(seed, tax_rate='1'))
    assert resp.status_code == 200
    with app.app_context():
        collection = Collection.query.filter_by(slug='riverview-spirit-wear-2026').one()
        assert collection.tax_rate == 9.5


def test_a_duplicate_name_gets_its_own_url(customer_client, seed, app):
    _post(customer_client, _base_form(seed))
    _post(customer_client, _base_form(seed))
    with app.app_context():
        slugs = {c.slug for c in Collection.query.filter_by(
            name='Riverview Spirit Wear 2026'
        ).all()}
    assert slugs == {'riverview-spirit-wear-2026', 'riverview-spirit-wear-2026-1'}


def test_the_share_page_is_reachable_after_creating(customer_client, seed):
    resp = _post(customer_client, _base_form(seed))
    assert resp.status_code == 200
    assert 'riverview-spirit-wear-2026' in resp.get_data(as_text=True)


def test_the_create_page_renders_for_a_signed_in_customer(customer_client):
    resp = customer_client.get('/shop/group-orders/create')
    assert resp.status_code == 200
    assert 'Create Group Order' in resp.get_data(as_text=True)


def test_create_form_shows_photos_from_color_variants(customer_client, seed, app):
    """Most catalogue photos live on color variants, not front_mockup_template."""
    from models import Product, ProductColorVariant

    photo = 'https://cdn.ssactivewear.com/Images/Color/example_fm.jpg'
    with app.app_context():
        product = db.session.get(Product, seed['hoodie_id'])
        product.front_mockup_template = None
        variant = ProductColorVariant.query.filter_by(product_id=product.id).one()
        variant.front_image_url = photo
        db.session.commit()
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert photo in html
    assert 'product-checkbox-mockup' in html


def test_group_order_catalog_prefers_the_lightest_variant_photo(app, seed):
    from models import Product, ProductColorVariant
    from utils.product_filters import load_group_order_form_catalog

    with app.app_context():
        product = db.session.get(Product, seed['tee_id'])
        product.front_mockup_template = None
        black = ProductColorVariant.query.filter_by(
            product_id=product.id, color_name='Black'
        ).one()
        white = ProductColorVariant.query.filter_by(
            product_id=product.id, color_name='White'
        ).one()
        black.front_image_url = 'https://cdn.example.test/black.jpg'
        white.front_image_url = 'https://cdn.example.test/white.jpg'
        db.session.commit()
        catalog = load_group_order_form_catalog()
        previews = {p.id: p.preview_image_url for p in catalog['products']}
        assert previews[seed['tee_id']] == 'https://cdn.example.test/white.jpg'


def test_create_form_asks_whether_jersey_uses_first_or_last_name(customer_client):
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'name="back_design_name_part"' in html
    assert 'value="first"' in html
    assert 'value="last"' in html
    assert 'What name should parents put on the jersey?' in html


def test_organizer_can_require_first_names_on_jerseys(customer_client, seed, app):
    form = _base_form(seed)
    form['back_design_type'] = 'name_number'
    form['back_design_name_part'] = 'first'
    form['back_design_font'] = 'Sports Jersey'
    resp = _post(customer_client, form)
    assert resp.status_code == 200
    with app.app_context():
        saved = Collection.query.filter_by(name=form['name']).one()
        assert saved.back_design_name_part == 'first'
        assert saved.back_design_type == 'name_number'


def test_group_order_setup_does_not_offer_the_general_design_library(customer_client):
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'Or pick from existing designs' not in html
    assert 'name="allowed_designs"' not in html
    assert 'Gallery Logo' not in html


def test_group_order_create_form_uses_cleaned_color_names(customer_client, seed, app):
    from models import ProductColorVariant

    with app.app_context():
        db.session.add_all([
            ProductColorVariant(
                product_id=seed['tee_id'],
                color_name='DTG White',
                front_image_url='/static/img/logo.png',
                size_inventory=json.dumps({'M': 5}),
            ),
            ProductColorVariant(
                product_id=seed['tee_id'],
                color_name='TestColor',
                front_image_url='/static/img/logo.png',
                size_inventory=json.dumps({'M': 5}),
            ),
        ])
        db.session.commit()

    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'DTG White' not in html
    assert 'TestColor' not in html
    assert 'value="White"' in html or 'White</span>' in html


def test_group_order_edit_does_not_offer_unassigned_gallery_art(
    admin_client, seed
):
    html = admin_client.get(
        f'/admin/collections/{seed["collection_id"]}/edit'
    ).get_data(as_text=True)
    assert 'Gallery Logo' not in html
    assert 'name="allowed_designs"' not in html


def test_group_order_shopper_does_not_get_the_general_design_gallery(
    client, seed
):
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get(
        f'/shop/customize/{seed["tee_id"]}?catalog_section=fan'
    ).get_data(as_text=True)
    assert 'Gallery Logo' not in html


def test_uniform_cart_offers_a_direct_fan_wear_next_step(client, seed, app):
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.team_store_config = json.dumps({
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
        sess['cart'] = [{
            'product_id': seed['tee_id'],
            'size': 'M',
            'color': 'Black',
            'quantity': 1,
            'unit_price': 30.00,
            'collection_id': seed['collection_id'],
            'catalog_section': 'uniform',
            'uniform_kit': 'home',
        }]
    html = client.get('/cart/').get_data(as_text=True)
    assert 'Add Family &amp; Fan Wear' in html
    assert '?path=fan#fanWearSection' in html
    assert 'Need family or fan wear too?' in html
    assert 'btn btn-primary btn-block' in html


def test_group_order_edit_only_shows_artwork_assigned_to_that_store(
    admin_client, seed, app
):
    url = f'/admin/collections/{seed["collection_id"]}/edit'
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.allowed_design_ids = json.dumps([seed['free_design_id']])
        db.session.commit()
        from utils.group_orders import designs_for_group_order_form
        assert [d.id for d in designs_for_group_order_form(collection)] == [
            seed['free_design_id']
        ]
    response = admin_client.get(url)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Artwork already uploaded to this group order' in html
    assert 'Gallery Logo' in html


def test_the_create_page_shrinks_photos_before_upload(customer_client):
    """The 50 MB body limit is only safe because the browser resizes first."""
    body = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'image-shrink.js' in body
    assert 'data-shrink' in body


# ── Organizer permissions ────────────────────────────────────────────────────

def test_only_the_organizer_can_edit_their_group_order(client, seed, login, app):
    from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL

    login(client, CUSTOMER_EMAIL)
    _post(client, _base_form(seed))
    client.get('/auth/logout')

    login(client, OTHER_EMAIL)
    resp = client.get('/shop/group-orders/riverview-spirit-wear-2026/edit',
                      follow_redirects=True)
    assert 'only edit group orders you created' in resp.get_data(as_text=True).lower()


def test_the_organizer_can_open_their_own_edit_page(customer_client, seed):
    _post(customer_client, _base_form(seed))
    resp = customer_client.get('/shop/group-orders/riverview-spirit-wear-2026/edit')
    assert resp.status_code == 200


def test_directory_style_count_matches_what_the_store_shows(client, seed, app):
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.show_in_directory = True
        tee = Product.query.get(seed['tee_id'])
        hoodie = Product.query.get(seed['hoodie_id'])
        youth = Product.query.get(seed['youth_id'])
        collection.products = [tee, hoodie, youth]
        collection.team_store_config = json.dumps({
            'version': 1,
            'uniform': {'enabled': False},
            'fan_product_ids': [seed['hoodie_id']],
        })
        db.session.commit()

    directory = client.get('/shop/group-orders').get_data(as_text=True)
    assert '1 style' in directory
    assert '3 styles' not in directory
    store = client.get(f'/c/{seed["collection_slug"]}').get_data(as_text=True)
    assert 'Heavy Blend Hooded Sweatshirt' in store


def test_the_group_orders_directory_loads(client):
    resp = client.get('/shop/group-orders')
    assert resp.status_code == 200


def test_link_only_stores_are_left_off_public_listings(client, seed, app):
    with app.app_context():
        public = db.session.get(Collection, seed['collection_id'])
        public.show_in_directory = True
        hidden = Collection(
            name='Rainbow Cheetahs Link Only',
            slug='rainbow-cheetahs-link-only',
            is_active=True,
            show_in_directory=False,
        )
        db.session.add(hidden)
        db.session.commit()

    directory = client.get('/shop/group-orders').get_data(as_text=True)
    home = client.get('/').get_data(as_text=True)
    assert 'Test Elementary Spirit Wear' in directory
    assert 'Rainbow Cheetahs Link Only' not in directory
    assert 'Rainbow Cheetahs Link Only' not in home
    assert 'Link only' not in directory


def test_admin_edit_form_has_a_visibility_toggle(admin_client, seed):
    html = admin_client.get(
        f'/admin/collections/{seed["collection_id"]}/edit'
    ).get_data(as_text=True)
    assert 'name="visibility"' in html
    assert 'value="link_only"' in html
    assert 'value="public"' in html


def test_admin_group_order_cards_have_polished_dashboard_structure(
    admin_client
):
    html = admin_client.get('/admin/collections').get_data(as_text=True)
    assert 'class="collection-card-accent"' in html
    assert 'class="collection-avatar"' in html
    assert 'class="collection-order-count"' in html
    assert 'class="collection-share-label"' in html
    assert 'Share with your group' in html
    assert 'Export Orders' in html


def test_uploaded_group_visual_is_contained_and_keeps_group_name_attached(
    client, seed, app
):
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.cover_image = '/static/uploads/groups/team-visual.png'
        db.session.commit()

    html = client.get('/shop/group-orders').get_data(as_text=True)
    assert 'class="dir-card-img has-cover"' in html
    assert 'class="dir-card-art-frame"' in html
    assert 'class="dir-card-cover-title">Test Elementary Spirit Wear<' in html
    assert 'object-fit: contain' in html


# ── Admin edit / Save Changes ────────────────────────────────────────────────

def _collection_form_html(html):
    """Inner HTML of .collection-form, stopping at the first </form>.

    That first close is what the browser uses too: a nested design-delete
    </form> used to terminate the collection form early, which left Save
    Changes and the pickup fields outside any form.
    """
    start = html.find('class="collection-form"')
    if start < 0:
        start = html.find("class='collection-form'")
    assert start != -1, 'the edit page did not render a collection form'
    open_at = html.rfind('<form', 0, start)
    close_at = html.find('</form>', start)
    assert close_at != -1
    return html[open_at:close_at]


def test_admin_edit_keeps_save_and_pickup_inside_the_form(admin_client, seed):
    """Regression: one gallery design was enough to make Save Changes dead.

    The red × sat in a <form> inside the collection form. The parser ignored
    that inner start tag, then treated its </form> as the end of the collection
    form. Pickup instructions and Save Changes rendered on the page but
    belonged to nothing, so the brown button did nothing.
    """
    html = admin_client.get(
        f'/admin/collections/{seed["collection_id"]}/edit'
    ).get_data(as_text=True)
    inner = _collection_form_html(html)
    assert 'name="pickup_instructions"' in inner
    assert 'Save Changes' in inner
    assert 'form="collection-form"' in inner


def test_admin_can_save_pickup_instructions(admin_client, seed, app):
    from models import Collection

    cid = seed['collection_id']
    with app.app_context():
        collection = db.session.get(Collection, cid)
        collection.tax_rate = 0.0  # stale value; save must force 9.5
        collection.back_design_text_color = '#112233'
        collection.lock_back_design_style = True
        db.session.commit()

    resp = admin_client.post(
        f'/admin/collections/{cid}/edit',
        data={
            'name': 'Test Elementary Spirit Wear',
            'products': [str(seed['tee_id'])],
            'pickup_instructions': 'Riverview front office or send home with child',
            'shipping_enabled': 'on',
            'is_active': 'on',
            'tax_rate': '3.0',  # must be ignored
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert '/admin/collections' in (resp.headers.get('Location') or '')
    with app.app_context():
        saved = db.session.get(Collection, cid)
        assert saved.pickup_instructions == (
            'Riverview front office or send home with child'
        )
        assert saved.shipping_enabled is True
        assert saved.is_active is True
        assert saved.tax_rate == 9.5
        assert saved.back_design_text_color == '#112233'
        assert saved.lock_back_design_style is True


def test_admin_can_choose_and_unlock_back_style_controls(admin_client, seed, app):
    cid = seed['collection_id']
    html = admin_client.get(
        f'/admin/collections/{cid}/edit'
    ).get_data(as_text=True)
    assert 'name="back_design_text_color"' in html
    assert 'name="back_design_outline"' in html
    assert 'name="back_design_outline_color"' in html
    assert 'name="lock_back_design_style"' in html
    assert 'id="collBackPreview"' in html

    admin_client.post(
        f'/admin/collections/{cid}/edit',
        data={
            'name': 'Test Elementary Spirit Wear',
            'products': [str(seed['tee_id'])],
            'is_active': 'on',
            'back_design_type': 'name_number',
            'back_design_font': 'Sports Jersey',
            'back_design_text_color': '#ff2eb6',
            'back_design_outline': 'off',
            'back_design_outline_color': '#ffffff',
            'back_style_controls_present': '1',
            # lock_back_design_style deliberately unchecked
        },
        follow_redirects=False,
    )
    with app.app_context():
        saved = db.session.get(Collection, cid)
        assert saved.back_design_font == 'Sports Jersey'
        assert saved.back_design_text_color == '#ff2eb6'
        assert saved.back_design_outline is False
        assert saved.back_design_outline_color == '#ffffff'
        assert saved.lock_back_design_style is False


def test_admin_save_always_forces_fixed_tax_rate(admin_client, seed, app):
    from models import Collection

    cid = seed['collection_id']
    with app.app_context():
        collection = db.session.get(Collection, cid)
        collection.tax_rate = 0.0
        db.session.commit()

    admin_client.post(
        f'/admin/collections/{cid}/edit',
        data={
            'name': 'Test Elementary Spirit Wear',
            'products': [str(seed['tee_id'])],
            'is_active': 'on',
        },
        follow_redirects=False,
    )
    with app.app_context():
        assert db.session.get(Collection, cid).tax_rate == 9.5


def test_brand_scoped_colors_do_not_leak_across_brands():
    from types import SimpleNamespace
    from utils.group_orders import (
        allowed_colors_for_product,
        serialize_allowed_colors_from_form,
    )
    import json

    payload = serialize_allowed_colors_from_form([
        'Port & Company||Navy',
        'Port & Company||Black',
        'Bella+Canvas||White',
    ])
    data = json.loads(payload)
    assert data['Port & Company'] == ['Navy', 'Black']
    assert data['Bella+Canvas'] == ['White']

    port = SimpleNamespace(brand='Port & Company')
    bella = SimpleNamespace(brand='Bella+Canvas')
    assert allowed_colors_for_product(port, payload) == {'Navy', 'Black'}
    assert allowed_colors_for_product(bella, payload) == {'White'}
    # Brand with no picks stays unrestricted (does not inherit Port Navy)
    other = SimpleNamespace(brand='Independent Trading Co.')
    assert allowed_colors_for_product(other, payload) is None


def test_admin_can_save_showcase_logos(admin_client, seed, app):
    """Organizer picks which allowed logos appear at the top of the storefront."""
    from models import Collection
    import json

    cid = seed['collection_id']
    design_id = seed['free_design_id']
    admin_client.post(
        f'/admin/collections/{cid}/edit',
        data={
            'name': 'Test Elementary Spirit Wear',
            'products': [str(seed['tee_id'])],
            'is_active': 'on',
            'allowed_designs': [str(design_id)],
            'showcase_designs': [str(design_id)],
        },
        follow_redirects=False,
    )
    with app.app_context():
        saved = db.session.get(Collection, cid)
        assert json.loads(saved.allowed_design_ids or '[]') == [design_id]
        assert json.loads(saved.showcase_design_ids or '[]') == [design_id]


def test_showcase_ignores_designs_not_in_allowed(admin_client, seed, app):
    from models import Collection
    import json

    cid = seed['collection_id']
    admin_client.post(
        f'/admin/collections/{cid}/edit',
        data={
            'name': 'Test Elementary Spirit Wear',
            'products': [str(seed['tee_id'])],
            'is_active': 'on',
            'allowed_designs': [str(seed['free_design_id'])],
            'showcase_designs': [str(seed['fee_4_design_id'])],
        },
        follow_redirects=False,
    )
    with app.app_context():
        saved = db.session.get(Collection, cid)
        assert json.loads(saved.showcase_design_ids or '[]') == []


def test_group_order_filter_panel_starts_closed(client, seed):
    html = client.get(f'/c/{seed["collection_slug"]}').get_data(as_text=True)
    assert 'id="catalogFilterPanel" hidden' in html
    assert 'aria-expanded="false"' in html


def test_team_store_offers_player_or_fan_paths(client, seed, app):
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.products.append(db.session.get(Product, seed['hoodie_id']))
        collection.team_store_config = json.dumps({
            'version': 1,
            'uniform': {
                'enabled': True,
                'product_id': seed['tee_id'],
                'home_color': 'Black',
                'away_color': 'White',
            },
            'fan_product_ids': [seed['hoodie_id']],
        })
        db.session.commit()

    html = client.get(f'/c/{seed["collection_slug"]}').get_data(as_text=True)
    assert 'I’m ordering for a player' in html
    assert 'I only need family &amp; fan wear' in html
    assert 'Home Uniform' in html
    assert 'Away Uniform' in html
    assert 'catalog_section=uniform' in html
    assert 'uniform_kit=home' in html
    assert 'Family &amp; Fan Wear' in html


def test_uniform_color_is_locked_in_customizer_and_cart(client, seed, app):
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.team_store_config = json.dumps({
            'version': 1,
            'uniform': {
                'enabled': True,
                'product_id': seed['tee_id'],
                'home_color': 'Black',
                'away_color': 'White',
            },
            'fan_product_ids': [],
        })
        db.session.commit()

    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get(
        f'/shop/customize/{seed["tee_id"]}'
        '?catalog_section=uniform&uniform_kit=home'
    ).get_data(as_text=True)
    assert 'Home player uniform' in html
    assert 'Black' in html
    assert "formData.append('catalog_section', \"uniform\")" in html
    assert "formData.append('uniform_kit', \"home\")" in html

    response = client.post('/cart/add', data={
        'product_id': str(seed['tee_id']),
        'color': 'White',
        'size': 'M',
        'quantity': '1',
        'catalog_section': 'uniform',
        'uniform_kit': 'home',
    })
    assert response.status_code == 400
    assert 'must be Black' in response.get_json()['error']


def test_create_form_asks_school_team_or_other(customer_client):
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'name="group_kind"' in html
    assert 'value="school"' in html
    assert 'value="team"' in html
    assert 'value="other"' in html
    assert 'Youth uniform style' in html
    assert 'Home jersey logo' in html
    assert 'Away jersey logo' in html
    assert 'extra matching designs' in html.lower()


def test_create_requires_a_group_kind(customer_client, seed, app):
    form = _base_form(seed)
    form.pop('group_kind')
    resp = _post(customer_client, form)
    assert 'please choose whether this group order is for a school' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert Collection.query.filter_by(name=form['name']).count() == 0


def test_youth_and_adult_uniforms_can_be_offered_together(customer_client, seed, app):
    form = _base_form(
        seed,
        group_kind='team',
        team_store_present='1',
        uniform_enabled='on',
        uniform_product_id=str(seed['tee_id']),
        uniform_youth_product_id=str(seed['youth_id']),
        uniform_home_color='Black',
        uniform_away_color='',
        products=[str(seed['hoodie_id'])],
    )
    resp = _post(customer_client, form)
    assert resp.status_code == 200
    with app.app_context():
        collection = Collection.query.filter_by(name=form['name']).one()
        config = json.loads(collection.team_store_config)
        assert config['uniform']['product_id'] == seed['tee_id']
        assert config['uniform']['product_ids'] == [seed['tee_id'], seed['youth_id']]
        assert {p.id for p in collection.products} == {
            seed['tee_id'], seed['youth_id'], seed['hoodie_id'],
        }
    html = customer_client.get(
        f'/c/{collection_slug_for(form["name"], app)}'
    ).get_data(as_text=True)
    assert f'/shop/customize/{seed["tee_id"]}' in html
    assert f'/shop/customize/{seed["youth_id"]}' in html


def _uniform_collection(app, seed, **uniform_extra):
    from models import Collection
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.products.append(db.session.get(Product, seed['hoodie_id']))
        collection.allowed_design_ids = json.dumps([
            seed['free_design_id'], seed['fee_4_design_id'],
        ])
        uniform = {
            'enabled': True,
            'product_id': seed['tee_id'],
            'home_color': 'Black',
            'away_color': 'White',
            'home_design_id': seed['free_design_id'],
            'away_design_id': seed['fee_4_design_id'],
        }
        uniform.update(uniform_extra)
        collection.team_store_config = json.dumps({
            'version': 1,
            'uniform': uniform,
            'fan_product_ids': [seed['hoodie_id']],
        })
        db.session.commit()


def test_create_saves_home_and_away_jersey_logos(customer_client, seed, app):
    form = _base_form(
        seed,
        team_store_present='1',
        uniform_enabled='on',
        uniform_product_id=str(seed['tee_id']),
        uniform_home_color='Black',
        uniform_away_color='White',
        products=[str(seed['hoodie_id'])],
        allowed_designs=[str(seed['free_design_id']), str(seed['fee_4_design_id'])],
        uniform_home_design_id=str(seed['free_design_id']),
        uniform_away_design_id=str(seed['fee_4_design_id']),
    )
    resp = _post(customer_client, form)
    assert resp.status_code == 200
    with app.app_context():
        collection = Collection.query.filter_by(name=form['name']).one()
        config = json.loads(collection.team_store_config)
        assert config['uniform']['home_design_id'] == seed['free_design_id']
        assert config['uniform']['away_design_id'] == seed['fee_4_design_id']


def test_uniform_customize_applies_the_jersey_logo_automatically(client, app, seed):
    _uniform_collection(app, seed)
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get(
        f'/shop/customize/{seed["tee_id"]}?catalog_section=uniform&uniform_kit=home'
    ).get_data(as_text=True)
    assert 'Jersey Logo' in html
    assert 'already applied' in html
    assert 'Pick the group logo below' not in html
    assert f'presetDesignId: {seed["free_design_id"]}' in html
    assert 'Group logos: tap one to use' not in html

    away = client.get(
        f'/shop/customize/{seed["tee_id"]}?catalog_section=uniform&uniform_kit=away'
    ).get_data(as_text=True)
    assert f'presetDesignId: {seed["fee_4_design_id"]}' in away


def test_fan_wear_still_offers_every_matching_design(client, app, seed):
    _uniform_collection(app, seed)
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get(
        f'/shop/customize/{seed["hoodie_id"]}?catalog_section=fan'
    ).get_data(as_text=True)
    assert 'Pick the jersey look or a matching design.' in html
    assert 'Group logos: tap one to use' in html
    assert 'Jersey Logo' not in html
    assert str(seed['free_design_id']) in html
    assert str(seed['fee_4_design_id']) in html


def test_uniform_cart_uses_the_locked_jersey_logo(client, app, seed):
    _uniform_collection(app, seed)
    client.get(f'/c/{seed["collection_slug"]}')
    response = client.post('/cart/add', data={
        'product_id': str(seed['tee_id']),
        'color': 'Black',
        'size': 'M',
        'quantity': '1',
        'catalog_section': 'uniform',
        'uniform_kit': 'home',
        'design_id': str(seed['fee_4_design_id']),
    })
    assert response.status_code == 200
    with client.session_transaction() as sess:
        item = sess['cart'][0]
    assert int(item['design_id']) == seed['free_design_id']


def test_jersey_logo_falls_back_to_the_first_allowed_design(app, seed):
    from models import Collection
    from utils.group_orders import resolve_uniform_design_id

    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.allowed_design_ids = json.dumps([
            seed['fee_4_design_id'], seed['free_design_id'],
        ])
        collection.team_store_config = json.dumps({
            'version': 1,
            'uniform': {
                'enabled': True,
                'product_id': seed['tee_id'],
                'home_color': 'Black',
                'away_color': 'White',
            },
            'fan_product_ids': [],
        })
        db.session.commit()
        collection = db.session.get(Collection, seed['collection_id'])
        assert resolve_uniform_design_id(collection, 'home') == seed['fee_4_design_id']
        assert resolve_uniform_design_id(collection, 'away') == seed['fee_4_design_id']


def collection_slug_for(name, app):
    with app.app_context():
        return Collection.query.filter_by(name=name).one().slug


def _checkout_html_for_kind(client, seed, app, kind):
    from models import Collection
    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.group_kind = kind
        db.session.commit()
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']
    resp = client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black',
        'quantity': 1, 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    })
    assert resp.status_code == 200
    return client.get('/checkout/').get_data(as_text=True)


def test_school_checkout_asks_for_grade(client, seed, app):
    html = _checkout_html_for_kind(client, seed, app, 'school')
    assert 'Send Home With Child' in html
    assert 'sent home from school' in html
    assert 'id="child_grade"' in html
    assert 'Teacher name' in html


def test_team_checkout_offers_send_home_without_grade(client, seed, app):
    html = _checkout_html_for_kind(client, seed, app, 'team')
    assert 'Send Home With Child' in html
    assert 'sent home from school' not in html
    assert 'id="child_grade"' not in html
    assert 'Coach name' in html


def test_other_checkout_hides_send_home(client, seed, app):
    html = _checkout_html_for_kind(client, seed, app, 'other')
    assert 'Send Home With Child' not in html
    assert 'id="send_home_with_child"' not in html

