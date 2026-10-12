"""Each organization gets its own Fan Wear store, so team orders and Excel files stay about the team."""
import json
from datetime import datetime, timedelta

from models import Collection, Order, OrgSection, Organization, db
from tests.test_group_order_audit import _slug_of
from tests.test_jersey_and_fan_wear import _save_edit
from tests.test_org_fan_wear import _build, _org_slug
from utils.group_orders import org_fan_hub, org_fan_wear_url, team_store_config
from utils.org_fan_store import fan_store_for, is_auto_fan_store, sync_org_fan_store

TEAM = 'Basketball: Rainbow Cheetahs'


def _org(app):
    return Organization.query.filter_by(name='Rainbow Cheetahs').one()


def _fan(app):
    with app.app_context():
        store = fan_store_for(_org(app))
        return store.id, store.slug


# ── It exists, and is its own store ──────────────────────────────────────────

def test_a_new_organization_gets_its_own_fan_wear_store(admin_client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        org = _org(app)
        store = fan_store_for(org)
        assert store is not None and is_auto_fan_store(store)
        assert store.name == 'Fan Wear: Rainbow Cheetahs'
        labels = [s.label for s in org.sections.order_by(OrgSection.sort_order)]
        assert labels[-1] == 'Fan Wear' and labels.count('Fan Wear') == 1
        cfg = team_store_config(store)
        assert not cfg['uniform']['enabled']                       # no jerseys in Fan Wear
        team = Collection.query.filter_by(name=TEAM).one()
        assert cfg['fan_product_ids'] == team_store_config(team)['fan_product_ids']
        assert store.show_in_directory is False and store.is_active


def test_syncing_again_never_makes_a_second_store(admin_client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        org = _org(app)
        first = fan_store_for(org).id
        for _ in range(3):
            sync_org_fan_store(org)
        db.session.commit()
        assert fan_store_for(org).id == first
        assert Collection.query.filter(Collection.name.like('Fan Wear:%')).count() == 1


def test_every_fan_wear_button_opens_the_fan_wear_store(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _, fan_slug = _fan(app)
    with app.app_context():
        org = _org(app)
        hub, dedicated = org_fan_hub(org)
        assert dedicated and hub.slug == fan_slug
        assert org_fan_wear_url(org) == f'/c/{fan_slug}'
    landing = client.get(f'/org/{_org_slug(app)}').get_data(as_text=True)
    assert f'/c/{fan_slug}' in landing
    team_page = client.get(f'/c/{_slug_of(app, TEAM)}').get_data(as_text=True)     # empty cart
    assert f'/c/{fan_slug}' in team_page


def test_the_fan_wear_store_is_not_listed_as_a_team_anywhere(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        for c in Collection.query.filter(Collection.name.like('%Rainbow Cheetahs')).all():
            if not c.name.startswith('Fan'):
                c.show_in_directory = True
        db.session.commit()
        from utils.group_orders import public_group_directory
        orgs, stores = public_group_directory()
        assert [o['team_count'] for o in orgs] == [3] and all(not s['collection'].name.startswith('Fan') for s in stores)
    assert 'Fan Wear: Rainbow Cheetahs' not in client.get('/shop/group-orders').get_data(as_text=True)
    page = admin_client.get(f'/org/{_org_slug(app)}/manage').get_data(as_text=True)
    assert 'Edit Fan Wear' in page and 'kept apart from your teams' in page
    assert 'Edit Fan Wear</a>' in page and 'Edit Fan Wear:' not in page
    admin = admin_client.get('/admin/collections').get_data(as_text=True)
    assert '3 team stores + Fan Wear' in admin


# ── Shopping in it ───────────────────────────────────────────────────────────

def test_the_fan_wear_page_shows_fan_wear_only(admin_client, client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    _, fan_slug = _fan(app)
    page = client.get(f'/c/{fan_slug}').get_data(as_text=True)
    assert "You're ordering for <strong>Rainbow Cheetahs</strong>" in page
    assert 'id="uniformSection"' not in page
    assert 'Basketball' not in page.split('<title>')[1].split('</title>')[0]
    # the teams' jersey logo designs are offered as fan designs, from every team
    from utils.group_orders import org_fanwear_design_ids
    with app.app_context():
        store = Collection.query.filter_by(slug=fan_slug).one()
        assert {a, b, c} <= set(org_fanwear_design_ids(store))


def test_a_fan_wear_item_goes_to_the_fan_store_not_a_team(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    fan_id, fan_slug = _fan(app)
    client.get(f'/c/{fan_slug}')
    resp = client.post('/cart/add', data={
        'product_id': seed['hoodie_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
        'catalog_section': 'fan', 'placement': 'center_chest',
    })
    assert resp.get_json().get('success'), resp.get_json()
    with client.session_transaction() as sess:
        cart = sess.get('cart') or []
    assert cart and all(i['collection_id'] == fan_id and i['catalog_section'] == 'fan' for i in cart)


def test_a_fan_wear_style_can_not_be_ordered_as_a_jersey_from_the_fan_store(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    _, fan_slug = _fan(app)
    client.get(f'/c/{fan_slug}')
    resp = client.post('/cart/add', data={
        'product_id': seed['hoodie_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
        'catalog_section': 'uniform', 'uniform_kit': 'home', 'placement': 'center_chest',
    })
    assert resp.status_code == 400


# ── Staying in step with the teams ───────────────────────────────────────────

def test_saving_fan_wear_updates_the_fan_store(admin_client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    resp = admin_client.post(f'/org/{_org_slug(app)}/fan-wear', data={
        'products': [str(seed['hoodie_id'])],
        'design_ids': [str(a), str(b), str(c)], 'fan_designs': [str(a), str(c)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        store = fan_store_for(_org(app))
        assert team_store_config(store)['fan_product_ids'] == [seed['hoodie_id']]
        assert json.loads(store.allowed_design_ids) == [a, c]            # the one hidden design stays hidden


def test_removing_every_fan_style_closes_the_fan_store_and_adding_one_reopens_it(admin_client, app, seed):
    a, b, c = _build(admin_client, app, seed)
    url = f'/org/{_org_slug(app)}/fan-wear'
    base = {'design_ids': [str(a), str(b), str(c)], 'fan_designs': [str(a), str(b), str(c)]}
    admin_client.post(url, data=dict(base, products=[]), follow_redirects=True)
    with app.app_context():
        assert not fan_store_for(_org(app)).is_active
        assert org_fan_hub(_org(app))[1] is False                          # falls back to a team store
    admin_client.post(url, data=dict(base, products=[str(seed['hoodie_id'])]), follow_redirects=True)
    with app.app_context():
        assert fan_store_for(_org(app)).is_active


def test_fan_wear_opens_with_the_first_team_and_closes_with_the_last(admin_client, app, seed):
    _build(admin_client, app, seed)
    from utils.group_orders import parse_order_deadline
    soon = (datetime.utcnow() + timedelta(days=10)).strftime('%Y-%m-%d')
    later = (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d')
    with app.app_context():
        teams = [c for c in Collection.query.all() if c.name.endswith(': Rainbow Cheetahs') and not c.name.startswith('Fan')]
        for i, team in enumerate(teams):
            team.order_deadline = parse_order_deadline(soon if i == 0 else later)
        db.session.commit()
        sync_org_fan_store(_org(app))
        db.session.commit()
        assert fan_store_for(_org(app)).order_deadline == parse_order_deadline(later)
        teams[0].order_deadline = None                                      # one team has no deadline
        sync_org_fan_store(_org(app))
        db.session.commit()
        assert fan_store_for(_org(app)).order_deadline is None


def test_editing_a_team_from_its_edit_page_keeps_the_fan_store_in_step(admin_client, app, seed):
    _build(admin_client, app, seed)
    later = (datetime.utcnow() + timedelta(days=45)).strftime('%Y-%m-%d')
    for name in ('Soccer: Rainbow Cheetahs', 'Volleyball: Rainbow Cheetahs', TEAM):
        _save_edit(admin_client, app, lambda d: d.update(order_deadline=[later]), name=name)
    with app.app_context():
        assert fan_store_for(_org(app)).order_deadline is not None


# ── Orders and Excel stay organized ──────────────────────────────────────────

def test_fan_wear_orders_have_their_own_excel_and_never_appear_in_a_teams(admin_client, app, seed):
    _build(admin_client, app, seed)
    fan_id, fan_slug = _fan(app)
    team_id = None
    with app.app_context():
        team_id = Collection.query.filter_by(name=TEAM).one().id
        for collection_id, number in ((fan_id, 'FAN-1001'), (team_id, 'TEAM-1001')):
            db.session.add(Order(order_number=number, collection_id=collection_id, email='mom@example.com',
                                 first_name='Mom', last_name='Cheetah', subtotal=20, total=20,
                                 payment_status='paid', status='paid'))
        db.session.commit()
    from routes.collection import _build_group_order_xlsx
    import io
    import openpyxl
    with app.app_context():
        def numbers(collection_id):
            book = openpyxl.load_workbook(io.BytesIO(_build_group_order_xlsx(db.session.get(Collection, collection_id), include_internal=True)))
            return {row[0] for row in book['Orders'].iter_rows(min_row=2, values_only=True) if row[0]}
        assert numbers(fan_id) == {'FAN-1001'}
        assert numbers(team_id) == {'TEAM-1001'}
    resp = admin_client.get(f'/c/{fan_slug}/export.xlsx')
    assert resp.status_code == 200


def test_the_org_edit_page_shows_fan_wear_orders_apart_from_teams(admin_client, app, seed):
    _build(admin_client, app, seed)
    fan_id, fan_slug = _fan(app)
    with app.app_context():
        db.session.add(Order(order_number='FAN-2001', collection_id=fan_id, email='a@example.com',
                             first_name='A', last_name='B', subtotal=10, total=10))
        db.session.commit()
    html = admin_client.get(f'/org/{_org_slug(app)}/manage').get_data(as_text=True)
    assert '<b>1</b> Fan Wear order so far' in html
    assert f'/c/{fan_slug}/export.xlsx' in html


def test_deleting_an_organization_takes_its_fan_wear_store_off_the_site_but_keeps_orders(admin_client, app, seed):
    _build(admin_client, app, seed)
    fan_id, _ = _fan(app)
    with app.app_context():
        db.session.add(Order(order_number='FAN-3001', collection_id=fan_id, email='a@example.com',
                             first_name='A', last_name='B', subtotal=10, total=10))
        db.session.commit()
    admin_client.post(f'/org/{_org_slug(app)}/manage', data={'action': 'delete_org'}, follow_redirects=True)
    with app.app_context():
        store = db.session.get(Collection, fan_id)
        assert not store.is_active
        assert Order.query.filter_by(order_number='FAN-3001').one().collection_id == fan_id


def test_a_hand_made_fan_section_is_never_overwritten(admin_client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        org = _org(app)
        store = fan_store_for(org)
        cfg = json.loads(store.team_store_config)
        cfg.pop('org_fan_store')                                            # pretend the admin built it by hand
        cfg['fan_product_ids'] = [seed['tee_id']]
        store.team_store_config = json.dumps(cfg)
        db.session.commit()
        sync_org_fan_store(org)
        db.session.commit()
        assert team_store_config(fan_store_for(org))['fan_product_ids'] == [seed['tee_id']]


# ── Audit follow-ups ─────────────────────────────────────────────────────────

def test_saving_the_fan_wear_store_from_its_edit_page_keeps_it_following_the_teams(admin_client, app, seed):
    """Saving it once used to drop its marker, after which it silently stopped following the teams."""
    _build(admin_client, app, seed)
    _save_edit(admin_client, app, lambda d: None, name='Fan Wear: Rainbow Cheetahs')
    with app.app_context():
        assert is_auto_fan_store(fan_store_for(_org(app)))
    later = (datetime.utcnow() + timedelta(days=60)).strftime('%Y-%m-%d')
    for name in ('Soccer: Rainbow Cheetahs', 'Volleyball: Rainbow Cheetahs', TEAM):
        _save_edit(admin_client, app, lambda d: d.update(order_deadline=[later]), name=name)
    with app.app_context():
        assert fan_store_for(_org(app)).order_deadline is not None


def test_a_problem_syncing_fan_wear_never_blocks_a_team_save(admin_client, app, seed, monkeypatch):
    _build(admin_client, app, seed)

    def boom(*a, **k):
        raise RuntimeError('fan store exploded')
    monkeypatch.setattr('utils.org_fan_store._fill', boom)
    later = (datetime.utcnow() + timedelta(days=20)).strftime('%Y-%m-%d')
    _save_edit(admin_client, app, lambda d: d.update(order_deadline=[later]), name=TEAM)
    with app.app_context():
        team = Collection.query.filter_by(name=TEAM).one()
        assert team.order_deadline is not None                 # the team's own save went through


def test_deleting_the_last_team_closes_the_fan_wear_store(admin_client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        ids = [c.id for c in Collection.query.filter(Collection.name.in_(
            [f'{n}: Rainbow Cheetahs' for n in ('Basketball', 'Soccer', 'Volleyball')])).all()]
    for coll_id in ids:
        admin_client.post(f'/admin/collections/{coll_id}/delete', follow_redirects=True)
    with app.app_context():
        assert not fan_store_for(_org(app)).is_active


def test_admin_orders_can_be_filtered_to_just_fan_wear(admin_client, app, seed):
    _build(admin_client, app, seed)
    fan_id, _ = _fan(app)
    with app.app_context():
        team_id = Collection.query.filter_by(name=TEAM).one().id
        for collection_id, number in ((fan_id, 'FAN-5001'), (team_id, 'TEAM-5001')):
            db.session.add(Order(order_number=number, collection_id=collection_id, email='x@example.com',
                                 first_name='X', last_name='Y', subtotal=5, total=5, status='pending'))
        db.session.commit()
    html = admin_client.get(f'/admin/orders?collection={fan_id}&status=all').get_data(as_text=True)
    assert 'FAN-5001' in html and 'TEAM-5001' not in html
    assert 'Fan Wear: Rainbow Cheetahs' in html                      # named in the store filter
