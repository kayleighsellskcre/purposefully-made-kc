"""Multi-team wizard: one organization page and one store per team.

Covers the bug where the wizard said "Something went wrong" after saving
only the first store, and per-team jerseys, away jerseys and jersey logos
never reached the storefronts.
"""
import json

from models import db, Collection, Design, Organization, OrgSection
from utils.group_orders import team_store_choice, team_store_config


def _designs(app, seed):
    with app.app_context():
        a = Design(filename='bb.png', file_path='uploads/designs/bb.png',
                   title='Basketball Logo', uploaded_by_user_id=seed['admin_id'])
        b = Design(filename='sc.png', file_path='uploads/designs/sc.png',
                   title='Soccer Logo', uploaded_by_user_id=seed['admin_id'])
        c = Design(filename='spirit.png', file_path='uploads/designs/spirit.png',
                   title='Spirit Art', uploaded_by_user_id=seed['admin_id'])
        db.session.add_all([a, b, c])
        db.session.commit()
        return a.id, b.id, c.id


def _wizard(seed, **extra):
    data = {
        'name': 'Rainbow Cheetahs',
        'is_active': 'on',
        'group_kind': 'team',
        'team_store_present': '1',
        'org_action': 'new',
        'org_style_mode': 'different',
        'org_team_names[]': ['Basketball', 'Soccer', 'Volleyball'],
        # Basketball: adult + youth home in Black, adult away in White
        # Soccer: adult White home, no away
        # Volleyball: no jersey, fan wear only
        'org_team_uniform_product_id[]': [str(seed['tee_id']), str(seed['tee_id']), ''],
        'org_team_home_color[]': ['Black', 'White', ''],
        'org_team_youth_product_id[]': [str(seed['youth_id']), '', ''],
        'org_team_away_product_id[]': [str(seed['tee_id']), '', ''],
        'org_team_away_color[]': ['White', '', ''],
        'org_team_away_youth_product_id[]': ['', '', ''],
        'products': [str(seed['hoodie_id'])],
    }
    data.update(extra)
    return data


def _store(app, name):
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        return coll.id, coll.slug, team_store_config(coll), json.loads(coll.allowed_design_ids or '[]')


def test_wizard_builds_every_team_store_with_its_own_jersey(admin_client, app, seed):
    bb_logo, sc_logo, spirit = _designs(app, seed)
    resp = admin_client.post('/admin/collections/add', data=_wizard(
        seed,
        allowed_designs=[str(bb_logo), str(sc_logo), str(spirit)],
        **{
            'org_team_jersey_logo_id[]': [str(bb_logo), str(sc_logo), ''],
            'org_team_away_jersey_logo_id[]': ['', '', ''],
        },
    ), follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'Something went wrong' not in html
    assert 'Created 3 team stores for Rainbow Cheetahs' in html

    with app.app_context():
        org = Organization.query.filter_by(name='Rainbow Cheetahs').one()
        sections = OrgSection.query.filter_by(organization_id=org.id).order_by(OrgSection.sort_order).all()
        assert [s.label for s in sections] == ['Basketball', 'Soccer', 'Volleyball']
        assert [s.icon for s in sections] == ['🏀', '⚽', '🏐']
        assert sections[0].collection.slug == 'rainbow-cheetahs'

    _, _, bb, bb_allowed = _store(app, 'Basketball: Rainbow Cheetahs')
    assert bb['uniform']['enabled'] is True
    assert bb['uniform']['home_color'] == 'Black'
    assert bb['uniform']['away_color'] == 'White'
    assert bb['uniform']['home_product_ids'] == [seed['tee_id'], seed['youth_id']]
    assert bb['uniform']['away_product_ids'] == [seed['tee_id']]
    assert bb['uniform']['home_design_id'] == bb_logo
    assert bb['fan_product_ids'] == [seed['hoodie_id']]
    # Basketball offers its own logo plus shared art, never Soccer's logo.
    assert bb_allowed == [bb_logo, spirit]

    _, _, sc, sc_allowed = _store(app, 'Soccer: Rainbow Cheetahs')
    assert sc['uniform']['home_color'] == 'White'
    assert sc['uniform']['away_color'] == ''
    assert sc['uniform']['product_ids'] == [seed['tee_id']]
    assert sc['uniform']['home_design_id'] == sc_logo
    assert sc_allowed == [sc_logo, spirit]

    _, _, vb, vb_allowed = _store(app, 'Volleyball: Rainbow Cheetahs')
    assert vb['uniform']['enabled'] is False
    assert vb['fan_product_ids'] == [seed['hoodie_id']]
    assert set(vb_allowed) == {bb_logo, sc_logo, spirit}


def test_youth_cannot_buy_an_away_kit_the_team_does_not_offer(admin_client, app, seed):
    admin_client.post('/admin/collections/add', data=_wizard(seed), follow_redirects=True)
    with app.app_context():
        bb = Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one()
        assert team_store_choice(bb, seed['youth_id'], 'uniform', 'home')[3] is None
        assert team_store_choice(bb, seed['tee_id'], 'uniform', 'away')[2] == 'White'
        error = team_store_choice(bb, seed['youth_id'], 'uniform', 'away')[3]
        assert error and 'Away uniform' in error


def test_team_store_shows_jerseys_first_and_a_fan_wear_button(admin_client, client, app, seed):
    admin_client.post('/admin/collections/add', data=_wizard(seed), follow_redirects=True)
    _, slug, _, _ = _store(app, 'Basketball: Rainbow Cheetahs')
    html = client.get(f'/c/{slug}').get_data(as_text=True)
    assert 'What are you shopping for?' not in html
    assert '<section class="uniform-section" id="uniformSection">' in html
    assert 'Shop Family &amp; Fan Wear' in html
    assert html.index('id="uniformSection"') < html.index('id="fanWearToggle"') < html.index('id="fanWearSection"')
    # Fan wear waits behind the button so jerseys are what shoppers see first.
    fan_tag = html[html.index('id="fanWearSection"'):html.index('id="fanWearSection"') + 80]
    assert 'hidden' in fan_tag
    # Team switcher lists every team.
    assert 'Choose your team' in html
    for label in ('Basketball', 'Soccer', 'Volleyball'):
        assert label in html


def test_fan_only_team_store_shows_fan_wear_right_away(admin_client, client, app, seed):
    admin_client.post('/admin/collections/add', data=_wizard(seed), follow_redirects=True)
    _, slug, _, _ = _store(app, 'Volleyball: Rainbow Cheetahs')
    html = client.get(f'/c/{slug}').get_data(as_text=True)
    assert 'id="fanWearToggle"' not in html
    fan_tag = html[html.index('id="fanWearSection"'):html.index('id="fanWearSection"') + 80]
    assert 'hidden' not in fan_tag


def test_bad_team_setup_saves_nothing(admin_client, app, seed):
    data = _wizard(seed, **{'org_team_away_color[]': ['', '', '']})  # away style, no color
    resp = admin_client.post('/admin/collections/add', data=data, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'Basketball: choose an Away jersey color' in html
    with app.app_context():
        assert Organization.query.count() == 0
        assert Collection.query.filter(Collection.name.contains('Rainbow Cheetahs')).count() == 0


def test_same_style_mode_still_makes_a_store_per_team(admin_client, app, seed):
    resp = admin_client.post('/admin/collections/add', data={
        'name': 'Lions',
        'group_kind': 'team',
        'team_store_present': '1',
        'org_action': 'new',
        'org_style_mode': 'same',
        'org_team_names[]': ['Baseball', 'Softball'],
        'uniform_enabled': 'on',
        'uniform_product_id': str(seed['tee_id']),
        'uniform_home_color': 'Black',
        'products': [str(seed['hoodie_id'])],
    }, follow_redirects=True)
    assert 'Created 2 team stores for Lions' in resp.get_data(as_text=True)
    for name in ('Baseball: Lions', 'Softball: Lions'):
        _, _, cfg, _ = _store(app, name)
        assert cfg['uniform']['product_ids'] == [seed['tee_id']]
        assert cfg['uniform']['home_color'] == 'Black'
        assert cfg['fan_product_ids'] == [seed['hoodie_id']]


def test_single_store_keeps_a_separate_away_style_through_edits(admin_client, app, seed):
    admin_client.post('/admin/collections/add', data={
        'name': 'Panthers',
        'group_kind': 'team',
        'team_store_present': '1',
        'uniform_enabled': 'on',
        'uniform_product_id': str(seed['tee_id']),
        'uniform_youth_product_id': str(seed['youth_id']),
        'uniform_home_color': 'Black',
        'uniform_away_color': 'White',
        'uniform_away_product_id': str(seed['tee_id']),
        'uniform_away_youth_product_id': '',
        'products': [str(seed['hoodie_id'])],
    }, follow_redirects=True)
    # Youth tee has no White, so with no youth away style the youth Home
    # style is used for Away too and the save is refused with a clear message.
    with app.app_context():
        assert Collection.query.filter_by(name='Panthers').count() == 0

    admin_client.post('/admin/collections/add', data={
        'name': 'Panthers',
        'group_kind': 'team',
        'team_store_present': '1',
        'uniform_enabled': 'on',
        'uniform_product_id': str(seed['youth_id']),
        'uniform_home_color': 'Black',
        'uniform_away_color': 'White',
        'uniform_away_product_id': str(seed['tee_id']),
        'products': [str(seed['hoodie_id'])],
    }, follow_redirects=True)
    coll_id, _, cfg, _ = _store(app, 'Panthers')
    assert cfg['uniform']['home_product_ids'] == [seed['youth_id']]
    assert cfg['uniform']['away_product_ids'] == [seed['tee_id']]

    edit = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    away_select = edit[edit.index('id="uniform_away_product_id"'):]
    away_select = away_select[:away_select.index('</select>')]
    assert f'value="{seed["tee_id"]}" selected' in away_select
