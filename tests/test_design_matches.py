"""Stage 4: spot duplicates, color versions and wording versions - suggestions only, never merged."""
import io
import json

import pytest
from PIL import Image, ImageDraw

from models import Design, DesignRelation, db
from utils import design_fingerprint as fp


# -- Pretend artwork (real images, so the real fingerprint code runs) --------------------

def _art(ink=(0, 0, 0), layout='crest', size=220, transparent=True):
    """A transparent-background design: a block of ink in a layout. Different layouts look different."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    if layout == 'crest':
        d.ellipse((30, 30, 190, 190), fill=ink + (255,))
        d.rectangle((90, 60, 130, 160), fill=(0, 0, 0, 0))
    elif layout == 'banner':
        d.rectangle((10, 70, 210, 150), fill=ink + (255,))
        d.polygon([(10, 70), (40, 110), (10, 150)], fill=(0, 0, 0, 0))
    elif layout == 'banner_wide':          # the same banner with a slightly longer word on it
        d.rectangle((10, 70, 210, 150), fill=ink + (255,))
        d.polygon([(10, 70), (40, 110), (10, 150)], fill=(0, 0, 0, 0))
        d.rectangle((60, 96, 190, 124), fill=(0, 0, 0, 0))
    elif layout == 'stack':
        for y in (20, 80, 140):
            d.rectangle((40, y, 180, y + 40), fill=ink + (255,))
    out = io.BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()


def _design(app, data, title, text=None, **over):
    with app.app_context():
        design = Design(filename=title + '.png', original_filename=title + '.png', file_path='x', title=title,
                        is_gallery=True, art_text=text, **over)
        db.session.add(design)
        db.session.flush()
        assert fp.store_fingerprint(design, data)
        db.session.commit()
        return design.id


def _pair(app, a, b):
    with app.app_context():
        return fp.classify_pair(db.session.get(Design, a), db.session.get(Design, b))


# -- Fingerprints ------------------------------------------------------------------------

def test_the_palette_ignores_the_transparent_background_and_names_color_families(app, seed):
    did = _design(app, _art(ink=(200, 30, 40)), 'Red crest')
    with app.app_context():
        design = db.session.get(Design, did)
        assert design.color_families == 'red'
        palette = json.loads(design.palette)
        assert palette[0]['family'] == 'red' and palette[0]['share'] > 0.9          # not diluted by the empty background
        assert len(design.phash) == 16 and len(design.shape_hash) == 64


def test_black_white_and_gold_are_recognized(app, seed):
    for ink, family in (((10, 10, 10), 'black'), ((250, 250, 250), 'white'), ((212, 175, 55), 'gold'),
                        ((30, 90, 200), 'blue'), ((235, 120, 170), 'pink')):
        did = _design(app, _art(ink=ink), f'ink {family}')
        with app.app_context():
            assert db.session.get(Design, did).color_families == family, family


def test_an_unreadable_file_is_handled(app, seed):
    assert fp.analyze_image(b'not an image') is None


# -- Telling the relationships apart ------------------------------------------------------

def test_the_same_artwork_is_an_exact_duplicate(app, seed):
    a = _design(app, _art(ink=(200, 30, 40)), 'A')
    b = _design(app, _art(ink=(200, 30, 40)), 'B')
    kind, score, reason = _pair(app, a, b)
    assert kind == 'exact_duplicate' and score > 0.9


def test_the_same_layout_in_other_colors_is_a_color_version(app, seed):
    a = _design(app, _art(ink=(200, 30, 40)), 'Crest red', text='Rainbow Cheetahs')
    b = _design(app, _art(ink=(30, 90, 200)), 'Crest blue', text='Rainbow Cheetahs')
    kind, score, reason = _pair(app, a, b)
    assert kind == 'color_variation' and 'red' in reason and 'blue' in reason


def test_the_same_layout_with_different_words_is_a_wording_version(app, seed):
    a = _design(app, _art(ink=(30, 30, 30), layout='banner'), 'Mama', text='Football Mama')
    b = _design(app, _art(ink=(30, 30, 30), layout='banner_wide'), 'Nana', text='Football Nana')
    kind, score, reason = _pair(app, a, b)
    assert kind == 'wording_variation' and 'mama' in reason and 'nana' in reason


def test_different_layouts_are_not_related_even_in_the_same_color(app, seed):
    a = _design(app, _art(ink=(30, 30, 30), layout='crest'), 'Crest')
    b = _design(app, _art(ink=(30, 30, 30), layout='stack'), 'Stack')
    assert _pair(app, a, b) is None


def test_similar_colors_with_totally_different_words_are_not_called_variations(app, seed):
    a = _design(app, _art(ink=(200, 30, 40)), 'One', text='Rainbow Cheetahs')
    b = _design(app, _art(ink=(30, 90, 200)), 'Two', text='Go Falcons Fly High')
    assert _pair(app, a, b) is None                                                  # words differ a lot: a different design


def test_unknown_wording_never_claims_a_color_version_with_full_confidence(app, seed):
    a = _design(app, _art(ink=(200, 30, 40)), 'Crest red')
    b = _design(app, _art(ink=(30, 90, 200)), 'Crest blue')
    kind, score, _ = _pair(app, a, b)
    assert kind == 'color_variation' and score <= 0.7


# -- Suggestions, and the scan --------------------------------------------------------------

def test_suggestions_are_saved_once_per_pair_and_nothing_is_changed(app, seed):
    a = _design(app, _art(ink=(200, 30, 40)), 'Crest red', text='Rainbow Cheetahs')
    b = _design(app, _art(ink=(30, 90, 200)), 'Crest blue', text='Rainbow Cheetahs')
    with app.app_context():
        design_b = db.session.get(Design, b)
        assert fp.suggest_for(design_b) == 1
        db.session.commit()
        assert fp.suggest_for(design_b) == 0                                          # already suggested
        rel = DesignRelation.query.one()
        assert rel.status == 'suggested' and (rel.design_id, rel.related_design_id) == (a, b)
        assert db.session.get(Design, a).is_gallery and db.session.get(Design, b).is_gallery
        assert db.session.get(Design, b).parent_design_id is None


def test_a_dismissed_pair_is_never_suggested_again(app, seed):
    a = _design(app, _art(ink=(200, 30, 40)), 'Crest red', text='X')
    b = _design(app, _art(ink=(30, 90, 200)), 'Crest blue', text='X')
    with app.app_context():
        fp.suggest_for(db.session.get(Design, b))
        rel = DesignRelation.query.one()
        rel.status = 'dismissed'
        db.session.commit()
        assert fp.suggest_for(db.session.get(Design, b)) == 0
        assert DesignRelation.query.count() == 1


def test_designs_already_grouped_as_colors_are_not_suggested_to_each_other(app, seed):
    a = _design(app, _art(ink=(200, 30, 40)), 'Crest red', text='X')
    b = _design(app, _art(ink=(30, 90, 200)), 'Crest blue', text='X')
    with app.app_context():
        db.session.get(Design, b).parent_design_id = a
        db.session.commit()
        assert fp.suggest_for(db.session.get(Design, b)) == 0


def test_scanning_fingerprints_existing_designs_and_finds_matches(app, seed, tmp_path, monkeypatch):
    import utils.design_organizer as org
    data = {1: _art(ink=(200, 30, 40)), 2: _art(ink=(30, 90, 200))}
    with app.app_context():
        for design in Design.query.all():
            design.fingerprinted_at = db.func.now()                                    # leave the shared test catalog out
        ids = []
        for n, title in enumerate(('Old red', 'Old blue'), start=1):
            design = Design(filename=title, file_path='x', title=title, is_gallery=True, art_text='Same words')
            db.session.add(design)
            db.session.flush()
            ids.append((design.id, n))
        db.session.commit()
    by_id = {i: data[n] for i, n in ids}
    monkeypatch.setattr(org, 'load_design_bytes', lambda d, **k: by_id.get(d.id))
    with app.app_context():
        assert fp.counts()['pending_scan'] == 2
        done, found = fp.scan_batch(5)
        assert (done, found) == (2, 1)
        assert fp.counts()['pending_scan'] == 0 and DesignRelation.query.count() == 1


def test_a_missing_file_does_not_stall_the_scan(app, seed, monkeypatch):
    import utils.design_organizer as org
    with app.app_context():
        for design in Design.query.all():
            design.fingerprinted_at = db.func.now()
        design = Design(filename='gone', file_path='gone.png', title='Gone', is_gallery=True)
        db.session.add(design)
        db.session.commit()
    monkeypatch.setattr(org, 'load_design_bytes', lambda d, **k: None)
    with app.app_context():
        assert fp.scan_batch(3)[0] == 1 and fp.counts()['pending_scan'] == 0


# -- The review page and what each button does --------------------------------------------------

def _suggest(app, kind='color'):
    if kind == 'dup':
        a = _design(app, _art(ink=(200, 30, 40)), 'Original', text='X')
        b = _design(app, _art(ink=(200, 30, 40)), 'Copy', text='X')
    elif kind == 'word':
        a = _design(app, _art(ink=(30, 30, 30), layout='banner'), 'Mama', text='Football Mama')
        b = _design(app, _art(ink=(30, 30, 30), layout='banner_wide'), 'Nana', text='Football Nana')
    else:
        a = _design(app, _art(ink=(200, 30, 40)), 'Crest red', text='X')
        b = _design(app, _art(ink=(30, 90, 200)), 'Crest blue', text='X')
    with app.app_context():
        fp.suggest_for(db.session.get(Design, b))
        db.session.commit()
        return a, b, DesignRelation.query.one().id


def test_the_page_shows_each_pair_with_what_to_do(app, seed, admin_client):
    _suggest(app, 'color')
    html = admin_client.get('/admin/design-library/matches').get_data(as_text=True)
    assert 'Duplicates &amp; versions' in html and 'Color versions' in html and 'Crest red' in html and 'Crest blue' in html
    assert 'Group as color options' in html and 'Not related' in html and 'ops-drop-badge' in html


def test_group_as_colors_makes_one_a_color_option_and_can_be_undone(app, seed, admin_client):
    a, b, rid = _suggest(app, 'color')
    resp = admin_client.post('/admin/design-library/matches', data={'relation_id': rid, 'action': 'group_colors'}, follow_redirects=True)
    assert 'color option of' in resp.get_data(as_text=True)
    with app.app_context():
        child = db.session.get(Design, b)
        assert child.parent_design_id == a and child.variant_label and child.title == 'Crest red'
        assert db.session.get(DesignRelation, rid).status == 'confirmed'
    admin_client.post('/admin/design-library/matches', data={'relation_id': rid, 'action': 'undo'})
    with app.app_context():
        assert db.session.get(Design, b).parent_design_id is None
        assert db.session.get(DesignRelation, rid).status == 'suggested'


def test_hiding_the_extra_copy_hides_the_newer_one_and_undo_brings_it_back(app, seed, admin_client):
    a, b, rid = _suggest(app, 'dup')
    admin_client.post('/admin/design-library/matches', data={'relation_id': rid, 'action': 'hide_copy'})
    with app.app_context():
        assert db.session.get(Design, a).is_gallery is True and db.session.get(Design, b).is_gallery is False
        assert db.session.get(Design, b) is not None                                    # nothing is deleted
    admin_client.post('/admin/design-library/matches', data={'relation_id': rid, 'action': 'undo'})
    with app.app_context():
        assert db.session.get(Design, b).is_gallery is True


def test_connect_dismiss_and_matching_set_decisions(app, seed, admin_client):
    a, b, rid = _suggest(app, 'word')
    admin_client.post('/admin/design-library/matches', data={'relation_id': rid, 'action': 'make_set'})
    with app.app_context():
        rel = db.session.get(DesignRelation, rid)
        assert rel.relation_type == 'matching_set' and rel.status == 'confirmed'
    admin_client.post('/admin/design-library/matches', data={'relation_id': rid, 'action': 'dismiss'})
    with app.app_context():
        assert db.session.get(DesignRelation, rid).status == 'dismissed'


def test_related_designs_put_true_versions_first_then_shared_tags(app, seed):
    from utils import design_tags as dt
    a, b, rid = _suggest(app, 'color')
    other = _design(app, _art(ink=(30, 30, 30), layout='stack'), 'Tagged cousin', text='Y')
    with app.app_context():
        dt.ensure_vocabulary()
        rel = db.session.get(DesignRelation, rid)
        rel.status = 'confirmed'
        for did in (a, other):
            dt.apply_auto_tags(db.session.get(Design, did), ['football', 'mom'])
        db.session.commit()
        names = [d.title for d in fp.related_designs(db.session.get(Design, a))]
        assert names[0] == 'Crest blue' and 'Tagged cousin' in names


def test_the_scan_endpoint_and_background_job_work(app, seed, admin_client, monkeypatch):
    import utils.design_organizer as org
    from scheduler import design_fingerprint_job
    with app.app_context():
        for design in Design.query.all():
            design.fingerprinted_at = db.func.now()
        design = Design(filename='n', file_path='x', title='New', is_gallery=True)
        db.session.add(design)
        db.session.commit()
        did = design.id
    monkeypatch.setattr(org, 'load_design_bytes', lambda d, **k: _art())
    body = admin_client.post('/admin/design-library/matches/scan').get_json()
    assert body['processed'] == 1 and body['counts']['pending_scan'] == 0
    with app.app_context():
        design = Design(filename='n2', file_path='x', title='New2', is_gallery=True)
        db.session.add(design)
        db.session.commit()
    design_fingerprint_job(app)
    with app.app_context():
        assert fp.counts()['pending_scan'] == 0


# -- Uploads --------------------------------------------------------------------------------

@pytest.fixture()
def uploader(app, admin_client, monkeypatch):
    import routes.admin as admin_routes
    state = {'n': 0}

    def fake_save(file, user_id, **kwargs):
        state['n'] += 1
        design = Design(filename=f'up{state["n"]}.png', original_filename=file.filename, file_path='uploads/x.png',
                        is_gallery=True, uploaded_by_user_id=user_id)
        db.session.add(design)
        db.session.flush()
        return design

    monkeypatch.setattr(admin_routes, '_save_uploaded_design', fake_save)

    def post(data_bytes, name='a.png', **form):
        body = {'file': (io.BytesIO(data_bytes), name), 'extra_categories': 'sports'}
        body.update(form)
        return admin_client.post('/admin/design-gallery/upload', data=body, content_type='multipart/form-data',
                                 headers={'X-Requested-With': 'XMLHttpRequest'})
    return post


def test_uploading_the_identical_file_twice_does_not_create_a_second_record(app, seed, uploader):
    data = _art(ink=(200, 30, 40))
    first = uploader(data, 'first.png', title='Red Crest').get_json()
    second = uploader(data, 'again.png', title='Red Crest Again').get_json()
    assert first['ok'] and not first.get('duplicate')
    assert second['ok'] and second['duplicate'] is True and second['design_id'] == first['design_id']
    assert 'already in your library' in second['message']
    with app.app_context():
        assert Design.query.filter(Design.file_hash.isnot(None)).count() == 1


def test_a_color_upload_for_a_parent_is_never_blocked_as_a_duplicate(app, seed, uploader):
    data = _art(ink=(200, 30, 40))
    first = uploader(data, 'first.png', title='Red Crest').get_json()
    child = uploader(data, 'variant.png', parent_design_id=str(first['design_id']), variant_label='Same').get_json()
    assert child['ok'] and not child.get('duplicate') and child['design_id'] != first['design_id']


def test_a_new_upload_is_fingerprinted_and_compared_straight_away(app, seed, uploader):
    uploader(_art(ink=(200, 30, 40)), 'red.png', title='Red Crest')
    second = uploader(_art(ink=(30, 90, 200)), 'blue.png', title='Blue Crest').get_json()
    assert second['ok']
    with app.app_context():
        new = db.session.get(Design, second['design_id'])
        assert new.phash and new.color_families == 'blue'
        assert DesignRelation.query.filter_by(status='suggested').count() == 1


def test_only_the_admin_can_use_the_matches_pages(client):
    for method, url in (('get', '/admin/design-library/matches'), ('post', '/admin/design-library/matches'),
                        ('post', '/admin/design-library/matches/scan')):
        assert getattr(client, method)(url).status_code in (302, 400, 401, 403)
