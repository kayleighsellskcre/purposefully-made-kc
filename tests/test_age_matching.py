import re
from types import SimpleNamespace

from models import db, Collection, Product
from utils.group_orders import build_store_cards
from utils.product_filters import age_families


def _product(pid, style, age, colors=(), sizes=(), price=30.0, brand='Bella+Canvas'):
    return SimpleNamespace(
        id=pid, style_number=style, display_age=age, display_brand=brand,
        carousel_colors=[{'color_name': c} for c in colors],
        available_sizes_list=list(sizes), listed_price=price, base_price=price,
    )


def test_age_families_put_adult_first_even_when_kids_style_comes_first():
    youth = _product(2, 'BC3001Y', 'youth')
    adult = _product(1, 'BC3001', 'adult')
    hoodie = _product(3, 'BC3719', 'adult')
    families = age_families([youth, hoodie, adult])
    assert [[m.id for m in f] for f in families] == [[3], [1, 2]]


def test_age_families_never_join_different_brands():
    adult = _product(1, '3001', 'adult', brand='Bella+Canvas')
    youth = _product(2, '3001Y', 'youth', brand='Gildan')
    assert [[m.id for m in f] for f in age_families([adult, youth])] == [[1], [2]]


def test_store_cards_fold_kids_sizes_into_the_adult_card():
    adult = _product(1, 'BC3001', 'adult', ['Navy', 'Black'], ['S', 'M', 'L', 'XL', '3XL'], 30)
    youth = _product(2, 'BC3001Y', 'youth', ['Navy', 'Black', 'Pink'], ['YS', 'YM', 'YL', 'YXL'], 24)
    toddler = _product(3, '3001T', 'toddler', ['Navy', 'Black'], ['2T', '3T', '4T', '5T'], 22)
    cards, note = build_store_cards([adult, youth, toddler])
    assert cards == [adult]
    family = adult.age_family
    assert family['labels'] == 'Adult + Youth + Toddler'
    assert family['ages'] == 'adult youth toddler'
    assert family['sizes'] == 'S\u20133XL \u00b7 YS\u2013YXL \u00b7 2T\u20135T'
    assert family['price_from'] == 22
    assert family['price_varies'] is True
    assert family['colors_match'] is True
    assert note == 'All sizes come in the same colors, so kids and adults will match!'


def test_store_note_stays_honest_when_kids_style_has_fewer_colors():
    adult = _product(1, 'BC3001', 'adult', ['Navy', 'Black', 'Red'])
    youth = _product(2, 'BC3001Y', 'youth', ['Navy', 'Black'])
    cards, note = build_store_cards([adult, youth])
    assert adult.age_family['colors_match'] is False
    assert adult.age_family['shared_colors'] == 2
    assert 'will match' not in note


def test_store_without_kids_styles_has_no_note():
    cards, note = build_store_cards([_product(1, 'BC3001', 'adult', ['Navy'])])
    assert note is None
    assert cards[0].age_family is None


def _add_youth_to_store(app, seed):
    with app.app_context():
        group = db.session.get(Collection, seed['collection_id'])
        group.products.append(db.session.get(Product, seed['youth_id']))
        db.session.commit()


def test_group_store_shows_one_card_for_youth_and_adult(client, seed, app):
    _add_youth_to_store(app, seed)
    html = client.get(f"/c/{seed['collection_slug']}").get_data(as_text=True)
    assert 'Adult + Youth' in html
    assert html.count('<article class="design-card') == 1
    assert re.search(r'family-match-label">\s*(Same colors in every size|\d+ colors? comes? in every size)', html)
    assert 'class="age-matching-note"' in html
    assert f"/shop/customize/{seed['youth_slug']}" not in html


def test_customize_page_offers_age_switch_inside_group_store(client, seed, app):
    _add_youth_to_store(app, seed)
    client.get(f"/c/{seed['collection_slug']}")
    html = client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'class="age-switch"' in html
    assert f"/shop/customize/{seed['youth_slug']}" in html
    assert 'pmkc-group-color-' in html


def test_customize_page_has_no_age_switch_outside_group_store(client, seed, app):
    _add_youth_to_store(app, seed)
    html = client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'class="age-switch"' not in html
