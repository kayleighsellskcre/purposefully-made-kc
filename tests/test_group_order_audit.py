"""Group order audit: real-world situations around organizations and team stores.

Each test builds a Rainbow Cheetahs organization (Basketball, Soccer, Volleyball)
and then does something an admin or shopper really might do.
"""
import json
from datetime import datetime, timedelta

from models import db, Collection, Organization, OrgSection
from tests.test_org_fan_wear import _build, _org_slug, _store
from utils.group_orders import org_fan_hub


def _set(app, name, **fields):
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        for key, value in fields.items():
            setattr(coll, key, value)
        db.session.commit()


def _slug_of(app, name):
    return _store(app, name)[1]


# ── Hidden / closed / protected teams ────────────────────────────────────────

def test_a_hidden_team_is_not_linked_from_the_org_page_or_team_bar(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    soccer = _slug_of(app, 'Soccer: Rainbow Cheetahs')
    _set(app, 'Soccer: Rainbow Cheetahs', is_active=False)
    landing = client.get(f'/org/{_org_slug(app)}').get_data(as_text=True)
    assert f'/c/{soccer}"' not in landing
    team = client.get(f'/c/{_slug_of(app, "Basketball: Rainbow Cheetahs")}').get_data(as_text=True)
    assert f'/c/{soccer}"' not in team
    assert client.get(f'/c/{soccer}').status_code == 404


def test_a_pay_for_everyone_team_is_never_the_fan_wear_page(admin_client, app, seed):
    from utils.group_roster import ORGANIZER_PAYS
    _build(admin_client, app, seed)
    _set(app, 'Basketball: Rainbow Cheetahs', payment_mode=ORGANIZER_PAYS)
    with app.app_context():
        org = Organization.query.filter_by(slug=_org_slug(app)).one()
        hub, _dedicated = org_fan_hub(org)
        assert hub is not None and hub.name != 'Basketball: Rainbow Cheetahs'


def test_a_team_that_closes_stops_taking_cart_items(admin_client, client, app, seed):
    """A shopper who opened the store while it was open cannot add after the deadline."""
    _build(admin_client, app, seed)
    name = 'Basketball: Rainbow Cheetahs'
    slug = _slug_of(app, name)
    client.get(f'/c/{slug}?path=fan')                       # shopper is inside the store
    _set(app, name, order_deadline=datetime.utcnow() - timedelta(days=2))
    page = client.get(f'/c/{slug}?path=fan').get_data(as_text=True)
    assert 'Ordering is closed' in page
    with client.session_transaction() as sess:
        sess['collection_id'] = _store(app, name)[0]         # still attached from before the deadline
    resp = client.post('/cart/add', data={
        'product_id': seed['hoodie_id'], 'size': 'M', 'color': 'Black',
        'quantity': 1, 'placement': 'center_chest', 'catalog_section': 'fan',
    })
    assert not resp.get_json().get('success')
    with client.session_transaction() as sess:
        assert not sess.get('cart')


def test_a_password_protected_team_asks_for_the_password(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    name = 'Basketball: Rainbow Cheetahs'
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        coll.set_password('letmein')
        db.session.commit()
    admin_client.get('/auth/logout')                 # admins skip the code, so look as a guest
    resp = client.get(f'/c/{_slug_of(app, name)}')
    assert resp.status_code == 302 and '/password' in resp.headers['Location']


# ── Deleting things ──────────────────────────────────────────────────────────

def test_deleting_a_team_store_keeps_the_organization_working(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    soccer_id = _store(app, 'Soccer: Rainbow Cheetahs')[0]
    admin_client.post(f'/admin/collections/{soccer_id}/delete', follow_redirects=True)
    slug = _org_slug(app)
    for path in (f'/org/{slug}', f'/org/{slug}/manage', f'/org/{slug}/fan-wear', '/shop/group-orders', '/admin/collections'):
        assert admin_client.get(path).status_code == 200, path
    with app.app_context():
        assert OrgSection.query.filter_by(collection_id=soccer_id).count() == 0


def test_an_organization_with_no_teams_left_says_it_is_being_set_up(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    for name in ('Basketball', 'Soccer', 'Volleyball'):
        coll_id = _store(app, f'{name}: Rainbow Cheetahs')[0]
        admin_client.post(f'/admin/collections/{coll_id}/delete', follow_redirects=True)
    slug = _org_slug(app)
    assert 'being set up' in client.get(f'/org/{slug}').get_data(as_text=True)
    assert admin_client.get(f'/org/{slug}/fan-wear').status_code == 302      # sent back to add a team
    assert admin_client.get(f'/org/{slug}/manage').status_code == 200


def test_deleting_an_organization_keeps_its_stores(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    resp = admin_client.post(f'/org/{slug}/manage', data={'action': 'delete_org'}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert Organization.query.filter_by(slug=slug).count() == 0
        assert OrgSection.query.count() == 0
        names = {c.name for c in Collection.query.all()}
        assert {'Basketball: Rainbow Cheetahs', 'Soccer: Rainbow Cheetahs', 'Volleyball: Rainbow Cheetahs'} <= names
    team = client.get(f'/c/{_slug_of(app, "Basketball: Rainbow Cheetahs")}')
    assert team.status_code == 200 and 'org-collection-nav' not in team.get_data(as_text=True)


def test_only_a_site_admin_can_delete_an_organization(admin_client, app, seed):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    with app.app_context():
        org = Organization.query.filter_by(slug=slug).one()
        org.set_password('organizer-pass')
        db.session.commit()
    admin_client.get('/auth/logout')
    from tests.conftest import _login, CUSTOMER_EMAIL
    _login(admin_client, CUSTOMER_EMAIL)
    with admin_client.session_transaction() as sess:
        sess[f'org_auth_{_org_id(app, slug)}'] = True      # signed in as the organizer, not an admin
    admin_client.post(f'/org/{slug}/manage', data={'action': 'delete_org'}, follow_redirects=True)
    with app.app_context():
        assert Organization.query.filter_by(slug=slug).count() == 1


def _org_id(app, slug):
    with app.app_context():
        return Organization.query.filter_by(slug=slug).one().id


# ── Public list ──────────────────────────────────────────────────────────────

def test_a_hidden_organization_does_not_leak_its_teams_into_the_public_list(admin_client, client, app, seed):
    _build(admin_client, app, seed)
    with app.app_context():
        for coll in Collection.query.filter(Collection.name.like('%: Rainbow Cheetahs')).all():
            coll.show_in_directory = True
        Organization.query.filter_by(slug=_org_slug(app)).one().is_active = False
        db.session.commit()
    html = client.get('/shop/group-orders').get_data(as_text=True)
    assert 'Rainbow Cheetahs' not in html.split('Open Group Orders')[-1]
