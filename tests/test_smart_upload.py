"""Stage 2: smart upload files a design everywhere it belongs, and asks only when unsure."""
import io
import json

import pytest

from models import Design, DesignCategoryLink, DesignCorrection, DesignTagLink, db
from utils import design_ai as ai
from utils import design_tags as dt
from utils.design_taxonomy import label_for


def _ready(app):
    with app.app_context():
        dt.ensure_vocabulary()


def _raw(**over):
    raw = {'title': 'Vintage Kansas City Football Mama', 'colors': ['Black', 'Red'],
           'visible_text': 'Kansas City Football Mama', 'style': 'vintage', 'audience': 'mom',
           'collections': [{'key': 'sports-game-day', 'sub': 'football', 'confidence': 0.93},
                           {'key': 'family-relationships', 'sub': 'moms', 'confidence': 0.88}],
           'tags': ['football-mom', 'vintage', 'kansas-city'], 'keywords': ['mama', 'game day'], 'protected': False}
    raw.update(over)
    return raw


# -- Checking what the model says -----------------------------------------------

def test_unknown_collections_and_bad_subcategories_are_dropped(app, seed):
    _ready(app)
    with app.app_context():
        result = ai.interpret(_raw(tags=[], collections=[
            {'key': 'made-up', 'sub': None, 'confidence': 0.99},
            {'key': 'sports-game-day', 'sub': 'moms', 'confidence': 1.7},        # wrong sub, confidence clamped
            {'key': 'funny-sarcastic', 'sub': 'funny-sayings', 'confidence': 'high'},
        ]))
        keys = {p['key']: p for p in result['collections']}
        assert 'made-up' not in keys
        assert keys['sports-game-day']['sub'] is None and keys['sports-game-day']['confidence'] == 1.0
        assert keys['funny-sarcastic']['confidence'] == 0.0


def test_a_team_is_only_named_when_its_words_are_visible(app, seed):
    _ready(app)
    with app.app_context():
        guessed = ai.interpret(_raw(visible_text='Game Day', title='Red Game Day Tee', tags=['kc-chiefs', 'football', 'game-day']))
        assert 'kc-chiefs' not in guessed['tags'] and 'kc-chiefs' in guessed['dropped_tags']
        assert 'football' in guessed['tags']
        shown = ai.interpret(_raw(visible_text='Chiefs Kingdom', tags=['kc-chiefs']))
        assert 'kc-chiefs' in shown['tags'] and 'football' in shown['tags']        # implied sport comes along


def test_a_specific_kc_team_subcategory_needs_the_name_visible(app, seed):
    _ready(app)
    with app.app_context():
        result = ai.interpret(_raw(visible_text='Kansas City', tags=['kansas-city'], collections=[
            {'key': 'kansas-city', 'sub': 'kc-chiefs', 'confidence': 0.9}]))
        place = result['collections'][0]
        assert place['sub'] != 'kc-chiefs' and place['confidence'] <= 0.6               # general KC pride at most


def test_protected_names_are_flagged_but_never_block_filing(app, seed):
    _ready(app)
    with app.app_context():
        result = ai.interpret(_raw(visible_text='Taylor Swift Eras Tour', protected=False, tags=['concert']))
        assert result['protected'] and 'taylor swift' in result['protected_words']
        assert result['collections']                                                    # still filed
        assert not ai.interpret(_raw(visible_text='Mama', tags=['mom'], title='Mama')).get('protected')


def test_a_missing_subcategory_is_filled_in_from_the_tags(app, seed):
    _ready(app)
    with app.app_context():
        result = ai.interpret(_raw(tags=['mom'], collections=[{'key': 'family-relationships', 'sub': None, 'confidence': 0.9}]))
        assert result['collections'][0]['sub'] == 'moms'


def test_without_the_ai_the_name_alone_files_it_with_modest_confidence(app, seed):
    _ready(app)
    with app.app_context():
        result = ai.classify_from_text('', 'vintage-football-mama.png')
        assert {'football', 'mom', 'vintage'} <= set(result['tags'])
        assert {p['key'] for p in result['collections']} >= {'sports-game-day', 'family-relationships'}
        assert result['confidence'] == 0.6                                              # below the auto threshold: review


# -- Writing it onto a design ----------------------------------------------------

def _design(app, **over):
    with app.app_context():
        design = Design(filename='x.png', file_path='designs/x.png', title='Football Mama', is_gallery=True, **over)
        db.session.add(design)
        db.session.commit()
        return design.id


def test_confident_results_are_applied_and_mirrored_to_the_existing_folders(app, seed):
    _ready(app)
    did = _design(app)
    with app.app_context():
        design = db.session.get(Design, did)
        status = ai.apply_classification(design, ai.interpret(_raw()), chose_folder=False)
        db.session.commit()
        assert status == 'done' and design.ai_status == 'done'
        links = DesignCategoryLink.query.filter_by(design_id=did).order_by(DesignCategoryLink.is_primary.desc()).all()
        assert [(l.category_key, l.subcategory_key, l.is_primary) for l in links] == [
            ('sports-game-day', 'football', True), ('family-relationships', 'moms', False)]
        assert design.folder == 'sports' and design.extra_categories == 'couples'     # the gallery you have keeps working
        assert {'football', 'mom', 'football-mom', 'vintage'} <= set(dt.design_tag_slugs(design))
        assert design.style == 'Vintage' and design.audience == 'Mom' and 'mama' in design.keywords
        assert design.ai_confidence == pytest.approx(0.93)


def test_unsure_categories_are_not_applied_and_the_design_needs_review(app, seed):
    _ready(app)
    did = _design(app)
    with app.app_context():
        design = db.session.get(Design, did)
        result = ai.interpret(_raw(collections=[{'key': 'sports-game-day', 'sub': 'football', 'confidence': 0.55}], tags=[]))
        assert ai.apply_classification(design, result, chose_folder=False) == 'needs_review'
        db.session.commit()
        assert DesignCategoryLink.query.filter_by(design_id=did).count() == 0
        assert json.loads(design.ai_suggestions)['unsure'][0]['key'] == 'sports-game-day'


def test_your_own_folder_choice_and_locked_edits_are_never_overwritten(app, seed):
    _ready(app)
    did = _design(app, folder='school')
    with app.app_context():
        design = db.session.get(Design, did)
        dt.record_correction(design, 'title', 'Football Mama', 'Football Mama (mine)', 'renamed')
        dt.record_correction(design, 'style', 'Bold', 'Minimal', 'style_changed')
        design.style = 'Minimal'
        ai.link_manual_folders(design, ['school'])
        ai.apply_classification(design, ai.interpret(_raw()), chose_folder=True)
        db.session.commit()
        assert design.folder == 'school'                                                # you picked it, so it stays
        assert design.style == 'Minimal' and design.title == 'Football Mama'
        manual = DesignCategoryLink.query.filter_by(design_id=did, source='manual').one()
        assert manual.category_key == 'school-spirit' and manual.locked


def test_a_protected_name_marks_the_design_for_review(app, seed):
    _ready(app)
    did = _design(app)
    with app.app_context():
        design = db.session.get(Design, did)
        status = ai.apply_classification(design, ai.interpret(_raw(visible_text='Chiefs Kingdom', tags=['kc-chiefs'])),
                                         chose_folder=False)
        assert design.ip_status == 'review' and status == 'needs_review'
        design.ip_status = 'cleared'
        ai.apply_classification(design, ai.interpret(_raw(visible_text='Chiefs Kingdom', tags=['kc-chiefs'])), chose_folder=False)
        assert design.ip_status == 'cleared'                                            # once you cleared it, it stays cleared


# -- The upload itself -----------------------------------------------------------

@pytest.fixture()
def uploader(app, admin_client, monkeypatch):
    import routes.admin as admin_routes
    app.config['OPENAI_API_KEY'] = 'test-key'
    state = {'raw': _raw(), 'n': 0}

    def fake_save(file, user_id, **kwargs):
        state['n'] += 1
        design = Design(filename=f'up{state["n"]}.png', original_filename=file.filename,
                        file_path=f'uploads/designs/up{state["n"]}.png', is_gallery=True, uploaded_by_user_id=user_id)
        db.session.add(design)
        db.session.flush()
        return design

    monkeypatch.setattr(admin_routes, '_save_uploaded_design', fake_save)
    monkeypatch.setattr('utils.design_ai.request_classification', lambda *a, **k: state['raw'])
    with app.app_context():
        dt.ensure_vocabulary()

    def post(**data):
        body = {'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 40), data.pop('filename', 'mama.png'))}
        body.update(data)
        return admin_client.post('/admin/design-gallery/upload', data=body, content_type='multipart/form-data',
                                 headers={'X-Requested-With': 'XMLHttpRequest'})
    post.state = state
    yield post
    app.config['OPENAI_API_KEY'] = None


def test_one_upload_names_files_tags_and_publishes_with_no_folder_chosen(uploader, app):
    body = uploader().get_json()
    assert body['ok'] and body['status'] == 'done' and body['held'] is False
    with app.app_context():
        design = db.session.get(Design, body['design_id'])
        assert design.title == 'Vintage Kansas City Football Mama' and design.is_gallery is True
        assert design.folder == 'sports' and design.sku and design.ai_status == 'done'
        assert DesignCategoryLink.query.filter_by(design_id=design.id).count() == 2
        assert 'football-mom' in dt.design_tag_slugs(design)


def test_an_unsure_upload_waits_for_review_instead_of_going_public(uploader, app):
    uploader.state['raw'] = _raw(collections=[{'key': 'sports-game-day', 'sub': 'football', 'confidence': 0.4}], tags=[])
    body = uploader().get_json()
    assert body['ok'] and body['held'] is True and body['status'] == 'needs_review'
    assert 'waiting for your review' in body['message']
    with app.app_context():
        design = db.session.get(Design, body['design_id'])
        assert design.is_gallery is False and design.sku is None


def test_a_folder_you_choose_is_published_as_before_even_when_a_name_is_flagged(uploader, app):
    uploader.state['raw'] = _raw(visible_text='Chiefs Kingdom', tags=['kc-chiefs'], protected=True)
    body = uploader(extra_categories='kc').get_json()
    assert body['ok'] and body['held'] is False
    with app.app_context():
        design = db.session.get(Design, body['design_id'])
        assert design.is_gallery is True and design.folder == 'kc' and design.ip_status == 'review'
        assert design.sku


def test_without_the_ai_key_a_folder_is_still_required(uploader, app):
    app.config['OPENAI_API_KEY'] = ''
    resp = uploader()
    assert resp.status_code == 400 and 'folder' in resp.get_json()['error'].lower()


def test_when_the_ai_is_down_the_name_still_files_it_for_review(uploader, app):
    uploader.state['raw'] = {}                                                          # the call failed
    body = uploader(filename='vintage-football-mama.png').get_json()
    assert body['ok'] and body['held'] is True
    with app.app_context():
        design = db.session.get(Design, body['design_id'])
        assert design.ai_status == 'needs_review' and 'football' in dt.design_tag_slugs(design)


# -- The review page ---------------------------------------------------------------

def test_held_designs_show_up_on_the_review_page_and_in_the_menu_badge(uploader, admin_client):
    uploader.state['raw'] = _raw(collections=[{'key': 'sports-game-day', 'sub': 'football', 'confidence': 0.4}], tags=[])
    uploader()
    html = admin_client.get('/admin/design-library/review').get_data(as_text=True)
    assert 'Design review' in html and 'Hidden from customers' in html and 'Approve and publish' in html
    assert 'Sports &amp; Game Day' in html and '40%' in html
    assert 'ops-drop-badge' in html


def test_approving_publishes_it_remembers_your_changes_and_locks_them(uploader, admin_client, app):
    uploader.state['raw'] = _raw(collections=[], tags=[], title='Football Mama')
    did = uploader().get_json()['design_id']
    resp = admin_client.post('/admin/design-library/review', data={
        'design_id': did, 'action': 'approve', 'title': 'Vintage Football Mama', 'collection': 'sports-game-day',
        'sub': 'football', 'extra': ['family-relationships'], 'tags': 'Football Mom, Vintage, Zzzz Unknown'},
        follow_redirects=True)
    assert resp.status_code == 200 and 'is approved and live' in resp.get_data(as_text=True)
    assert 'Not in the tag list' in resp.get_data(as_text=True)
    with app.app_context():
        design = db.session.get(Design, did)
        assert design.is_gallery is True and design.ai_status == 'done' and design.sku
        assert design.title == 'Vintage Football Mama' and dt.is_locked(design, 'title')
        assert {(l.category_key, l.subcategory_key, l.source) for l in DesignCategoryLink.query.filter_by(design_id=did)} == {
            ('sports-game-day', 'football', 'manual'), ('family-relationships', None, 'manual')}
        assert design.folder == 'sports' and design.extra_categories == 'couples'
        assert {'football-mom', 'football', 'mom', 'vintage'} <= set(dt.design_tag_slugs(design))
        kinds = {c.correction_type for c in DesignCorrection.query.filter_by(design_id=did)}
        assert 'renamed' in kinds and 'categories_changed' in kinds
    again = admin_client.get('/admin/design-library/review').get_data(as_text=True)
    assert 'All caught up' in again


def test_approving_without_a_collection_asks_for_one(uploader, admin_client, app):
    uploader.state['raw'] = _raw(collections=[], tags=[])
    did = uploader().get_json()['design_id']
    resp = admin_client.post('/admin/design-library/review', data={'design_id': did, 'action': 'approve'}, follow_redirects=True)
    assert 'Pick a collection' in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Design, did).is_gallery is False


def test_a_flagged_name_can_be_cleared_and_keep_hidden_leaves_it_hidden(uploader, admin_client, app):
    uploader.state['raw'] = _raw(visible_text='Chiefs Kingdom', tags=['kc-chiefs'], protected=True)
    did = uploader(extra_categories='kc').get_json()['design_id']
    page = admin_client.get('/admin/design-library/review').get_data(as_text=True)
    assert 'protected name' in page and 'chiefs' in page.lower()
    admin_client.post('/admin/design-library/review', data={'design_id': did, 'action': 'save', 'clear_ip': 'on'})
    with app.app_context():
        assert db.session.get(Design, did).ip_status == 'cleared'
    admin_client.post('/admin/design-library/review', data={'design_id': did, 'action': 'keep'})
    with app.app_context():
        assert db.session.get(Design, did).is_gallery is False


def test_only_the_admin_sees_the_review_page(client):
    assert client.get('/admin/design-library/review').status_code in (302, 401, 403)
    assert client.post('/admin/design-library/review', data={'design_id': 1}).status_code in (302, 400, 401, 403)
