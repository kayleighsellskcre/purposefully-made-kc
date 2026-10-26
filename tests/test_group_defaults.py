"""New group orders start with our recommended styles and colors; everything else stays available."""
import json
import re

from models import Collection, Product, ProductColorVariant, db
from tests.conftest import CUSTOMER_EMAIL
from utils.group_defaults import (
    DEFAULT_STYLES, default_fan_color_keys, default_style_ids, favorite_colors, is_tie_dye,
)
from utils.group_order_templates import group_order_templates

SIZES = json.dumps(['S', 'M', 'L'])


def test_favorite_colors_are_the_ones_we_recommend():
    names = ['Natural', 'Heather Natural', 'Navy', 'Heather Navy', 'Athletic Heather', 'Deep Heather',
             'Dark Grey Heather', 'Solid Black Blend', 'Solid White Blend', 'Solid Red Blend', 'Heather Red',
             'Pink', 'Mint', 'Heather Mauve']
    assert favorite_colors(names) == ['Natural', 'Heather Natural', 'Navy', 'Heather Navy', 'Athletic Heather',
                                      'Deep Heather', 'Dark Grey Heather', 'Solid Black Blend', 'Solid White Blend',
                                      'Solid Red Blend', 'Heather Red']
    assert favorite_colors(['Dark Gray Heather', 'natural heather', 'NAVY']) == ['Dark Gray Heather', 'natural heather', 'NAVY']


def test_plain_black_white_and_red_are_used_only_when_there_is_no_solid_blend():
    assert favorite_colors(['Black', 'White', 'Red', 'Navy']) == ['Navy', 'Black', 'White', 'Red']
    assert favorite_colors(['Black', 'Solid Black Blend', 'White', 'Red']) == ['Solid Black Blend', 'White', 'Red']
    assert favorite_colors(['Black', 'White', 'Solid White Blend', 'Red', 'Solid Red Blend']) == ['Solid White Blend', 'Solid Red Blend', 'Black']
    assert favorite_colors(['Black', 'Solid Black Blend', 'White', 'Solid White Blend', 'Red', 'Solid Red Blend']) == \
        ['Solid Black Blend', 'Solid White Blend', 'Solid Red Blend']


def test_a_style_with_none_of_these_colors_is_left_unrestricted():
    assert favorite_colors(['Pink', 'Mint', 'Orange']) == []


def test_tie_dye_starts_with_rainbow_pastel_rainbow_and_neon_rainbow():
    names = ['Black', 'Rainbow', 'Pastel Rainbow', 'Neon Rainbow', 'USA Rainbow', 'Ocean Rainbow', 'Royal', 'Navy']
    assert favorite_colors(names, tie_dye=True) == ['Rainbow', 'Pastel Rainbow', 'Neon Rainbow']
    assert is_tie_dye(Product(name='Port & Company Tie-Dye Tee', style_number='PC147'))
    assert not is_tie_dye(Product(name='Unisex Jersey Short Sleeve Tee', style_number='BC3001'))


def _p(style, name, age='adult', category='Tee', brand='Bella+Canvas', active=True):
    p = Product(style_number=style, name=name, category=category, age_group=age, brand=brand, base_price=20.0,
                wholesale_cost=5.0, is_active=active, available_sizes=SIZES, available_colors=json.dumps(['Black']))
    db.session.add(p)
    db.session.flush()
    return p


def test_the_styles_that_start_checked_are_the_recommended_set(app, seed):
    with app.app_context():
        made = {
            'adult_tee': _p('BC3001', 'Unisex Jersey Short Sleeve Tee'),
            'youth_tee': _p('BC3001Y', 'Youth Jersey Short Sleeve Tee', 'youth'),
            'toddler_tee': _p('3001T', 'Toddler Jersey Tee', 'toddler'),
            'other_adult': _p('CC1717', 'Comfort Colors Garment-Dyed Heavyweight Tee', brand='Comfort Colors'),
            'other_youth': _p('PRM15YSB', 'Youth Lightweight Hooded Sweatshirt', 'youth', 'Hoodie', 'Independent Trading Co.'),
            'tie_dye': _p('PC147', 'Port & Company Tie-Dye Tee', brand='Port & Company'),
            'vneck': _p('BC3005', 'Unisex Jersey Short Sleeve V-Neck Tee', category='V-Neck'),
            'tank': _p('BC8800', "Women's Flowy Racerback Tank", category='Tank'),
        }
        products = list(made.values())
        ids = lambda *keys: [made[k].id for k in keys]
        assert default_style_ids(products) == ids('adult_tee', 'youth_tee', 'toddler_tee', 'tie_dye', 'vneck', 'tank')
        assert default_style_ids(products, ('adult',)) == ids('adult_tee', 'tie_dye', 'vneck', 'tank')
        assert default_style_ids(products, ('youth', 'toddler', 'baby')) == ids('youth_tee', 'toddler_tee')
        assert 'CC1717' not in DEFAULT_STYLES and made['other_adult'].id not in default_style_ids(products)


def test_every_group_type_starts_with_the_recommended_set_adults_or_kids_only_where_it_says(app, seed):
    with app.app_context():
        adult = _p('BC3719', 'Unisex Sponge Fleece Pullover Hoodie', category='Hoodie')
        youth = _p('BC3719Y', 'Youth Sponge Fleece Pullover Hoodie', 'youth', 'Hoodie')
        other = _p('IND4000', 'Heavyweight Hooded Sweatshirt', category='Hoodie', brand='Independent Trading Co.')
        templates = {t['key']: set(t['product_ids']) for t in group_order_templates([adult, youth, other])}
        both = {str(adult.id), str(youth.id)}
        for key in ('school_spirit', 'sports_team', 'family_vacation', 'organization_club', 'event', 'mixed_ages'):
            assert templates[key] == both, key
        assert templates['adults_only'] == {str(adult.id)} and templates['business'] == {str(adult.id)}
        assert templates['kids_only'] == {str(youth.id)}
        assert str(other.id) not in set().union(*templates.values())          # still on the page, just not checked


def test_a_catalog_without_the_recommended_styles_keeps_each_types_own_picks(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        templates = {t['key']: t['product_ids'] for t in group_order_templates([tee])}
        assert templates['school_spirit'] == [str(tee.id)]


def _variant(product, name, hex_='#000000'):
    db.session.add(ProductColorVariant(product_id=product.id, color_name=name, color_hex=hex_,
                                       front_image_url='/static/img/logo.png', size_inventory=json.dumps({'M': 5})))


def test_the_create_form_opens_on_our_recommended_styles_and_colors(app, seed, customer_client):
    with app.app_context():
        hoodie = _p('BC3719', 'Unisex Sponge Fleece Pullover Hoodie', category='Hoodie')
        tie = _p('PC147', 'Port & Company Tie-Dye Tee', brand='Port & Company')
        plain = _p('IND4000', 'Heavyweight Hooded Sweatshirt', category='Hoodie', brand='Independent Trading Co.')
        for name in ('Black', 'Solid Black Blend', 'Heather Navy', 'Navy', 'Pink', 'Athletic Heather', 'White', 'Solid White Blend'):
            _variant(hoodie, name)
        for name in ('Rainbow', 'Pastel Rainbow', 'Neon Rainbow', 'USA Rainbow', 'Black'):
            _variant(tie, name)
        for name in ('Mint', 'Pink'):
            _variant(plain, name)
        db.session.commit()
        hoodie_id, tie_id, plain_id = hoodie.id, tie.id, plain.id
    html = customer_client.get('/shop/group-orders/create?type=school_spirit').get_data(as_text=True)
    data = json.loads(re.search(r'id="fanColorData">(.*?)</script>', html, re.S).group(1))
    checked = set(data['checked'])
    assert {f'p:{hoodie_id}||Solid Black Blend', f'p:{hoodie_id}||Heather Navy', f'p:{hoodie_id}||Navy',
            f'p:{hoodie_id}||Athletic Heather', f'p:{hoodie_id}||Solid White Blend'} <= checked
    assert f'p:{hoodie_id}||Black' not in checked and f'p:{hoodie_id}||White' not in checked   # the solid blends win
    assert f'p:{hoodie_id}||Pink' not in checked
    assert {f'p:{tie_id}||Rainbow', f'p:{tie_id}||Pastel Rainbow', f'p:{tie_id}||Neon Rainbow'} <= checked
    assert f'p:{tie_id}||USA Rainbow' not in checked and f'p:{tie_id}||Black' not in checked
    assert not any(k.startswith(f'p:{plain_id}||') for k in checked)          # none of our colors there: left unrestricted
    assert 'name="color_restriction_mode" value="restrict" checked' in html
    assert 'value="all" checked' not in html and 'Our recommended colors' in html
    templates = json.loads(re.search(r'group_templates\s*=\s*(\{.*?\});', html, re.S).group(1)) if 'group_templates =' in html else None
    assert templates is None or str(hoodie_id) in json.dumps(templates)


def test_other_styles_and_colors_are_still_there_to_add(app, seed, customer_client):
    with app.app_context():
        other = _p('IND4000', 'Heavyweight Hooded Sweatshirt', category='Hoodie', brand='Independent Trading Co.')
        _variant(other, 'Pink')
        db.session.commit()
        other_id = other.id
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert f'value="{other_id}"' in html and f'name="products" value="{other_id}" checked' not in html
    data = json.loads(re.search(r'id="fanColorData">(.*?)</script>', html, re.S).group(1))
    assert str(other_id) in data['picker']['products']


def test_a_store_made_from_the_defaults_saves_the_checked_colors(app, seed, customer_client):
    with app.app_context():
        hoodie = _p('BC3719', 'Unisex Sponge Fleece Pullover Hoodie', category='Hoodie')
        for name in ('Black', 'Heather Navy', 'Pink'):
            _variant(hoodie, name)
        db.session.commit()
        pid = hoodie.id
    resp = customer_client.post('/shop/group-orders/create', data={
        'name': 'Defaults Store', 'payment_mode': 'each_pays', 'products': [str(pid)], 'group_kind': 'school',
        'color_restriction_mode': 'restrict', 'allowed_colors': [f'p:{pid}||Black', f'p:{pid}||Heather Navy'],
        'allowed_designs': [str(seed['free_design_id'])], 'allowed_placements': ['center_chest']},
        content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        store = Collection.query.filter_by(name='Defaults Store').first()
        saved = json.loads(store.allowed_colors)
        assert sorted(saved[f'p:{pid}']) == ['Black', 'Heather Navy']
