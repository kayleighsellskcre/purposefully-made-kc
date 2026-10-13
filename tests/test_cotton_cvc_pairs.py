"""Cotton and CVC versions of one shirt are shown as ONE item; the color decides the style."""
import json
import re
from types import SimpleNamespace as P

from models import Collection, Product, ProductColorVariant, db
from utils.style_pairs import blend_pairs, find_partner, is_blend, style_parts

SIZES = ['S', 'M', 'L', 'XL', '2XL']


# ── Which styles pair up ─────────────────────────────────────────────────────

def test_cotton_and_cvc_styles_pair_up_even_with_brand_letters_and_age_letters():
    items = [
        P(id=1, style_number='BC3001', brand='Bella+Canvas'), P(id=2, style_number='BC3001CVC', brand='Bella+Canvas'),
        P(id=3, style_number='3001Y', brand='BELLA + CANVAS'), P(id=4, style_number='3001YCVC', brand='BELLA + CANVAS'),
        P(id=5, style_number='6400CVC', brand='Bella+Canvas'),           # no cotton twin
        P(id=6, style_number='3001CVC', brand='Gildan'),                  # other brand: never paired
    ]
    assert sorted((a.id, b.id) for a, b in blend_pairs(items)) == [(1, 2), (3, 4)]
    assert style_parts('BC3001CVC') == ('3001', '', True) and is_blend(items[1]) and not is_blend(items[0])


def test_youth_never_pairs_with_adult():
    items = [P(id=1, style_number='3001', brand='Bella+Canvas'), P(id=2, style_number='3001YCVC', brand='Bella+Canvas')]
    assert blend_pairs(items) == []


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cvc(app, seed, price=34.0, sizes=None):
    with app.app_context():
        blend = Product(style_number='3001CVC', name='Unisex Heather CVC Short Sleeve Tee', category='Tee',
                        age_group='adult', base_price=price, wholesale_cost=7.0, is_active=True,
                        available_sizes=json.dumps(sizes or SIZES),
                        available_colors=json.dumps(['Heather Grey']))
        db.session.add(blend)
        db.session.flush()
        db.session.add(ProductColorVariant(
            product_id=blend.id, color_name='Heather Grey', color_hex='#b0b0b0',
            front_image_url='/static/img/logo.png', size_inventory=json.dumps({s: 40 for s in (sizes or SIZES)})))
        db.session.commit()
        return blend.id, blend.slug


def _cards(html):
    """{color: attributes} for every color card on a customize page."""
    out = {}
    for m in re.finditer(r'<div class="color-card"(.*?)onclick="selectColor', html, re.S):
        attrs = dict(re.findall(r'data-([\w-]+)="([^"]*)"', m.group(1)))
        out[attrs['color']] = attrs
    return out


# ── One tile in the shop ─────────────────────────────────────────────────────

def test_the_shop_shows_one_tile_with_both_fabrics_colors(client, app, seed):
    _, blend_slug = _cvc(app, seed)
    html = client.get('/shop/').get_data(as_text=True)
    assert f"/shop/customize/{seed['tee_slug']}" in html
    assert f'/shop/customize/{blend_slug}' not in html                  # no second tile
    assert 'Heather Grey' in html                                        # its color rides on the cotton tile


def test_a_heather_color_search_finds_the_combined_shirt(client, app, seed):
    _, blend_slug = _cvc(app, seed)
    html = client.get('/shop/?q=heather').get_data(as_text=True)
    assert f"/shop/customize/{seed['tee_slug']}" in html


def test_a_cvc_style_with_no_cotton_twin_still_shows_on_its_own(client, app, seed):
    with app.app_context():
        lone = Product(style_number='6400CVC', name='Womens Relaxed Heather CVC Tee', category='Tee', age_group='adult',
                       base_price=25, is_active=True, available_sizes=json.dumps(SIZES),
                       available_colors=json.dumps(['Heather Grey']))
        db.session.add(lone)
        db.session.flush()
        db.session.add(ProductColorVariant(product_id=lone.id, color_name='Heather Grey', front_image_url='/static/img/logo.png',
                                           size_inventory=json.dumps({s: 5 for s in SIZES})))
        db.session.commit()
        slug = lone.slug
    assert f'/shop/customize/{slug}' in client.get('/shop/').get_data(as_text=True)


# ── One item on the customize page ───────────────────────────────────────────

def test_the_customize_page_lists_every_color_and_each_remembers_its_style(client, app, seed):
    blend_id, _ = _cvc(app, seed, price=34.0)
    html = client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    cards = _cards(html)
    assert {'Black', 'White', 'Navy', 'Heather Grey'} <= set(cards) or {'Black', 'White', 'Heather Grey'} <= set(cards)
    assert cards['Black']['product-id'] == str(seed['tee_id']) and cards['Black']['price'] == '30.0'
    assert cards['Heather Grey']['product-id'] == str(blend_id) and cards['Heather Grey']['price'] == '34.0'
    assert cards['Heather Grey']['style'] == '3001CVC' and 'blend' in cards['Heather Grey']['fabric'].lower()
    assert 'formData.append(\'product_id\', state.productId)' in html


def test_the_cvc_page_shows_the_cotton_colors_too(client, app, seed):
    _, blend_slug = _cvc(app, seed)
    cards = _cards(client.get(f'/shop/customize/{blend_slug}').get_data(as_text=True))
    assert 'Heather Grey' in cards and 'Black' in cards and cards['Black']['product-id'] == str(seed['tee_id'])


def test_a_shirt_with_no_twin_looks_exactly_as_before(client, seed):
    html = client.get(f"/shop/customize/{seed['hoodie_slug']}").get_data(as_text=True)
    assert 'data-product-id=' not in html


def test_sizes_from_both_fabrics_are_offered(client, app, seed):
    _cvc(app, seed, sizes=['S', 'M', 'L', 'XL', '2XL', '3XL'])
    html = client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'data-size="3XL"' in html


def test_the_page_never_breaks_if_merging_fails(client, app, seed, monkeypatch):
    _cvc(app, seed)
    monkeypatch.setattr('utils.style_pairs.find_partner', lambda p: (_ for _ in ()).throw(RuntimeError('boom')))
    resp = client.get(f"/shop/customize/{seed['tee_slug']}")
    assert resp.status_code == 200 and 'data-product-id=' not in resp.get_data(as_text=True)


# ── The right style goes in the cart ─────────────────────────────────────────

def test_a_heather_color_adds_the_cvc_style(client, app, seed):
    blend_id, _ = _cvc(app, seed, price=34.0)
    resp = client.post('/cart/add', data={'product_id': blend_id, 'size': 'M', 'color': 'Heather Grey',
                                          'quantity': 1, 'placement': 'center_chest'})
    assert resp.get_json().get('success'), resp.get_json()
    with client.session_transaction() as sess:
        cart = sess['cart']
    assert cart[0]['product_id'] == blend_id          # priced from the CVC style itself, not the cotton one


def test_find_partner_works_in_both_directions(app, seed):
    blend_id, _ = _cvc(app, seed)
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        blend = db.session.get(Product, blend_id)
        assert find_partner(tee).id == blend_id
        assert find_partner(blend).id == seed['tee_id']
        assert find_partner(db.session.get(Product, seed['hoodie_id'])) is None


# ── Group stores only combine styles the organizer chose ─────────────────────

def _put_in_store(app, seed, product_ids, fan_ids):
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.products = [db.session.get(Product, i) for i in product_ids]
        coll.team_store_config = json.dumps({'version': 1, 'uniform': {'enabled': False}, 'fan_product_ids': fan_ids})
        db.session.commit()
        return coll.slug


def test_a_group_store_with_both_styles_combines_them(client, app, seed):
    blend_id, _ = _cvc(app, seed)
    slug = _put_in_store(app, seed, [seed['tee_id'], blend_id], [seed['tee_id'], blend_id])
    client.get(f'/c/{slug}')
    cards = _cards(client.get(f"/shop/customize/{seed['tee_slug']}?catalog_section=fan").get_data(as_text=True))
    assert 'Heather Grey' in cards and cards['Heather Grey']['product-id'] == str(blend_id)


def test_a_group_store_that_only_chose_cotton_never_shows_heather(client, app, seed):
    blend_id, _ = _cvc(app, seed)
    slug = _put_in_store(app, seed, [seed['tee_id']], [seed['tee_id']])
    client.get(f'/c/{slug}')
    cards = _cards(client.get(f"/shop/customize/{seed['tee_slug']}?catalog_section=fan").get_data(as_text=True))
    assert 'Heather Grey' not in cards
    resp = client.post('/cart/add', data={'product_id': blend_id, 'size': 'M', 'color': 'Heather Grey', 'quantity': 1,
                                          'placement': 'center_chest', 'catalog_section': 'fan'})
    with client.session_transaction() as sess:
        assert not any(i['product_id'] == blend_id and i.get('collection_id') for i in sess.get('cart') or [])


def test_a_group_store_shows_one_tile_for_a_chosen_pair(client, app, seed):
    blend_id, blend_slug = _cvc(app, seed)
    slug = _put_in_store(app, seed, [seed['tee_id'], blend_id], [seed['tee_id'], blend_id])
    html = client.get(f'/c/{slug}').get_data(as_text=True)
    assert f"/shop/customize/{seed['tee_slug']}" in html
    assert f'/shop/customize/{blend_slug}' not in html


def test_a_group_store_with_only_the_blend_chosen_still_shows_it(client, app, seed):
    blend_id, blend_slug = _cvc(app, seed)
    slug = _put_in_store(app, seed, [blend_id], [blend_id])
    html = client.get(f'/c/{slug}').get_data(as_text=True)
    assert f'/shop/customize/{blend_slug}' in html


# ── Group-order forms: one shirt, both fabrics ───────────────────────────────

def _store_named(app, name):
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        from utils.group_orders import team_store_config
        return coll.id, [p.id for p in coll.products], team_store_config(coll)['fan_product_ids'], coll.allowed_colors


def test_the_create_form_lists_one_card_for_the_pair(admin_client, app, seed):
    blend_id, _ = _cvc(app, seed)
    html = admin_client.get('/admin/collections/add').get_data(as_text=True)
    assert f'name="products" value="{seed["tee_id"]}"' in html
    assert f'name="products" value="{blend_id}"' not in html
    assert 'Includes heather (cotton/poly blend) colors' in html


def test_choosing_the_cotton_shirt_in_the_form_saves_both_styles(customer_client, app, seed):
    from tests.test_group_orders import _base_form, _post
    blend_id, _ = _cvc(app, seed)
    resp = _post(customer_client, _base_form(seed, name='Pair Group', products=[str(seed['tee_id'])]))
    assert resp.status_code == 200
    _cid, products, fan_ids, _colors = _store_named(app, 'Pair Group')
    assert set(products) == {seed['tee_id'], blend_id}


def test_the_edit_form_shows_one_checked_card_and_unticking_it_removes_both(admin_client, app, seed):
    from tests.test_jersey_and_fan_wear import _save_edit
    from tests.test_group_orders import _base_form, _post
    from tests.conftest import ADMIN_EMAIL, _login
    blend_id, _ = _cvc(app, seed)
    admin_client.post('/admin/collections/add', data={
        'name': 'Pair Edit', 'products': [str(seed['tee_id'])], 'group_kind': 'other', 'is_active': 'on'},
        follow_redirects=True)
    cid, products, _f, _c = _store_named(app, 'Pair Edit')
    assert set(products) == {seed['tee_id'], blend_id}
    html = admin_client.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert re.search(rf'name="products" value="{seed["tee_id"]}"\s+checked', html)
    assert f'name="products" value="{blend_id}"' not in html
    _save_edit(admin_client, app, lambda d: d.update(products=[str(seed['hoodie_id'])]), name='Pair Edit')
    _cid, products, _f, _c = _store_named(app, 'Pair Edit')
    assert blend_id not in products and seed['tee_id'] not in products


def test_a_store_that_only_chose_the_blend_keeps_it_visible_and_alone(admin_client, app, seed):
    from tests.test_jersey_and_fan_wear import _save_edit
    blend_id, _ = _cvc(app, seed)
    admin_client.post('/admin/collections/add', data={
        'name': 'Blend Only', 'products': [str(blend_id)], 'group_kind': 'other', 'is_active': 'on'},
        follow_redirects=True)
    cid, products, _f, _c = _store_named(app, 'Blend Only')
    assert products == [blend_id]
    html = admin_client.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert re.search(rf'name="products" value="{blend_id}"\s+checked', html)
    _save_edit(admin_client, app, lambda d: None, name='Blend Only')
    assert _store_named(app, 'Blend Only')[1] == [blend_id]            # saving never adds the cotton shirt


def test_colors_picked_for_the_cotton_shirt_apply_to_its_twin(admin_client, app, seed):
    from utils.group_orders import allowed_colors_for_product, product_color_key
    from utils.style_pairs import replicate_blend_color_picks
    blend_id, _ = _cvc(app, seed)
    saved = replicate_blend_color_picks(json.dumps({product_color_key(seed['tee_id']): ['Black', 'Heather Grey']}))
    with app.app_context():
        assert allowed_colors_for_product(db.session.get(Product, blend_id), saved) == {'Black', 'Heather Grey'}
        assert allowed_colors_for_product(db.session.get(Product, seed['tee_id']), saved) == {'Black', 'Heather Grey'}


def test_the_color_picker_lists_heather_colors_on_the_cotton_card(app, seed):
    from utils.product_filters import load_group_order_form_catalog
    blend_id, _ = _cvc(app, seed)
    with app.app_context():
        picker = load_group_order_form_catalog()['fan_color_picker']
        labels = {picker['palette'][i][0] for i in picker['products'][str(seed['tee_id'])]}
    assert 'Heather Grey' in labels and 'Black' in labels


def test_the_org_fan_wear_page_uses_one_card_and_saves_both(admin_client, app, seed):
    from tests.test_org_fan_wear import _build, _org_slug
    from tests.test_org_fan_store import _fan
    blend_id, _ = _cvc(app, seed)
    a, b, c = _build(admin_client, app, seed)
    url = f'/org/{_org_slug(app)}/fan-wear'
    html = admin_client.get(url).get_data(as_text=True)
    assert f'name="products" value="{seed["tee_id"]}"' in html and f'name="products" value="{blend_id}"' not in html
    admin_client.post(url, data={'products': [str(seed['tee_id'])], 'design_ids': [str(a), str(b), str(c)],
                                 'fan_designs': [str(a), str(b), str(c)]}, follow_redirects=True)
    fan_id, _slug = _fan(app)
    with app.app_context():
        from utils.group_orders import team_store_config
        ids = team_store_config(db.session.get(Collection, fan_id))['fan_product_ids']
    assert ids == [seed['tee_id'], blend_id]


def test_the_no_mockup_placeholder_is_the_friendly_picture_day_card(client):
    resp = client.get('/static/img/placeholder-product.svg')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'skipped picture day' in body and 'you can still order' in body and 'No image' not in body


def test_the_same_style_number_from_two_brands_is_never_one_family():
    from utils.product_filters import group_products_by_family
    bella = P(id=1, style_number='BC3001', brand='Bella+Canvas', name='Bella Tee', display_age='adult')
    bella_youth = P(id=2, style_number='3001Y', brand='BELLA + CANVAS', name='Bella Youth Tee', display_age='youth')
    indy = P(id=3, style_number='SS3001Y', brand='Independent Trading Co.', name='Youth Sweatshirt', display_age='youth')
    families = group_products_by_family([bella, bella_youth, indy])
    groups = sorted(sorted(m.id for m in f['members']) for f in families)
    assert groups == [[1, 2], [3]]


def test_a_family_member_with_no_brand_still_joins_its_family():
    from utils.product_filters import group_products_by_family
    adult = P(id=1, style_number='BC3001', brand='Bella+Canvas', name='Tee', display_age='adult')
    toddler = P(id=2, style_number='3001T', brand='', name='Toddler Tee', display_age='toddler')
    families = group_products_by_family([adult, toddler])
    assert [sorted(m.id for m in f['members']) for f in families] == [[1, 2]]
