"""Turn an existing group order into a multi-team group, or add teams to one."""
from models import Collection, OrgSection, Organization, db


def _post(client, collection_id, names, first=''):
    data = {'org_team_names[]': names, 'first_team_name': first}
    return client.post(f'/admin/collections/{collection_id}/teams/add', data=data, follow_redirects=False)


def test_a_single_store_becomes_a_group_with_more_teams(app, seed, admin_client):
    cid = seed['collection_id']
    page = admin_client.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert 'id="addTeams"' in page and 'This store is for which team?' in page
    resp = _post(admin_client, cid, ['Soccer', 'Volleyball'], first='Basketball')
    assert resp.status_code == 302
    with app.app_context():
        base = db.session.get(Collection, cid)
        org = OrgSection.query.filter_by(collection_id=cid).first().organization
        labels = sorted(s.label for s in OrgSection.query.filter_by(organization_id=org.id).all())
        assert 'Basketball' in labels and 'Soccer' in labels and 'Volleyball' in labels
        assert base.name.startswith('Basketball: ')
        soccer = Collection.query.filter(Collection.name.like('Soccer: %')).one()
        assert soccer.slug != base.slug and list(soccer.products) == list(base.products)
    again = admin_client.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert 'This store is the <strong>Basketball</strong> team' in again and 'This store is for which team?' not in again


def test_more_teams_can_be_added_later(app, seed, admin_client):
    cid = seed['collection_id']
    _post(admin_client, cid, ['Soccer'], first='Basketball')
    _post(admin_client, cid, ['Cheer'])
    with app.app_context():
        org = OrgSection.query.filter_by(collection_id=cid).first().organization
        labels = {s.label for s in OrgSection.query.filter_by(organization_id=org.id).all()}
        assert {'Basketball', 'Cheer', 'Soccer'} <= labels


def test_bad_input_changes_nothing(app, seed, admin_client):
    cid = seed['collection_id']
    for names, first in ((['Soccer'], ''), ([''], 'Basketball'), (['Soccer', 'soccer'], 'Basketball'), (['Basketball'], 'Basketball')):
        _post(admin_client, cid, names, first=first)
    with app.app_context():
        assert Organization.query.count() == 0 or not OrgSection.query.filter_by(collection_id=cid).first()


def test_only_admins_can_add_teams_here(app, seed, guest):
    resp = guest.post(f"/admin/collections/{seed['collection_id']}/teams/add", data={'org_team_names[]': ['Soccer'], 'first_team_name': 'A'})
    assert resp.status_code in (302, 401, 403)
    with app.app_context():
        assert OrgSection.query.count() == 0


def test_new_teams_can_get_their_own_jerseys(app, seed, admin_client):
    from models import Product
    from utils.group_orders import team_store_config
    cid = seed['collection_id']
    with app.app_context():
        base = db.session.get(Collection, cid)
        shirt = base.products[0]
        color = (shirt.color_variants[0].color_name if getattr(shirt, 'color_variants', None) else None)
    if not color:
        import pytest
        pytest.skip('seed shirt has no color variants')
    data = {'org_team_names[]': ['Soccer', 'Cheer'], 'first_team_name': 'Basketball', 'org_style_mode': 'different',
            'org_team_uniform_product_id[]': [str(shirt.id), ''], 'org_team_home_color[]': [color, ''],
            'org_team_youth_product_id[]': ['', ''], 'org_team_away_product_id[]': ['', ''],
            'org_team_away_color[]': ['', ''], 'org_team_away_youth_product_id[]': ['', '']}
    assert admin_client.post(f'/admin/collections/{cid}/teams/add', data=data).status_code == 302
    with app.app_context():
        soccer = Collection.query.filter(Collection.name.like('Soccer: %')).one()
        cheer = Collection.query.filter(Collection.name.like('Cheer: %')).one()
        assert team_store_config(soccer)['uniform']['enabled'] is True
        assert team_store_config(cheer)['uniform']['enabled'] is False
