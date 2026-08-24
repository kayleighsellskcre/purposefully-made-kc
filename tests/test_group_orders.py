"""The group-order create form, including the 413 that broke it in production."""
import io

from models import db, Collection


def _base_form(seed, **over):
    form = {
        'name': 'Riverview Spirit Wear 2026',
        'products': [str(seed['tee_id'])],
        'allowed_placements': ['center_chest', 'left_chest'],
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
        assert [p.id for p in collection.products] == [seed['tee_id']]


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


def test_the_group_orders_directory_loads(client):
    resp = client.get('/shop/group-orders')
    assert resp.status_code == 200


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
    # Gallery designs (and their delete buttons) must not close the form.
    assert 'name="allowed_designs"' in inner or 'gallery' in html.lower()


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
