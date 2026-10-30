"""Add a team from the organization page: a new store copied from a team you already have."""
from models import Collection, OrgSection
from tests.test_group_order_audit import _build, _org_slug


def _labels(app, slug):
    with app.app_context():
        from models import Organization
        org = Organization.query.filter_by(slug=slug).one()
        return org, sorted(s.label for s in OrgSection.query.filter_by(organization_id=org.id).all())


def test_new_team_is_created_under_this_organization(admin_client, app, seed):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    resp = admin_client.post(f'/org/{slug}/manage', data={'action': 'new_team', 'label': 'Cheer'}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        store = Collection.query.filter_by(name='Cheer: Rainbow Cheetahs').one()
        basketball = Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one()
        assert store.slug != basketball.slug and list(store.products) == list(basketball.products)
    assert 'Cheer' in _labels(app, slug)[1]


def test_new_team_needs_a_name_and_a_new_name(admin_client, app, seed):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    before = _labels(app, slug)[1]
    admin_client.post(f'/org/{slug}/manage', data={'action': 'new_team', 'label': ''})
    admin_client.post(f'/org/{slug}/manage', data={'action': 'new_team', 'label': 'basketball'})
    assert _labels(app, slug)[1] == before


def test_manage_page_asks_for_a_name_not_a_store(admin_client, app, seed):
    _build(admin_client, app, seed)
    html = admin_client.get(f'/org/{_org_slug(app)}/manage').get_data(as_text=True)
    assert 'value="new_team"' in html and 'New team name' in html
