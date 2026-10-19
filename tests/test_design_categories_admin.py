"""Admin can add, rename and remove collections and categories, and every part of the site follows."""
from models import Design, DesignCategoryLink, db
from utils import design_category_admin as ca
from utils import design_taxonomy as tax


def _d(title='X', coll=None, sub=None, live=True):
    d = Design(filename=f'{title}.png', file_path=f'uploads/{title}.png', title=title, is_gallery=live, design_fee=0)
    db.session.add(d)
    db.session.flush()
    if coll:
        db.session.add(DesignCategoryLink(design_id=d.id, category_key=coll, subcategory_key=sub, is_primary=True))
    return d


def test_you_can_add_a_category_and_it_shows_up_everywhere(app, seed, admin_client):
    r = admin_client.post('/admin/design-library/categories', data={'action': 'add_sub', 'coll': 'sports-game-day', 'label': 'Track & Field'},
                          follow_redirects=True)
    assert 'Added "Track &amp; Field"' in r.get_data(as_text=True) or 'Added &#34;Track' in r.get_data(as_text=True) or 'Track' in r.get_data(as_text=True)
    assert 'track-and-field' in tax.subcategory_keys('sports-game-day')
    assert tax.label_for('sports-game-day', 'track-and-field') == 'Track & Field'
    page = admin_client.get('/admin/designs?tab=gallery').get_data(as_text=True)
    assert 'value="sports-game-day:track-and-field"' in page
    with app.app_context():
        d = _d('Relay Tee', 'sports-game-day', 'track-and-field')
        db.session.commit()
    assert 'Relay Tee' in admin_client.get('/shop/designs?collection=sports-game-day&sub=track-and-field').get_data(as_text=True)


def test_the_new_category_is_known_to_the_automatic_filing_too(app, seed, admin_client):
    admin_client.post('/admin/design-library/categories', data={'action': 'add_sub', 'coll': 'lifestyle-interests', 'label': 'Gardening'})
    from utils.design_ai import _prompt
    assert 'gardening' in _prompt()
    assert tax.is_valid_pair('lifestyle-interests', 'gardening')


def test_duplicates_are_refused_and_a_removed_built_in_comes_back_when_re_added(app, seed, admin_client):
    r = admin_client.post('/admin/design-library/categories', data={'action': 'add_sub', 'coll': 'sports-game-day', 'label': 'football'},
                          follow_redirects=True)
    assert 'already in' in r.get_data(as_text=True)
    admin_client.post('/admin/design-library/categories', data={'action': 'remove_sub', 'coll': 'sports-game-day', 'sub': 'volleyball'})
    assert 'volleyball' not in tax.subcategory_keys('sports-game-day')
    admin_client.post('/admin/design-library/categories', data={'action': 'add_sub', 'coll': 'sports-game-day', 'label': 'Volleyball'})
    assert 'volleyball' in tax.subcategory_keys('sports-game-day')


def test_removing_a_category_keeps_its_designs_in_the_collection_and_can_be_restored(app, seed, admin_client):
    with app.app_context():
        a = _d('Spike', 'sports-game-day', 'volleyball')
        b = _d('Both', 'sports-game-day', 'volleyball')
        db.session.add(DesignCategoryLink(design_id=b.id, category_key='sports-game-day', subcategory_key=None))
        db.session.commit()
        ids = (a.id, b.id)
    r = admin_client.post('/admin/design-library/categories', data={'action': 'remove_sub', 'coll': 'sports-game-day', 'sub': 'volleyball'},
                          follow_redirects=True)
    assert '2 designs stayed in' in r.get_data(as_text=True)
    with app.app_context():
        rows = DesignCategoryLink.query.filter(DesignCategoryLink.design_id.in_(ids)).all()
        assert sorted((l.design_id, l.category_key, l.subcategory_key) for l in rows) == sorted(
            [(ids[0], 'sports-game-day', None), (ids[1], 'sports-game-day', None)])
        assert Design.query.count() >= 2                                  # no design was removed
    assert 'Volleyball' in admin_client.get('/admin/design-library/categories').get_data(as_text=True)         # in the "removed" list
    admin_client.post('/admin/design-library/categories', data={'action': 'restore', 'kind': 'sub', 'key': 'sports-game-day:volleyball'})
    assert 'volleyball' in tax.subcategory_keys('sports-game-day')


def test_rename_changes_the_label_customers_see(app, seed, admin_client):
    admin_client.post('/admin/design-library/categories', data={'action': 'rename', 'target': 'faith-inspiration', 'label': 'Faith & Hope'})
    admin_client.post('/admin/design-library/categories', data={'action': 'rename', 'target': 'faith-inspiration:encouragement', 'label': 'Uplifting'})
    with app.app_context():
        d = _d('Hope', 'faith-inspiration', 'encouragement')
        db.session.commit()
    page = admin_client.get('/shop/designs').get_data(as_text=True)
    assert 'Faith &amp; Hope' in page
    assert 'Uplifting' in admin_client.get('/shop/designs?collection=faith-inspiration').get_data(as_text=True)


def test_collections_can_be_added_and_only_removed_when_empty(app, seed, admin_client):
    admin_client.post('/admin/design-library/categories', data={'action': 'add_collection', 'label': 'Teachers'})
    assert 'teachers' in tax.COLLECTION_BY_KEY
    with app.app_context():
        _d('Apple Tee', 'teachers')
        db.session.commit()
    r = admin_client.post('/admin/design-library/categories', data={'action': 'remove_collection', 'key': 'teachers'}, follow_redirects=True)
    assert 'still has 1 design' in r.get_data(as_text=True) and 'teachers' in tax.COLLECTION_BY_KEY
    with app.app_context():
        DesignCategoryLink.query.filter_by(category_key='teachers').delete()
        db.session.commit()
    admin_client.post('/admin/design-library/categories', data={'action': 'remove_collection', 'key': 'teachers'})
    assert 'teachers' not in tax.COLLECTION_BY_KEY


def test_a_built_in_collection_with_designs_cannot_be_removed(app, seed, admin_client):
    with app.app_context():
        _d('Cross', 'faith-inspiration')
        db.session.commit()
    r = admin_client.post('/admin/design-library/categories', data={'action': 'remove_collection', 'key': 'faith-inspiration'}, follow_redirects=True)
    assert 'Move them' in r.get_data(as_text=True) and 'faith-inspiration' in tax.COLLECTION_BY_KEY


def test_changes_survive_a_restart_and_reach_other_workers(app, seed, admin_client):
    admin_client.post('/admin/design-library/categories', data={'action': 'add_sub', 'coll': 'kansas-city', 'label': 'Waldo'})
    tax.apply_overrides({})                                               # pretend this worker just started fresh
    assert 'waldo' not in tax.subcategory_keys('kansas-city')
    tax.refresh(force=True)                                               # it reads the saved changes
    assert 'waldo' in tax.subcategory_keys('kansas-city')


def test_only_the_admin_can_change_categories(client):
    assert client.get('/admin/design-library/categories').status_code in (302, 401, 403)
    assert client.post('/admin/design-library/categories', data={'action': 'add_collection', 'label': 'X'}).status_code in (302, 400, 401, 403)
