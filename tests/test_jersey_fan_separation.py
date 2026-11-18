"""Jerseys and Fan Wear are separate: jerseys get their own placements and stacked-name choice,
and a team page of an organization with its own Fan Wear store shows no Fan Wear at all."""
import json
import re

from models import Collection, db
from tests.test_group_order_audit import _slug_of
from tests.test_jersey_and_fan_wear import TEAM, _cfg, _save_edit
from tests.test_org_fan_wear import _build, _org_slug
from utils.group_orders import team_store_config, uniform_rules


def _jersey_page(client, app, seed, section='uniform'):
    client.get(f'/c/{_slug_of(app, TEAM)}')
    slug = seed['tee_slug'] if section == 'uniform' else seed['hoodie_slug']
    url = f"/shop/customize/{slug}?catalog_section={section}"
    if section == 'uniform':
        url += '&uniform_kit=home'
    return client.get(url).get_data(as_text=True)


def _placements_in(page):
    match = re.search(r'allowedPlacements:\s*(\[[^\]]*\]|null)', page)
    return json.loads(match.group(1)) if match else None


def _set_store(app, **fields):
    with app.app_context():
        coll = Collection.query.filter_by(name=TEAM).one()
        for key, value in fields.items():
            setattr(coll, key, value)
        db.session.commit()


def _jersey_rules(data, placements=None, stacked=False):
    data['jersey_rules_present'] = ['1']
    data['jersey_placements'] = list(placements or [])
    data.pop('jersey_allow_stacked_name', None)
    if stacked:
        data['jersey_allow_stacked_name'] = ['on']


def test_jerseys_follow_the_store_until_the_organizer_sets_their_own(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _set_store(app, allowed_placements=json.dumps(['center_chest', 'left_chest', 'center_back']), allow_stacked_name=True)
    with app.app_context():
        coll = Collection.query.filter_by(name=TEAM).one()
        assert uniform_rules(coll) == (['center_chest', 'left_chest', 'center_back'], True)
        assert team_store_config(coll)['jersey_placements'] is None
    assert _placements_in(_jersey_page(client, app, seed)) == ['center_chest', 'left_chest', 'center_back']


def test_jerseys_can_be_front_only_while_fan_wear_keeps_its_three_spots(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _set_store(app, allowed_placements=json.dumps(['center_chest', 'left_chest', 'center_back']))
    _save_edit(admin_client, app, lambda d: _jersey_rules(d, ['center_chest', 'left_chest'], stacked=True))
    assert _cfg(app)['jersey_placements'] == ['center_chest', 'left_chest']
    assert _placements_in(_jersey_page(client, app, seed)) == ['center_chest', 'left_chest']          # no Center Back
    fan_page = _jersey_page(client, app, seed, section='fan')
    assert _placements_in(fan_page) == ['center_chest', 'left_chest', 'center_back']                 # Fan Wear: all 3


def test_a_jersey_rule_that_matches_the_store_is_not_stored(admin_client, app, seed):
    _build(admin_client, app, seed)
    store = ['center_chest', 'left_chest', 'center_back']
    _set_store(app, allowed_placements=json.dumps(store), allow_stacked_name=True)
    _save_edit(admin_client, app, lambda d: _jersey_rules(d, store, stacked=True))
    config = _cfg(app)
    assert config['jersey_placements'] is None and config['jersey_allow_stacked_name'] is None


def test_the_jersey_rules_survive_saving_from_a_page_without_the_jersey_boxes(admin_client, app, seed):
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: _jersey_rules(d, ['left_chest'], stacked=False))
    assert _cfg(app)['jersey_placements'] == ['left_chest']
    assert _cfg(app)['jersey_allow_stacked_name'] is False

    def older_page(d):
        for key in ('jersey_rules_present', 'jersey_placements', 'jersey_allow_stacked_name'):
            d.pop(key, None)
    _save_edit(admin_client, app, older_page)
    assert _cfg(app)['jersey_placements'] == ['left_chest']
    assert _cfg(app)['jersey_allow_stacked_name'] is False


def test_the_edit_page_shows_the_jersey_choices_and_remembers_them(admin_client, app, seed):
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: _jersey_rules(d, ['center_chest'], stacked=False))
    with app.app_context():
        coll_id = Collection.query.filter_by(name=TEAM).one().id
    page = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    assert 'Jersey choices' in page and 'name="jersey_placements"' in page
    assert re.search(r'name="jersey_placements" value="center_chest"\s+checked', page)
    assert not re.search(r'name="jersey_placements" value="center_back"\s+checked', page)
    assert not re.search(r'name="jersey_allow_stacked_name" value="on"\s+checked', page)


def test_a_stacked_name_is_refused_on_a_jersey_but_allowed_on_fan_wear(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _set_store(app, allow_stacked_name=True, allow_back_design=True, back_design_type='name_number')
    _save_edit(admin_client, app, lambda d: _jersey_rules(d, None, stacked=False))
    client.get(f'/c/{_slug_of(app, TEAM)}')
    base = {'product_id': seed['tee_id'], 'size': 'M', 'quantity': 1, 'placement': 'center_chest',
            'back_design_name': 'SMITH', 'back_design_vertical': 'true'}
    jersey = client.post('/cart/add', data={**base, 'color': 'Black', 'catalog_section': 'uniform', 'uniform_kit': 'home'})
    assert jersey.status_code == 400 and 'stacked' in jersey.get_json()['error']
    fan = client.post('/cart/add', data={**base, 'color': 'Black', 'catalog_section': 'fan'})
    assert 'stacked' not in (fan.get_json() or {}).get('error', '')


def test_a_placement_the_jersey_does_not_offer_is_refused_in_the_cart(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _set_store(app, allowed_placements=json.dumps(['center_chest', 'left_chest', 'center_back']))
    _save_edit(admin_client, app, lambda d: _jersey_rules(d, ['center_chest']))
    client.get(f'/c/{_slug_of(app, TEAM)}')
    base = {'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
            'catalog_section': 'uniform', 'uniform_kit': 'home'}
    refused = client.post('/cart/add', data={**base, 'placement': 'center_back'})
    assert refused.status_code == 400 and 'placement' in refused.get_json()['error']
    assert client.post('/cart/add', data={**base, 'placement': 'center_chest'}).get_json().get('success')


# ── No Fan Wear on a team page when the organization has its own Fan Wear store ──

def test_a_team_page_shows_no_fan_wear_when_the_organization_has_a_fan_wear_store(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    slug = _slug_of(app, TEAM)
    page = client.get(f'/c/{slug}').get_data(as_text=True)
    assert 'id="uniformSection"' in page                                      # the jerseys are still there
    assert "Don&rsquo;t need a jersey?" not in page and 'id="fanWearToggle"' not in page
    assert 'catalog_section=fan' not in page                                  # no Fan Wear card or link
    assert 'Fan Wear' in page                                                 # the org tab to the separate page stays


def test_an_old_team_fan_wear_link_goes_to_the_separate_fan_wear_page(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    resp = client.get(f'/c/{_slug_of(app, TEAM)}?path=fan')
    assert resp.status_code == 302
    assert '/c/' in resp.headers['Location'] and TEAM.lower().split(':')[0] not in resp.headers['Location']


def test_the_separate_fan_wear_page_still_sells_fan_wear(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        from models import Organization
        from utils.group_orders import org_fan_hub
        org = Organization.query.filter_by(name='Rainbow Cheetahs').one()
        hub, dedicated = org_fan_hub(org)
        slug = hub.slug
    page = client.get(f'/c/{slug}').get_data(as_text=True)
    assert 'catalog_section=fan' in page
    assert f"/shop/customize/{seed['hoodie_slug']}?catalog_section=fan" in page


def test_a_store_without_an_organization_keeps_jerseys_and_fan_wear_together(admin_client, client, app, seed):
    """A lone store has no separate Fan Wear page, so it must keep selling Fan Wear itself."""
    _build(admin_client, app, seed)
    from models import OrgSection
    with app.app_context():
        coll = Collection.query.filter_by(name=TEAM).one()
        OrgSection.query.filter_by(collection_id=coll.id).delete()
        db.session.commit()
    page = client.get(f'/c/{_slug_of(app, TEAM)}').get_data(as_text=True)
    assert 'catalog_section=fan' in page or 'id="fanWearToggle"' in page
