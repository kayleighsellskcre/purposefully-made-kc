"""Admin find and bulk edit."""
from models import Design, DesignCategoryLink, DesignCorrection, db
from utils import design_tags as dt


def _d(title, coll=None, live=True, **over):
    d = Design(filename=f'{title}.png', original_filename=f'{title}.png', file_path=f'uploads/{title}.png',
               title=title, is_gallery=live, design_fee=0, sku=f'SKU-{title}', **over)
    db.session.add(d)
    db.session.flush()
    if coll:
        db.session.add(DesignCategoryLink(design_id=d.id, category_key=coll, is_primary=True))
    return d


def _page(c, url='/admin/design-library/browse'):
    return c.get(url).get_data(as_text=True)


def test_search_finds_hidden_designs_and_understands_synonyms(app, seed, admin_client):
    with app.app_context():
        dt.ensure_vocabulary()
        a = _d('Best Mom Ever', 'family-relationships')
        dt.apply_auto_tags(a, ['mom'])
        _d('Hidden Gem', live=False)
        _d('Dad Joke')
        db.session.commit()
    assert 'Best Mom Ever' in _page(admin_client, '/admin/design-library/browse?q=mama')
    assert 'Dad Joke' not in _page(admin_client, '/admin/design-library/browse?q=mama')
    held = _page(admin_client, '/admin/design-library/browse?status=held')
    assert 'Hidden Gem' in held and 'Dad Joke' not in held


def test_filters_by_collection_tag_color_and_errors(app, seed, admin_client):
    with app.app_context():
        dt.ensure_vocabulary()
        a = _d('Red Crest', 'sports-game-day', color_families='red')
        dt.apply_auto_tags(a, ['football'])
        _d('Blue Cross', 'faith-inspiration', color_families='blue')
        _d('Broken One', ai_status='error', ai_error='timed out')
        db.session.commit()
    assert 'Red Crest' in _page(admin_client, '/admin/design-library/browse?collection=sports-game-day')
    assert 'Blue Cross' not in _page(admin_client, '/admin/design-library/browse?collection=sports-game-day')
    assert 'Red Crest' in _page(admin_client, '/admin/design-library/browse?tag=football')
    assert 'Blue Cross' in _page(admin_client, '/admin/design-library/browse?color=blue')
    err = _page(admin_client, '/admin/design-library/browse?status=errors')
    assert 'Broken One' in err and 'timed out' in err and 'Red Crest' not in err


def test_bulk_add_collection_and_tags_are_manual_locked_and_remembered(app, seed, admin_client):
    with app.app_context():
        dt.ensure_vocabulary()
        ids = [_d('One').id, _d('Two').id]
        db.session.commit()
    r = admin_client.post('/admin/design-library/browse', data={'ids': ids, 'action': 'add_collection',
                                                                 'collection': 'holidays-seasons:christmas'}, follow_redirects=True)
    assert 'Added to Christmas: 2 designs' in r.get_data(as_text=True)
    admin_client.post('/admin/design-library/browse', data={'ids': ids, 'action': 'add_tag', 'tag': 'vintage'})
    with app.app_context():
        for i in ids:
            link = DesignCategoryLink.query.filter_by(design_id=i).one()
            assert (link.category_key, link.subcategory_key, link.source, link.locked) == ('holidays-seasons', 'christmas', 'manual', True)
            assert 'vintage' in dt.design_tag_slugs(db.session.get(Design, i))
            assert db.session.get(Design, i).folder == 'holiday'
    admin_client.post('/admin/design-library/browse', data={'ids': ids, 'action': 'remove_tag', 'tag': 'vintage'})
    with app.app_context():
        assert 'vintage' not in dt.design_tag_slugs(db.session.get(Design, ids[0]))


def test_bulk_hide_and_show_never_delete(app, seed, admin_client):
    with app.app_context():
        d = _d('Keeper')
        db.session.commit()
        did = d.id
    admin_client.post('/admin/design-library/browse', data={'ids': [did], 'action': 'hide'})
    with app.app_context():
        assert db.session.get(Design, did).is_gallery is False
    admin_client.post('/admin/design-library/browse', data={'ids': [did], 'action': 'show'})
    with app.app_context():
        assert db.session.get(Design, did).is_gallery is True


def test_read_again_respects_your_locked_edits(app, seed, admin_client, monkeypatch):
    with app.app_context():
        dt.ensure_vocabulary()
        d = _d('Mine Now')
        dt.record_correction(d, 'title', 'Old', 'Mine Now', 'renamed')
        db.session.commit()
        did = d.id
    monkeypatch.setattr('utils.design_organizer._analyze', lambda *a, **k: __import__('utils.design_ai', fromlist=['x']).interpret(
        {'title': 'Different Name', 'visible_text': 'Mama', 'collections': [{'key': 'family-relationships', 'sub': 'moms', 'confidence': 0.95}],
         'tags': ['mom']}))
    r = admin_client.post('/admin/design-library/browse', data={'ids': [did], 'action': 'reread'}, follow_redirects=True)
    assert 'Read 1 design again' in r.get_data(as_text=True)
    with app.app_context():
        d = db.session.get(Design, did)
        assert d.title == 'Mine Now' and 'mom' in dt.design_tag_slugs(d)


def test_nothing_ticked_changes_nothing(app, seed, admin_client):
    r = admin_client.post('/admin/design-library/browse', data={'action': 'hide'}, follow_redirects=True)
    assert 'Tick the designs' in r.get_data(as_text=True)


def test_only_admins_get_in(client):
    assert client.get('/admin/design-library/browse').status_code in (302, 401, 403)
    assert client.post('/admin/design-library/browse', data={'action': 'hide'}).status_code in (302, 400, 401, 403)
