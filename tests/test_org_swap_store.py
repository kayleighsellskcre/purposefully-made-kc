"""Point a team at an older store (orders stay with that store) and forward the old link."""
from models import Collection, OrgSection
from tests.test_group_order_audit import _build, _org_slug


def _older_store(app, name='Older Basketball', slug='older-basketball'):
    from models import db
    with app.app_context():
        base = Collection.query.filter_by(name='Basketball: Rainbow Cheetahs').one()
        old = Collection(name=name, slug=slug, is_active=True)
        db.session.add(old)
        db.session.commit()
        return old.id, base.id


def test_team_can_switch_to_an_older_store_and_the_replaced_one_is_turned_off(admin_client, app, seed):
    _build(admin_client, app, seed)
    slug = _org_slug(app)
    old_id, new_id = _older_store(app)
    with app.app_context():
        section = OrgSection.query.filter_by(collection_id=new_id).one()
        section_id = section.id
    html = admin_client.get(f'/org/{slug}/manage').get_data(as_text=True)
    assert 'Older Basketball' in html and 'value="swap_store"' in html
    admin_client.post(f'/org/{slug}/manage', data={'action': 'swap_store', 'section_id': section_id, 'collection_id': old_id},
                      follow_redirects=True)
    with app.app_context():
        assert OrgSection.query.get(section_id).collection_id == old_id
        assert Collection.query.get(old_id).is_active is True
        replaced = Collection.query.get(new_id)
        assert replaced is not None and replaced.is_active is False


def test_old_link_forwards_to_the_store_that_took_its_place(client, app, seed):
    from models import db
    from routes import collection as C
    with app.app_context():
        db.session.add(Collection(name='Live', slug='live-store', is_active=True))
        db.session.commit()
    C.RETIRED_LINKS['gone-store'] = 'live-store'
    try:
        resp = client.get('/c/gone-store')
        assert resp.status_code == 301 and resp.headers['Location'].endswith('/c/live-store')
        assert client.get('/c/never-existed').status_code == 404
    finally:
        C.RETIRED_LINKS.pop('gone-store', None)
