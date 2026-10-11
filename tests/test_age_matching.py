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


def test_store_cards_keep_each_age_as_its_own_card():
    """Adult and youth are shown separately so shoppers see exactly what they order."""
    adult = _product(1, 'BC3001', 'adult', ['Navy', 'Black'], ['S', 'M', 'L', 'XL', '3XL'], 30)
    youth = _product(2, 'BC3001Y', 'youth', ['Navy', 'Black', 'Pink'], ['YS', 'YM', 'YL', 'YXL'], 24)
    cards, note = build_store_cards([adult, youth])
    assert cards == [adult, youth]
    assert adult.age_family is None and youth.age_family is None
    assert note is None


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
    assert html.count('<article class="design-card') == 1
    assert 'design-card--family' in html
    assert 'coll-family-members-tpl' in html          # the age-group picker lives on the card


def test_customize_page_still_opens_for_a_family_style_inside_a_group_store(client, seed, app):
    _add_youth_to_store(app, seed)
    client.get(f"/c/{seed['collection_slug']}")
    resp = client.get(f"/shop/customize/{seed['tee_slug']}")
    assert resp.status_code == 200
    assert 'Customize' in resp.get_data(as_text=True)


def test_customize_page_has_no_age_switch_outside_group_store(client, seed, app):
    _add_youth_to_store(app, seed)
    html = client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'class="age-switch"' not in html
