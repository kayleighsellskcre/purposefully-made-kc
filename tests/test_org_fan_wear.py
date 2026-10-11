"""Org Fan Wear: one link, one set of designs, edits never wipe the store."""
import json

from models import db, Collection, Organization
from tests.test_multi_team_group_orders import _designs, _store, _wizard
from utils.group_orders import (
    org_fan_hub, org_fan_wear_url, org_fanwear_design_ids, team_store_config,
)


def _build(admin_client, app, seed):
    a, b, c = _designs(app, seed)
    resp = admin_client.post('/admin/collections/add', data=_wizard(
        seed,
        allowed_designs=[str(a), str(b), str(c)],
        **{'org_team_jersey_logo_id[]': [str(a), str(b), '']},
    ), follow_redirects=True)
    assert resp.status_code == 200
    return a, b, c


def _set_cfg(app, name, **changes):
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        cfg = json.loads(coll.team_store_config)
        cfg.update(changes)
        coll.team_store_config = json.dumps(cfg)
        db.session.commit()


def test_every_fan_wear_button_points_to_the_same_page(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        org = Organization.query.filter_by(name='Rainbow Cheetahs').one()
        hub, dedicated = org_fan_hub(org)
        assert hub is not None and not dedicated
        url = org_fan_wear_url(org)
        assert url.endswith('?path=fan#fanWearSection')
    landing = client.get(f'/org/{org.slug}').get_data(as_text=True)
    assert url in landing or url.replace('&', '&amp;') in landing
    # A team's nav bar keeps the shopper in their own store (cart stays intact).
    _, slug, _, _ = _store(app, 'Soccer: Rainbow Cheetahs')
    page = client.get(f'/c/{slug}').get_data(as_text=True)
    assert f'/c/{slug}?path=fan#fanWearSection' in page


def test_fan_page_hides_jerseys_and_shows_org_designs(admin_client, client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    _, slug, _, _ = _store(app, 'Soccer: Rainbow Cheetahs')
    page = client.get(f'/c/{slug}?path=fan').get_data(as_text=True)
    assert 'Rainbow Cheetahs Fan Wear' in page
    assert 'id="uniformSection"' not in page


def test_jersey_logo_toggle_and_jersey_only_control_fan_designs(admin_client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    with app.app_context():
        coll = Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one()
        everything = set(org_fanwear_design_ids(coll))
        assert {a, b, c} <= everything
    _set_cfg(app, 'Basketball: Rainbow Cheetahs', fan_show_jersey_logo=False)
    with app.app_context():
        coll = Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one()
        ids = set(org_fanwear_design_ids(coll))
        assert a not in ids and b in ids and c in ids
    _set_cfg(app, 'Soccer: Rainbow Cheetahs', fanwear_excluded_ids=[b])
    with app.app_context():
        coll = Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one()
        assert set(org_fanwear_design_ids(coll)) == {c}


def test_editing_a_team_store_keeps_its_jerseys(admin_client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    coll_id, _, before, _ = _store(app, 'Basketball: Rainbow Cheetahs')
    assert before['uniform']['enabled']
    resp = admin_client.post(f'/admin/collections/{coll_id}/edit', data={
        'name': 'Basketball: Rainbow Cheetahs',
        'slug': _store(app, 'Basketball: Rainbow Cheetahs')[1],
        'is_active': 'on',
        'group_kind': 'team',
        'products': [str(seed['hoodie_id'])],
        'allowed_designs': [str(a), str(b), str(c)],
        'fan_controls_present': '1',
        'fanwear_excluded_ids': [str(a)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    _, _, after, _ = _store(app, 'Basketball: Rainbow Cheetahs')
    assert after['uniform'] == before['uniform']
    assert after['fan_product_ids'] == before['fan_product_ids']
    assert after['fan_show_jersey_logo'] is False  # box left unchecked on the form
    with app.app_context():
        coll = Collection.query.get(coll_id)
        assert json.loads(coll.team_store_config)['fanwear_excluded_ids'] == [a]
