"""One structure for every collection: collection, then subcategory. Music is not special any more."""
import io

from models import Design, DesignCategoryLink, DesignCorrection, db
from utils import design_places as dp


def _d(**over):
    fields = dict(filename='x.png', file_path='uploads/x.png', title='X', is_gallery=True, design_fee=0)
    fields.update(over)
    d = Design(**fields)
    db.session.add(d)
    db.session.flush()
    return d


def test_places_are_checked_and_a_subcategory_implies_its_collection():
    class Form(dict):
        def getlist(self, k):
            return self.get(k, [])
    got = dp.parse_places(Form(place=['sports-game-day', 'sports-game-day:football', 'made-up', 'sports-game-day:moms',
                                      'faith-inspiration', 'faith-inspiration', 'music-entertainment:country-music']))
    assert got == [('sports-game-day', 'football'), ('faith-inspiration', None), ('music-entertainment', 'country-music')]


def test_every_collection_has_the_same_two_level_picker(app, seed, admin_client):
    html = admin_client.get('/admin/designs?tab=gallery').get_data(as_text=True)
    for label in ('Kansas City', 'Faith &amp; Inspiration', 'Sports &amp; Game Day', 'School Spirit', 'Music &amp; Entertainment',
                  'Funny &amp; Sarcastic', 'Family &amp; Relationships', 'Lifestyle &amp; Interests', 'Holidays &amp; Seasons', 'Luxury Basics'):
        assert label in html
    assert 'value="music-entertainment:country-music"' in html and 'value="sports-game-day:football"' in html
    assert 'value="fan-favorites"' not in html and 'value="evergreen"' not in html      # Fan Favorites builds itself now
    assert 'name="upload_cats"' not in html and 'Music genre' not in html


def test_old_music_genres_and_folders_show_up_in_the_new_places(app, seed):
    with app.app_context():
        d = _d(folder='sports', extra_categories='country,kc')
        assert dp.current_places(d) == [('sports-game-day', None), ('music-entertainment', 'country-music'), ('kansas-city', None)]
        g = _d(folder='funny', extra_categories='gospel,rock')
        assert ('faith-inspiration', 'faith-based') in dp.current_places(g)


def test_editing_places_saves_manual_locked_links_and_keeps_the_old_folders_in_step(app, seed, admin_client):
    with app.app_context():
        d = _d(folder='sports')
        db.session.commit()
        did = d.id
    r = admin_client.post(f'/admin/design-gallery/{did}/edit', data={
        'title': 'Edited', 'places_present': '1',
        'place': ['music-entertainment', 'music-entertainment:country-music', 'family-relationships:moms']},
        headers={'X-Requested-With': 'XMLHttpRequest'})
    body = r.get_json()
    assert r.status_code == 200 and body['design']['places'] == 'music-entertainment:country-music|family-relationships:moms'
    assert 'Music & Entertainment / Country Music' in body['design']['places_label']
    with app.app_context():
        d = db.session.get(Design, did)
        links = DesignCategoryLink.query.filter_by(design_id=did).order_by(DesignCategoryLink.id).all()
        assert [(l.category_key, l.subcategory_key, l.source, l.locked, l.is_primary) for l in links] == [
            ('music-entertainment', 'country-music', 'manual', True, True), ('family-relationships', 'moms', 'manual', True, False)]
        assert d.folder == 'music' and d.extra_categories == 'couples'
        assert DesignCorrection.query.filter_by(design_id=did, correction_type='categories_changed').count() == 1


def test_an_edit_with_no_places_is_refused(app, seed, admin_client):
    with app.app_context():
        d = _d(folder='sports')
        db.session.commit()
        did = d.id
    r = admin_client.post(f'/admin/design-gallery/{did}/edit', data={'title': 'X', 'places_present': '1'},
                          headers={'X-Requested-With': 'XMLHttpRequest'})
    assert r.status_code == 400 and 'where this design belongs' in r.get_json()['error']


def test_the_edit_box_is_prefilled_from_the_saved_places(app, seed, admin_client):
    with app.app_context():
        d = _d(folder='music', extra_categories='rock')
        db.session.commit()
        did = d.id
    html = admin_client.get('/admin/designs?tab=gallery').get_data(as_text=True)
    assert f'data-design-id="{did}"' in html
    assert 'data-places="music-entertainment|music-entertainment:rock-and-retro"' in html or \
           'data-places="music-entertainment:rock-and-retro"' in html


def test_uploading_into_chosen_places_files_it_exactly_there_without_counting_as_a_correction(app, seed, admin_client, monkeypatch):
    import routes.admin as admin_routes

    def fake_save(file, user_id, **kw):
        d = _d(filename='up.png', file_path='uploads/up.png', original_filename=file.filename)
        d.uploaded_by_user_id = user_id
        return d
    monkeypatch.setattr(admin_routes, '_save_uploaded_design', fake_save)
    r = admin_client.post('/admin/design-gallery/upload', data={
        'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 40), 'logo.png'), 'title': 'Western Boot',
        'place': ['lifestyle-interests:western-and-country']},
        content_type='multipart/form-data', headers={'X-Requested-With': 'XMLHttpRequest'})
    body = r.get_json()
    assert r.status_code == 200 and body['ok'] and not body['held']
    with app.app_context():
        links = DesignCategoryLink.query.filter_by(design_id=body['design_id']).all()
        assert [(l.category_key, l.subcategory_key, l.source) for l in links] == [('lifestyle-interests', 'western-and-country', 'manual')]
        assert DesignCorrection.query.filter_by(design_id=body['design_id']).count() == 0
        assert db.session.get(Design, body['design_id']).folder == 'evergreen'     # a collection with no old folder stays visible


def test_a_color_version_edit_does_not_change_places(app, seed, admin_client):
    with app.app_context():
        parent = _d(folder='sports')
        child = _d(folder='sports', parent_design_id=parent.id, variant_label='Navy')
        db.session.commit()
        cid = child.id
    r = admin_client.post(f'/admin/design-gallery/{cid}/edit', data={'title': 'T', 'places_present': '1', 'place': ['kansas-city']},
                          headers={'X-Requested-With': 'XMLHttpRequest'})
    assert r.status_code == 200
    with app.app_context():
        assert DesignCategoryLink.query.filter_by(design_id=cid).count() == 0
