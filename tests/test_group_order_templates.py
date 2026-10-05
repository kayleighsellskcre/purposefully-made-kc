import json
import re
from types import SimpleNamespace

from utils.group_order_templates import GROUP_TEMPLATES, group_order_templates


def _product(pid, style, age, category, fit='Unisex'):
    return SimpleNamespace(
        id=pid, style_number=style, display_age=age, display_category=category, display_fit=fit,
    )


CATALOG = [
    _product(1, 'BC3001', 'adult', 'Tee'),
    _product(2, 'BC3001Y', 'youth', 'Tee'),
    _product(3, '3001T', 'toddler', 'Tee'),
    _product(4, '100B', 'baby', 'Onesie'),
    _product(5, 'BC3719', 'adult', 'Hoodie'),
    _product(6, 'BC3719Y', 'youth', 'Hoodie'),
    _product(7, 'BC8800', 'adult', 'Tank', "Women's"),
    _product(8, 'BC3480', 'adult', 'Tank'),
    _product(9, 'DM130', 'adult', 'Tee'),
]


def _by_key(templates):
    return {t['key']: t for t in templates}


def test_every_group_type_from_the_request_is_offered():
    labels = [t['label'] for t in GROUP_TEMPLATES]
    assert labels == [
        'Family Vacation', 'School Spirit Wear', 'Sports Team', 'Business / Corporate',
        'Organization / Club', 'Event', 'Kids Only', 'Adults Only', 'Mixed Ages',
    ]


def test_customer_copy_has_no_em_dashes():
    for t in GROUP_TEMPLATES:
        text = ' '.join([t['label'], t['blurb'], t['description'], t['watch'], *t['tips']])
        assert '\u2014' not in text, t['key']


def test_family_vacation_matches_every_age():
    family = _by_key(group_order_templates(CATALOG))['family_vacation']
    assert family['product_ids'][:4] == ['1', '2', '3', '4']
    assert 'slots' not in family


def test_kids_only_never_includes_adult_styles():
    ages = {p.id: p.display_age for p in CATALOG}
    kids = _by_key(group_order_templates(CATALOG))['kids_only']
    assert kids['product_ids']
    assert all(ages[int(pid)] != 'adult' for pid in kids['product_ids'])


def test_adults_only_never_includes_kids_styles():
    ages = {p.id: p.display_age for p in CATALOG}
    adults = _by_key(group_order_templates(CATALOG))['adults_only']
    assert adults['product_ids']
    assert all(ages[int(pid)] == 'adult' for pid in adults['product_ids'])


def test_retired_style_falls_back_to_same_age_and_category():
    catalog = [p for p in CATALOG if p.style_number != 'BC3001'] + [_product(20, 'PC147', 'adult', 'Tee')]
    school = _by_key(group_order_templates(catalog))['school_spirit']
    assert school['product_ids'][0] == '9'


def test_fallback_skips_womens_fit_unless_asked():
    catalog = [_product(7, 'BC8800', 'adult', 'Tank', "Women's"), _product(8, 'BC3480', 'adult', 'Tank')]
    event = _by_key(group_order_templates(catalog))['event']
    assert event['product_ids'] == ['8', '7']


def test_sports_team_sets_team_kind_and_name_number_back():
    sports = _by_key(group_order_templates(CATALOG))['sports_team']
    assert sports['kind'] == 'team'
    assert sports['back'] == 'name_number'
    assert _by_key(group_order_templates(CATALOG))['school_spirit']['kind'] == 'school'


def test_no_style_is_picked_twice_in_one_template():
    for t in group_order_templates(CATALOG):
        assert len(t['product_ids']) == len(set(t['product_ids'])), t['key']


def _template_data(html):
    match = re.search(r'<script type="application/json" id="groupTemplateData">(.*?)</script>', html, re.S)
    assert match, 'group template data missing'
    return json.loads(match.group(1))


def test_create_page_shows_group_type_picker(customer_client, seed):
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'What are you planning?' in html
    assert 'name="group_template" value="family_vacation"' in html
    data = _by_key(_template_data(html))
    assert str(seed['tee_id']) in data['family_vacation']['product_ids']
    assert str(seed['youth_id']) in data['family_vacation']['product_ids']
    assert str(seed['tee_id']) not in data['kids_only']['product_ids']


def test_create_page_preselects_type_from_query(customer_client, seed):
    html = customer_client.get('/shop/group-orders/create?type=sports_team').get_data(as_text=True)
    assert 'data-selected="sports_team"' in html
    html = customer_client.get('/shop/group-orders/create?type=bogus').get_data(as_text=True)
    assert 'data-selected=""' in html


def test_admin_create_page_shows_group_type_picker(admin_client, seed):
    html = admin_client.get('/admin/collections/add').get_data(as_text=True)
    assert 'What are you planning?' in html


def test_group_template_field_does_not_break_create(customer_client, seed, app):
    response = customer_client.post(
        '/shop/group-orders/create',
        data={
            'name': 'Hayes Family Beach Trip',
            'group_template': 'family_vacation',
            'products': [str(seed['tee_id'])],
            'allowed_placements': ['center_chest'],
            'group_kind': 'other',
        },
        content_type='multipart/form-data', follow_redirects=True,
    )
    assert response.status_code == 200
    from models import Collection
    with app.app_context():
        assert Collection.query.filter_by(name='Hayes Family Beach Trip').first() is not None
