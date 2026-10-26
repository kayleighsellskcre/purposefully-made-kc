"""Delete several stores, schools or group orders at once, and never lose an order or a sign-up."""
from datetime import datetime

from models import (Collection, District, GroupRosterEntry, Order, OrderItem, Organization, OrgSection, Product,
                    SponsorSubmission, User, db)
from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL
from utils import districts as DS
from utils.group_delete import remove_organization, remove_stores, store_activity, summary


def _district(app, seed, stores=('Football', 'Volleyball', 'Band', 'Fall Festival')):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district('Desoto USD 232', [
            ('Mill Valley High', 'high', list(stores), {}), ('Riverview Elementary', 'elementary', ['Band'], {})])
        for school in d.schools.all():
            for store in DS.stores_of(school, True):
                store.products.append(tee)
        db.session.commit()
        schools = {s.short_slug: s.id for s in d.schools.all()}
        return d.id, schools['mill-valley'], schools['riverview']


def _store(app, school_id, label):
    with app.app_context():
        school = db.session.get(Organization, school_id)
        return next(s for s in DS.stores_of(school, True) if DS.store_label(s) == label).id


def _order_for(app, seed, store_id, number='PMKC-DEL1'):
    with app.app_context():
        o = Order(order_number=number, email='p@example.com', first_name='Pat', last_name='Parent', subtotal=30.0, total=30.0,
                  payment_status='paid', status='paid', payment_method='stripe', collection_id=store_id, paid_at=datetime.utcnow())
        db.session.add(o)
        db.session.flush()
        db.session.add(OrderItem(order_id=o.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black',
                                 quantity=1, unit_price=30.0, subtotal=30.0, collection_id=store_id))
        db.session.commit()


def _exists(app, store_id):
    with app.app_context():
        return db.session.get(Collection, store_id) is not None


def test_a_store_with_nothing_on_it_is_deleted_for_good(app, seed):
    did, mill, _ = _district(app, seed)
    band = _store(app, mill, 'Band')
    with app.app_context():
        deleted, kept = remove_stores([db.session.get(Collection, band)])
        assert deleted == ['Mill Valley Band'] and kept == []
    assert not _exists(app, band)
    with app.app_context():
        assert OrgSection.query.filter_by(collection_id=band).count() == 0


def test_a_store_with_orders_is_turned_off_and_kept_with_its_orders(app, seed):
    did, mill, _ = _district(app, seed)
    fb = _store(app, mill, 'Football')
    _order_for(app, seed, fb)
    with app.app_context():
        assert store_activity(db.session.get(Collection, fb))['orders'] == 1
        deleted, kept = remove_stores([db.session.get(Collection, fb)])
        assert deleted == [] and kept == ['Mill Valley Football']
    with app.app_context():
        store = db.session.get(Collection, fb)
        assert store is not None and store.is_active is False and store.show_in_directory is False
        assert Order.query.filter_by(order_number='PMKC-DEL1').one().collection_id == fb


def test_roster_names_and_sponsor_requests_also_protect_a_store(app, seed):
    did, mill, _ = _district(app, seed)
    vb, band = _store(app, mill, 'Volleyball'), _store(app, mill, 'Band')
    with app.app_context():
        db.session.add(GroupRosterEntry(collection_id=vb, first_name='Ava', last_name='Lopez', size='M'))
        db.session.add(SponsorSubmission(collection_id=band, first_name='Ben', last_name='Lee', email='b@example.com', items_json='[]'))
        db.session.commit()
        deleted, kept = remove_stores([db.session.get(Collection, vb), db.session.get(Collection, band)])
        assert deleted == [] and len(kept) == 2


def test_the_summary_says_what_happened_in_plain_words():
    assert summary(['A', 'B'], []) == 'Deleted 2 stores.'
    assert summary([], ['C']) == '1 store has orders or sign-ups, so it was turned off and kept: C.'
    assert summary(['A'], ['B', 'C']) .startswith('Deleted 1 store. 2 stores have orders or sign-ups, so they were turned off and kept: B, C.')
    assert summary([], []) == 'Nothing was selected.'


def test_the_district_screen_selects_and_deletes_several_stores_but_never_school_spirit(app, seed, client, login):
    did, mill, _ = _district(app, seed)
    spirit = DS.stores_of
    with app.app_context():
        school = db.session.get(Organization, mill)
        spirit_id = DS.spirit_store(school).id
    ids = [_store(app, mill, n) for n in ('Football', 'Volleyball', 'Fall Festival')]
    login(client, ADMIN_EMAIL)
    resp = client.post(f'/admin/districts/{did}', data={'action': 'delete_stores', 'store_id': [str(i) for i in ids + [spirit_id]]})
    assert resp.status_code == 302
    assert all(not _exists(app, i) for i in ids) and _exists(app, spirit_id)
    assert _exists(app, _store(app, mill, 'Band'))


def test_a_store_from_another_district_cannot_be_deleted_from_this_screen(app, seed, client, login):
    did, mill, _ = _district(app, seed)
    with app.app_context():
        other = Collection(name='Someone Else', slug='someone-else', is_active=True)
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    login(client, ADMIN_EMAIL)
    client.post(f'/admin/districts/{did}', data={'action': 'delete_stores', 'store_id': [str(other_id)]})
    assert _exists(app, other_id)


def test_the_district_screen_has_a_select_bar_per_school_with_the_kinds_present(app, seed, client, login):
    did, mill, river = _district(app, seed)
    login(client, ADMIN_EMAIL)
    html = client.get(f'/admin/districts/{did}').get_data(as_text=True)
    assert f'id="bulkStores{mill}"' in html and f'id="bulkStores{river}"' in html
    mill_bar = html.split(f'id="bulkStores{mill}"')[1].split('</form>')[0]
    assert 'data-bulk-select="sport"' in mill_bar and 'data-bulk-select="activity"' in mill_bar and 'data-bulk-select="event"' in mill_bar
    assert 'data-bulk-select="teacher"' not in mill_bar and 'data-bulk-select="staff"' not in mill_bar
    assert html.count('class="bulk-pick"') == 5 and 'js/bulk-delete.js' in html            # Spirit rows have no box
    assert 'Delete this district' in html


def test_delete_a_school_removes_it_and_its_stores(app, seed, client, login):
    did, mill, river = _district(app, seed)
    store_ids = [s.id for s in DS.stores_of(db.session.get(Organization, mill), True)] if False else None
    with app.app_context():
        store_ids = [s.id for s in DS.stores_of(db.session.get(Organization, river), True)]
    login(client, ADMIN_EMAIL)
    resp = client.post(f'/admin/districts/school/{river}', data={'action': 'delete_school'})
    assert resp.status_code == 302 and f'/admin/districts/{did}' in resp.headers['Location']
    with app.app_context():
        assert db.session.get(Organization, river) is None
        assert all(db.session.get(Collection, i) is None for i in store_ids)
        assert db.session.get(Organization, mill) is not None


def test_a_school_with_orders_is_turned_off_not_erased(app, seed, client, login):
    did, mill, river = _district(app, seed)
    _order_for(app, seed, _store(app, river, 'Band'))
    login(client, ADMIN_EMAIL)
    client.post(f'/admin/districts/school/{river}', data={'action': 'delete_school'})
    with app.app_context():
        school = db.session.get(Organization, river)
        assert school is not None and school.is_active is False
        assert Order.query.filter_by(order_number='PMKC-DEL1').one().collection_id is not None
    assert client.get('/org/desoto-usd-232/riverview-elementary').status_code == 404


def test_delete_a_whole_district(app, seed, client, login):
    did, mill, river = _district(app, seed)
    login(client, ADMIN_EMAIL)
    resp = client.post(f'/admin/districts/{did}', data={'action': 'delete_district'})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(District, did) is None and Organization.query.filter(Organization.district_id.isnot(None)).count() == 0
        assert Collection.query.filter(Collection.short_slug.isnot(None)).count() == 0


def test_a_district_with_orders_is_turned_off_and_kept(app, seed, client, login):
    did, mill, river = _district(app, seed)
    _order_for(app, seed, _store(app, mill, 'Band'))
    login(client, ADMIN_EMAIL)
    client.post(f'/admin/districts/{did}', data={'action': 'delete_district'})
    with app.app_context():
        d = db.session.get(District, did)
        assert d is not None and d.is_active is False
        assert Order.query.count() == 1
    assert client.get('/org/desoto-usd-232').status_code == 404


def test_the_group_orders_list_deletes_several_at_once_and_whole_organizations(app, seed, client, login):
    with app.app_context():
        made = []
        for n in range(3):
            c = Collection(name=f'Spare {n}', slug=f'spare-{n}', is_active=True)
            db.session.add(c)
            made.append(c)
        org = Organization(name='Rainbow Cheetahs', slug='rainbow-cheetahs', is_active=True)
        db.session.add(org)
        db.session.flush()
        team = Collection(name='Basketball: Rainbow Cheetahs', slug='rc-basketball', is_active=True)
        db.session.add(team)
        db.session.flush()
        db.session.add(OrgSection(organization_id=org.id, collection_id=team.id, label='Basketball'))
        db.session.commit()
        ids, org_id, team_id = [c.id for c in made], org.id, team.id
    login(client, ADMIN_EMAIL)
    html = client.get('/admin/collections').get_data(as_text=True)
    assert 'id="bulkCollections"' in html and html.count('name="store_id"') >= 4 and f'name="org_id" value="{org_id}"' in html
    resp = client.post('/admin/collections/bulk-delete', data={'store_id': [str(ids[0]), str(ids[1])], 'org_id': [str(org_id)]})
    assert resp.status_code == 302
    assert not _exists(app, ids[0]) and not _exists(app, ids[1]) and _exists(app, ids[2])
    with app.app_context():
        assert db.session.get(Organization, org_id) is None and db.session.get(Collection, team_id) is None


def test_a_group_order_with_orders_is_kept_when_it_is_in_the_bulk_delete(app, seed, client, login):
    _order_for(app, seed, seed['collection_id'])
    login(client, ADMIN_EMAIL)
    client.post('/admin/collections/bulk-delete', data={'store_id': [str(seed['collection_id'])]})
    with app.app_context():
        store = db.session.get(Collection, seed['collection_id'])
        assert store is not None and store.is_active is False


def test_only_the_owner_can_use_the_bulk_delete(app, seed):
    visitor = app.test_client()
    shopper = app.test_client()
    shopper.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': 'TestPassw0rd!23'})
    for client in (visitor, shopper):
        resp = client.post('/admin/collections/bulk-delete', data={'store_id': [str(seed['collection_id'])]})
        assert resp.status_code in (302, 401, 403, 404)
    assert _exists(app, seed['collection_id'])


def test_an_organizer_deletes_their_own_group_orders_but_not_anyone_elses(app, seed, client, login):
    with app.app_context():
        me = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        other = User.query.filter_by(email='other-test@example.com').first()
        mine = [Collection(name=f'Mine {n}', slug=f'mine-{n}', is_active=True, created_by_user_id=me.id) for n in range(2)]
        theirs = Collection(name='Theirs', slug='theirs', is_active=True, created_by_user_id=other.id)
        db.session.add_all(mine + [theirs])
        db.session.commit()
        mine_ids, theirs_id = [c.id for c in mine], theirs.id
    login(client, CUSTOMER_EMAIL)
    html = client.get('/account/group-orders').get_data(as_text=True)
    assert 'id="bulkMine"' in html and html.count('name="store_id"') == 2 and 'js/bulk-delete.js' in html
    resp = client.post('/account/group-orders/delete', data={'store_id': [str(i) for i in mine_ids + [theirs_id]]})
    assert resp.status_code == 302
    assert all(not _exists(app, i) for i in mine_ids) and _exists(app, theirs_id)


def test_the_select_bar_script_and_pages_agree_on_the_checkbox_contract(app, seed):
    js = open('static/js/bulk-delete.js', encoding='utf-8').read()
    for needle in ('input.bulk-pick[form=', 'data-bulk-select', 'data-bulk-delete', 'window.confirm', 'turned off and kept'):
        assert needle in js, needle
