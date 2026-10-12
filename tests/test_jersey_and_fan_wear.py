"""A team's jersey can be changed or removed, and the jersey shirt can ALSO be a Fan Wear style."""
import json

from models import Collection
from tests.test_group_order_audit import _slug_of
from tests.test_group_order_roundtrip import _Form
from tests.test_org_fan_wear import _build, _org_slug, _store
from utils.group_orders import team_store_config

TEAM = 'Basketball: Rainbow Cheetahs'     # jersey: the tee (+ youth tee), Home Black, Away White


def _cfg(app, name=TEAM):
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        return team_store_config(coll)


def _save_edit(admin_client, app, change, name=TEAM):
    """Open the real edit page, change what a person would, and press Save."""
    coll_id = _store(app, name)[0]
    page = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    form = _Form()
    form.feed(page)
    data = {}
    for key, value in form.fields:
        data.setdefault(key, []).append(value)
    change(data)
    resp = admin_client.post(f'/admin/collections/{coll_id}/edit', data=data, follow_redirects=True)
    assert resp.status_code == 200
    return coll_id


def _checked_products(admin_client, coll_id):
    page = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    form = _Form()
    form.feed(page)
    return {int(v) for k, v in form.fields if k == 'products'}


# ── The jersey shirt as a Fan Wear style ─────────────────────────────────────

def test_the_jersey_shirt_can_also_be_a_fan_wear_style_and_stays(admin_client, app, seed):
    _build(admin_client, app, seed)
    tee = seed['tee_id']
    assert tee in _cfg(app)['uniform']['product_ids']
    coll_id = _save_edit(admin_client, app, lambda d: d.update(products=[str(tee), str(seed['hoodie_id'])]))
    config = _cfg(app)
    assert tee in config['fan_product_ids'] and seed['hoodie_id'] in config['fan_product_ids']
    assert tee in config['uniform']['product_ids']                      # still the jersey too
    # and it is still ticked when the page is opened again (it used to vanish on save)
    assert tee in _checked_products(admin_client, coll_id)
    # saving again changes nothing
    _save_edit(admin_client, app, lambda d: None)
    assert tee in _cfg(app)['fan_product_ids']


def test_the_store_shows_a_jersey_shirt_in_both_the_jersey_and_fan_wear_sections(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: d.update(products=[str(seed['tee_id']), str(seed['hoodie_id'])]))
    slug = _slug_of(app, TEAM)
    page = client.get(f'/c/{slug}?path=fan').get_data(as_text=True)
    assert f"/shop/customize/{seed['tee_slug']}?catalog_section=fan" in page          # a Fan Wear card
    home = client.get(f'/c/{slug}').get_data(as_text=True)
    assert 'catalog_section=uniform' in home                                          # and still a jersey


def test_a_jersey_shirt_can_be_added_to_the_cart_as_fan_wear(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: d.update(products=[str(seed['tee_id']), str(seed['hoodie_id'])]))
    client.get(f'/c/{_slug_of(app, TEAM)}')
    resp = client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
        'catalog_section': 'fan', 'placement': 'center_chest',
    })
    assert resp.get_json().get('success'), resp.get_json()


def test_the_shared_fan_wear_page_keeps_a_jersey_shirt_for_every_team(admin_client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    tee = seed['tee_id']
    resp = admin_client.post(f'/org/{_org_slug(app)}/fan-wear', data={
        'products': [str(tee), str(seed['hoodie_id'])],
        'design_ids': [str(a), str(b), str(c)], 'fan_designs': [str(a), str(b), str(c)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    for team in ('Basketball', 'Soccer', 'Volleyball'):
        assert tee in _cfg(app, f'{team}: Rainbow Cheetahs')['fan_product_ids'], team
    page = admin_client.get(f'/org/{_org_slug(app)}/fan-wear').get_data(as_text=True)
    assert f'value="{tee}" checked' in page                                            # still ticked next time


# ── Changing, adding and removing the jersey ─────────────────────────────────

def test_the_jersey_can_be_removed_and_fan_wear_stays(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: d.pop('uniform_enabled', None))
    config = _cfg(app)
    assert not config['uniform']['enabled']
    assert config['fan_product_ids']                                                   # Fan Wear is untouched
    assert 'id="uniformSection"' not in client.get(f'/c/{_slug_of(app, TEAM)}').get_data(as_text=True)


def test_the_jersey_style_and_color_can_be_changed(admin_client, app, seed):
    _build(admin_client, app, seed)

    def change(d):
        d.update(uniform_product_id=[str(seed['hoodie_id'])], uniform_youth_product_id=[''],
                 uniform_home_color=['Black'], uniform_away_color=[''],
                 uniform_away_product_id=[''], uniform_away_youth_product_id=[''])
    _save_edit(admin_client, app, change)
    config = _cfg(app)
    assert config['uniform']['enabled'] and config['uniform']['product_ids'] == [seed['hoodie_id']]
    assert config['uniform']['home_color'] == 'Black' and not config['uniform']['away_color']


def test_a_youth_jersey_style_can_be_added(admin_client, app, seed):
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: d.update(uniform_youth_product_id=['']))
    assert seed['youth_id'] not in _cfg(app)['uniform']['product_ids']
    # the Away jersey is adult-only (the youth tee does not come in White), so say so
    _save_edit(admin_client, app, lambda d: d.update(uniform_youth_product_id=[str(seed['youth_id'])],
                                                     uniform_away_youth_product_id=['none']))
    config = _cfg(app)['uniform']
    assert seed['youth_id'] in config['product_ids']
    assert config['away_product_ids'] == [seed['tee_id']]            # no youth Away jersey


def test_the_jersey_can_be_added_back_after_removing_it(admin_client, app, seed):
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: d.pop('uniform_enabled', None))
    assert not _cfg(app)['uniform']['enabled']

    def add(d):
        d.update(uniform_enabled=['on'], uniform_product_id=[str(seed['tee_id'])],
                 uniform_youth_product_id=[''], uniform_home_color=['Black'], uniform_away_color=[''])
    _save_edit(admin_client, app, add)
    config = _cfg(app)
    assert config['uniform']['enabled'] and config['uniform']['product_ids'] == [seed['tee_id']]


def test_the_jersey_logo_is_kept_when_a_store_is_saved(admin_client, app, seed):
    """Saving a team from the edit page used to wipe its jersey logo."""
    _build(admin_client, app, seed)
    before = _cfg(app, 'Soccer: Rainbow Cheetahs')['uniform']['home_design_id']
    assert before
    _save_edit(admin_client, app, lambda d: None, name='Soccer: Rainbow Cheetahs')
    assert _cfg(app, 'Soccer: Rainbow Cheetahs')['uniform']['home_design_id'] == before


def test_the_jersey_logo_can_be_changed_from_the_edit_page(admin_client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: d.update(uniform_home_design_id=[str(c)],
                                                     allowed_designs=[str(a), str(b), str(c)]),
               name='Soccer: Rainbow Cheetahs')
    assert _cfg(app, 'Soccer: Rainbow Cheetahs')['uniform']['home_design_id'] == c


def test_the_edit_page_shows_the_jersey_logo_chooser(admin_client, app, seed):
    _build(admin_client, app, seed)
    coll_id = _store(app, TEAM)[0]
    html = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    assert 'id="homeLogoOptions"' in html and 'name="uniform_home_design_id"' in html
    assert 'No youth Away jersey' in html


def test_a_jersey_shirt_is_not_greyed_out_in_the_fan_wear_list(admin_client, app, seed):
    _build(admin_client, app, seed)
    coll_id = _store(app, TEAM)[0]
    html = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    assert 'box.disabled = isUniform' not in html                     # the old rule that greyed it out is gone
    assert 'A jersey shirt can ALSO be offered as Fan Wear' in html


def test_the_fan_wear_page_names_the_organization_not_a_team(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    page = client.get(f'/c/{_slug_of(app, TEAM)}?path=fan').get_data(as_text=True)
    assert "You're ordering for <strong>Rainbow Cheetahs</strong>" in page
    assert 'Rainbow Cheetahs Fan Wear - Purposefully Made KC' in page
    assert "ordering for <strong>Basketball" not in page
    team_page = client.get(f'/c/{_slug_of(app, TEAM)}').get_data(as_text=True)
    assert 'Basketball' in team_page.split('<title>')[1].split('</title>')[0]
