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
    assert 'Fan Wear' in page and 'Rainbow Cheetahs' in page
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


def _edit(admin_client, app, name, **extra):
    coll_id, slug, _, _ = _store(app, name)
    data = {'name': name, 'slug': slug, 'is_active': 'on', 'group_kind': 'team'}
    data.update(extra)
    return coll_id, admin_client.post(f'/admin/collections/{coll_id}/edit', data=data, follow_redirects=True)


def test_sync_copies_fan_styles_and_colors_but_not_jerseys(admin_client, app, seed):
    _build(admin_client, app, seed)
    _, _, soccer_before, _ = _store(app, 'Soccer: Rainbow Cheetahs')
    color = f"p:{seed['hoodie_id']}||Black"
    _edit(admin_client, app, 'Basketball: Rainbow Cheetahs',
          products=[str(seed['hoodie_id'])], allowed_colors=[color],
          color_picker_present='1', sync_fan_to_org='on')
    with app.app_context():
        soccer = Collection.query.filter_by(name='Soccer: Rainbow Cheetahs').one()
        assert json.loads(soccer.allowed_colors) == json.loads(
            Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one().allowed_colors)
        cfg = json.loads(soccer.team_store_config)
        assert cfg['fan_product_ids'] == [seed['hoodie_id']]
        assert cfg['uniform'] == soccer_before['uniform']


def test_no_sync_leaves_other_teams_alone(admin_client, app, seed):
    _build(admin_client, app, seed)
    color = f"p:{seed['hoodie_id']}||Black"
    _edit(admin_client, app, 'Basketball: Rainbow Cheetahs',
          products=[str(seed['hoodie_id'])], allowed_colors=[color], color_picker_present='1')
    with app.app_context():
        assert Collection.query.filter_by(name='Soccer: Rainbow Cheetahs').one().allowed_colors in (None, '')


def test_edit_without_color_picker_keeps_saved_colors(admin_client, app, seed):
    _build(admin_client, app, seed)
    color = f"p:{seed['hoodie_id']}||Black"
    _edit(admin_client, app, 'Basketball: Rainbow Cheetahs',
          products=[str(seed['hoodie_id'])], allowed_colors=[color], color_picker_present='1')
    _edit(admin_client, app, 'Basketball: Rainbow Cheetahs', products=[str(seed['hoodie_id'])])
    with app.app_context():
        saved = Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one().allowed_colors
        assert saved and 'Black' in saved


def test_edit_page_has_the_quick_color_bar_and_sync_box(admin_client, app, seed):
    _build(admin_client, app, seed)
    coll_id, _, _, _ = _store(app, 'Basketball: Rainbow Cheetahs')
    html = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    assert 'id="fanQuickRow"' in html
    assert 'name="sync_fan_to_org"' in html
    assert 'Select products above first' not in html


# ── Organization edit page ───────────────────────────────────────────────────

import io


def _org_slug(app):
    with app.app_context():
        return Organization.query.filter_by(name='Rainbow Cheetahs').one().slug


def test_admin_opens_org_edit_page_with_teams_inside_it(admin_client, app, seed):
    _build(admin_client, app, seed)
    html = admin_client.get(f'/org/{_org_slug(app)}/manage').get_data(as_text=True)
    for label in ('Basketball', 'Soccer', 'Volleyball'):
        assert f'Edit {label}' in html
    assert 'name="photos"' in html and 'name="logo"' in html


def _photos(app, slug):
    from routes.org import org_photos
    with app.app_context():
        org = Organization.query.filter_by(slug=slug).one()
        return [(p['key'], p['hidden']) for p in org_photos(org)]


def _save(admin_client, slug, **extra):
    data = {'action': 'save_settings', 'name': 'Rainbow Cheetahs', 'description': 'Hi'}
    data.update(extra)
    return admin_client.post(f'/org/{slug}/manage', data=data, content_type='multipart/form-data',
                             follow_redirects=True)


def test_adding_a_photo_keeps_the_fan_designs(admin_client, app, seed, monkeypatch):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    before = _photos(app, slug)
    fan_keys = [k for k, _h in before if k.startswith('fan:')]
    assert fan_keys, 'fan wear designs are the default main photos'
    monkeypatch.setattr('utils.cloud_storage.upload_image', lambda *a, **k: 'uploads/org-photos/new.png')
    _save(admin_client, slug, photos=(io.BytesIO(b'x'), 'new.png'))
    after = _photos(app, slug)
    assert [k for k, _h in after if k.startswith('fan:')] == fan_keys
    assert ('up:uploads/org-photos/new.png', False) in after
    assert not any(h for _k, h in after)


def test_photos_are_only_removed_when_ticked_and_can_be_restored(admin_client, app, seed, monkeypatch):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    monkeypatch.setattr('utils.cloud_storage.upload_image', lambda *a, **k: 'uploads/org-photos/new.png')
    _save(admin_client, slug, photos=(io.BytesIO(b'x'), 'new.png'))
    fan_key = next(k for k, _h in _photos(app, slug) if k.startswith('fan:'))

    _save(admin_client, slug, remove_photo=fan_key)
    state = dict(_photos(app, slug))
    assert state[fan_key] is True                      # hidden, not gone
    assert state['up:uploads/org-photos/new.png'] is False

    _save(admin_client, slug, restore_photo=fan_key)
    assert dict(_photos(app, slug))[fan_key] is False

    _save(admin_client, slug, remove_photo='up:uploads/org-photos/new.png')
    assert 'up:uploads/org-photos/new.png' not in dict(_photos(app, slug))


def test_photo_added_before_this_change_is_kept_and_removable(admin_client, app, seed):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    with app.app_context():
        org = Organization.query.filter_by(slug=slug).one()
        org.cover_image = 'uploads/org-covers/old.png'
        db.session.commit()
    keys = dict(_photos(app, slug))
    assert 'cover' in keys and any(k.startswith('fan:') for k in keys)
    _save(admin_client, slug, remove_photo='cover')
    assert 'cover' not in dict(_photos(app, slug))


def test_every_card_lists_all_photos(admin_client, client, app, seed, monkeypatch):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    monkeypatch.setattr('utils.cloud_storage.upload_image', lambda *a, **k: 'uploads/org-photos/new.png')
    _save(admin_client, slug, photos=(io.BytesIO(b'x'), 'new.png'))
    html = admin_client.get('/admin/collections').get_data(as_text=True)
    assert 'org-photos/new.png' in html


def test_org_team_rename_and_reorder(admin_client, app, seed):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    with app.app_context():
        secs = Organization.query.filter_by(slug=slug).one().sections.all()
        first, second = secs[0].id, secs[1].id
    admin_client.post(f'/org/{slug}/manage', data={
        'action': 'rename_section', 'section_id': first, 'label': 'Hoops', 'icon': '🏀'})
    admin_client.post(f'/org/{slug}/manage', data={
        'action': 'reorder', 'section_order[]': [str(second), str(first)]})
    with app.app_context():
        from models import OrgSection
        assert OrgSection.query.get(first).label == 'Hoops'
        assert OrgSection.query.get(second).sort_order == 0


def test_admin_list_shows_one_org_card_not_every_team(admin_client, app, seed):
    _build(admin_client, app, seed)
    html = admin_client.get('/admin/collections').get_data(as_text=True)
    assert 'Edit Rainbow Cheetahs' in html
    assert 'id="orgGroup' in html
    assert 'collection-card' not in html.split('Other Group Orders')[0]


def _hero_keys(app, slug):
    from routes.org import org_photos
    with app.app_context():
        org = Organization.query.filter_by(slug=slug).one()
        return {p['key'] for p in org_photos(org) if p['hero'] and not p['hidden']}


def test_each_photo_can_be_chosen_for_the_top_of_the_page(admin_client, client, app, seed, monkeypatch):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    monkeypatch.setattr('utils.cloud_storage.upload_image', lambda *a, **k: 'uploads/org-photos/mine.png')
    _save(admin_client, slug, photos=(io.BytesIO(b'x'), 'mine.png'))
    # Before anyone chooses, only the photos the organizer added are on top.
    assert _hero_keys(app, slug) == {'up:uploads/org-photos/mine.png'}

    fan_key = next(k for k, _h in _photos(app, slug) if k.startswith('fan:'))
    _save(admin_client, slug, hero_present='1', hero_photo=[fan_key, 'up:uploads/org-photos/mine.png'])
    assert _hero_keys(app, slug) == {fan_key, 'up:uploads/org-photos/mine.png'}

    _save(admin_client, slug, hero_present='1', hero_photo=[fan_key])
    assert _hero_keys(app, slug) == {fan_key}
    html = client.get(f'/org/{slug}').get_data(as_text=True)
    assert 'org-cover-tile' in html and 'org-photos/mine.png' not in html


def test_a_photo_added_after_choosing_shows_up_on_top(admin_client, app, seed, monkeypatch):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    fan_key = next(k for k, _h in _photos(app, slug) if k.startswith('fan:'))
    _save(admin_client, slug, hero_present='1', hero_photo=[fan_key])
    monkeypatch.setattr('utils.cloud_storage.upload_image', lambda *a, **k: 'uploads/org-photos/later.png')
    _save(admin_client, slug, photos=(io.BytesIO(b'x'), 'later.png'))
    assert _hero_keys(app, slug) == {fan_key, 'up:uploads/org-photos/later.png'}
