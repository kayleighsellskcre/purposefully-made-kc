"""Stage 7: one small library, start to finish, with real images.

Upload -> named, filed, tagged -> duplicates / colorways / wording versions noticed -> customers find it ->
the owner corrects things -> a re-read never overwrites the corrections.
"""
import io

import pytest
from PIL import Image, ImageDraw

from models import Design, DesignCategoryLink, DesignRelation, db
from utils import design_tags as dt


def _art(ink, layout='crest', transparent=True):
    img = Image.new('RGBA', (220, 220), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    if layout == 'crest':
        d.ellipse((30, 30, 190, 190), fill=ink + (255,))
        d.rectangle((90, 60, 130, 160), fill=(0, 0, 0, 0))
    elif layout == 'banner':
        d.rectangle((10, 70, 210, 150), fill=ink + (255,))
        d.polygon([(10, 70), (40, 110), (10, 150)], fill=(0, 0, 0, 0))
    elif layout == 'banner_wide':
        d.rectangle((10, 70, 210, 150), fill=ink + (255,))
        d.polygon([(10, 70), (40, 110), (10, 150)], fill=(0, 0, 0, 0))
        d.rectangle((60, 96, 190, 124), fill=(0, 0, 0, 0))
    elif layout == 'stack':
        for y in (20, 80, 140):
            d.rectangle((40, y, 180, y + 40), fill=ink + (255,))
    out = io.BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()


def _raw(title, text, collections, tags, **over):
    raw = {'title': title, 'colors': [], 'visible_text': text, 'style': 'bold', 'audience': '',
           'collections': collections, 'tags': tags, 'keywords': [], 'protected': False}
    raw.update(over)
    return raw


@pytest.fixture()
def lib(app, admin_client, client, monkeypatch):
    import routes.admin as admin_routes
    app.config['OPENAI_API_KEY'] = 'test-key'
    state = {'raw': {}, 'n': 0}

    def fake_save(file, user_id, **kwargs):
        state['n'] += 1
        design = Design(filename=f'j{state["n"]}.png', original_filename=file.filename,
                        file_path=f'uploads/designs/j{state["n"]}.png', is_gallery=True, uploaded_by_user_id=user_id)
        db.session.add(design)
        db.session.flush()
        return design

    monkeypatch.setattr(admin_routes, '_save_uploaded_design', fake_save)
    monkeypatch.setattr('utils.design_ai.request_classification', lambda *a, **k: state['raw'])
    with app.app_context():
        dt.ensure_vocabulary()

    class Lib:
        admin, public = admin_client, client

        def upload(self, data, name, raw=None, **form):
            state['raw'] = raw or {}
            body = {'file': (io.BytesIO(data), name)}
            body.update(form)
            return admin_client.post('/admin/design-gallery/upload', data=body, content_type='multipart/form-data',
                                     headers={'X-Requested-With': 'XMLHttpRequest'}).get_json()
    yield Lib()
    app.config['OPENAI_API_KEY'] = None


CHIEFS = [{'key': 'sports-game-day', 'sub': 'football', 'confidence': 0.95},
          {'key': 'kansas-city', 'sub': 'other-kc-teams', 'confidence': 0.9}]
MOMS = [{'key': 'family-relationships', 'sub': 'moms', 'confidence': 0.92}]


def test_a_small_library_works_end_to_end(app, lib):
    # 1. a design that belongs in two places, on a transparent background
    red = lib.upload(_art((200, 30, 40)), 'chiefs.png',
                     _raw('Kansas City Crest', 'Kansas City Football', CHIEFS, ['kansas-city', 'football']))
    assert red['ok'] and not red['held']
    # 2. the same artwork in another colorway
    blue = lib.upload(_art((30, 90, 200)), 'chiefs-blue.png',
                      _raw('Kansas City Crest Blue', 'Kansas City Football', CHIEFS, ['kansas-city', 'football']))
    # 3. a banner and the same banner with different words
    mama = lib.upload(_art((20, 20, 20), 'banner'), 'mama.png', _raw('Mama Banner', 'Football Mama', MOMS, ['mom']))
    mimi = lib.upload(_art((20, 20, 20), 'banner_wide'), 'mimi.png',
                      _raw('Mimi Banner', 'Football Mimi', [{'key': 'family-relationships', 'sub': 'grandparents', 'confidence': 0.9}], ['mimi']))
    # 4. the exact same file again is not stored twice
    again = lib.upload(_art((200, 30, 40)), 'chiefs-copy.png', _raw('Copy', 'x', CHIEFS, []))
    assert again['duplicate'] is True and again['design_id'] == red['design_id']
    # 5. the AI is unsure: held back, not public
    unsure = lib.upload(_art((90, 60, 20), 'stack'), 'mystery.png',
                        _raw('Mystery Stack', '', [{'key': 'funny-sarcastic', 'sub': None, 'confidence': 0.3}], []))
    assert unsure['held'] is True

    with app.app_context():
        assert Design.query.count() >= 5
        kinds = {(r.relation_type) for r in DesignRelation.query.filter_by(status='suggested')}
        assert 'color_variation' in kinds and 'wording_variation' in kinds
        assert not Design.query.get(unsure['design_id']).is_gallery
        chiefs = Design.query.get(red['design_id'])
        assert {l.category_key for l in DesignCategoryLink.query.filter_by(design_id=chiefs.id)} == {'sports-game-day', 'kansas-city'}
        assert chiefs.color_families == 'red'                                    # transparent background ignored

    # customers: both collections show it, search by a synonym finds it, the held one is invisible
    sports = lib.public.get('/shop/designs?collection=sports-game-day').get_data(as_text=True)
    kc = lib.public.get('/shop/designs?collection=kansas-city&sub=other-kc-teams').get_data(as_text=True)
    assert 'Kansas City Crest' in sports and 'Kansas City Crest' in kc
    assert 'Mystery Stack' not in lib.public.get('/shop/designs?q=mystery').get_data(as_text=True)
    assert 'Mama Banner' in lib.public.get('/shop/designs?q=mommy').get_data(as_text=True)

    # the owner corrects the name and a tag
    resp = lib.admin.post('/admin/design-library/review', data={
        'design_id': mama['design_id'], 'action': 'save', 'title': 'Mama Ribbon (mine)',
        'collection': 'family-relationships', 'sub': 'moms', 'tags': 'Mom'}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert Design.query.get(mama['design_id']).title == 'Mama Ribbon (mine)'

    # a later re-read with different answers never overwrites it
    from utils import design_ai as ai
    with app.app_context():
        design = Design.query.get(mama['design_id'])
        ai.apply_classification(design, ai.interpret(_raw('Totally Different', 'Football Mama', [
            {'key': 'funny-sarcastic', 'sub': None, 'confidence': 0.99}], ['football'])), chose_folder=False)
        db.session.commit()
        design = Design.query.get(mama['design_id'])
        assert design.title == 'Mama Ribbon (mine)'
        places = {(l.category_key, l.subcategory_key) for l in DesignCategoryLink.query.filter_by(design_id=design.id)}
        assert ('family-relationships', 'moms') in places
