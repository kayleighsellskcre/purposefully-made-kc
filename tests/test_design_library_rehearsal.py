"""Stage 8 rehearsal: organize a realistic existing library and prove nothing you have is lost.

Forty old-style designs (folders, SKUs, hand-made names, color families, hidden ones) go through the real
organizer: read -> preview -> backup -> apply -> compare for duplicates -> customers see them -> undo the batch.
"""
import io

import pytest
from PIL import Image, ImageDraw

from models import Design, DesignCategoryLink, DesignProposal, DesignRelation, DesignTagLink, db
from utils import design_ai as ai
from utils import design_fingerprint as fp
from utils import design_organizer as org
from utils import design_tags as dt

FOLDERS = ['sports', 'faith', 'school', 'kc', 'holiday', 'funny', 'family', 'luxury_basics', 'music', 'evergreen']


def _png(i):
    img = Image.new('RGBA', (160, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((10 + (i * 3) % 60, 10 + (i * 7) % 60, 100 + (i * 5) % 50, 100 + (i * 11) % 50), fill=(30 + i * 4 % 200, 40, 90, 255))
    out = io.BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()


@pytest.fixture()
def library(app, seed):
    with app.app_context():
        dt.ensure_vocabulary()
        for d in Design.query.all():
            d.ai_status = 'done'
            d.is_gallery = False
        db.session.commit()
        ids = []
        for i in range(40):
            d = Design(filename=f'old{i}.png', original_filename=f'old{i}.png', file_path=f'uploads/designs/old{i}.png',
                       title=f'Hand Named {i}', sku=f'PMKC-{1000 + i}', folder=FOLDERS[i % len(FOLDERS)],
                       extra_categories='kc' if i % 7 == 0 else None, is_gallery=True)
            db.session.add(d)
            db.session.flush()
            ids.append(d.id)
        for i in (3, 9):                                             # two color children
            db.session.add(Design(filename=f'c{i}.png', file_path=f'uploads/designs/c{i}.png', title=f'Hand Named {i}',
                                  is_gallery=True, parent_design_id=ids[i], variant_label='Navy'))
        db.session.add(Design(filename='hid.png', file_path='uploads/designs/hid.png', title='Not Live', is_gallery=False))
        db.session.commit()
    return ids


def _snapshot(app):
    with app.app_context():
        return {d.id: (d.title, d.sku, d.file_path, d.folder, d.extra_categories, d.parent_design_id, d.variant_label, d.is_gallery)
                for d in Design.query.all()}


def _fake_ai(monkeypatch):
    def raw(*a, **k):
        return {'title': 'Machine Name', 'colors': ['Black'], 'visible_text': 'Mama', 'style': 'bold', 'audience': 'mom',
                'collections': [{'key': 'family-relationships', 'sub': 'moms', 'confidence': 0.9}],
                'tags': ['mom'], 'keywords': [], 'protected': False}
    monkeypatch.setattr(org, 'load_design_bytes', lambda d, **k: b'img')
    monkeypatch.setattr(org, 'request_classification', raw)


def test_organizing_the_whole_library_changes_nothing_you_already_have(app, library, monkeypatch):
    _fake_ai(monkeypatch)
    before = _snapshot(app)
    with app.app_context():
        batch, count = org.plan_batch(200, 'smart')
        assert count == 40                                                # mains only: not the children, not the hidden one
        while org.process_queue(10, api_key='k'):
            pass
        assert org.summary()['ready'] == 40 and org.summary()['errors'] == 0
    assert _snapshot(app) == before                                      # the preview changed nothing at all

    with app.app_context():
        for row in DesignProposal.query.filter_by(status='ready').all():
            assert org.apply_proposal(row, user_id=1)
        db.session.commit()
    after = _snapshot(app)
    assert set(after) == set(before)                                     # nothing removed
    for did, old in before.items():
        new = after[did]
        assert (new[0], new[1], new[2], new[5], new[6], new[7]) == (old[0], old[1], old[2], old[5], old[6], old[7])  # name, SKU, file, family, live
        assert new[3] == old[3]                                          # the folder you chose stays the folder

    with app.app_context():
        assert DesignCategoryLink.query.count() >= 40                    # every design now has a place in the new library
        assert DesignTagLink.query.count() >= 40
        # the gallery customers use still lists every live design
        from utils.design_variants import gallery_cards_for_public
        cards = gallery_cards_for_public(Design)
        assert len(cards) == 40


def test_the_whole_batch_can_be_undone_exactly(app, library, monkeypatch):
    _fake_ai(monkeypatch)
    before = _snapshot(app)
    with app.app_context():
        batch, _count = org.plan_batch(200, 'smart')
        while org.process_queue(10, api_key='k'):
            pass
        for row in DesignProposal.query.filter_by(status='ready').all():
            org.apply_proposal(row, user_id=1)
        db.session.commit()
        rows = DesignProposal.query.filter_by(batch_id=batch, status='applied').all()
        assert len(rows) == 40 and all(org.undo_proposal(r) for r in rows)
        db.session.commit()
        assert DesignCategoryLink.query.count() == 0 and DesignTagLink.query.count() == 0
    assert _snapshot(app) == before


def test_a_crash_halfway_leaves_a_clean_restartable_state(app, library, monkeypatch):
    _fake_ai(monkeypatch)
    calls = {'n': 0}
    real = org._analyze

    def flaky(design, mode, key):
        calls['n'] += 1
        if calls['n'] == 5:
            raise RuntimeError('network blip')
        return real(design, mode, key)
    monkeypatch.setattr(org, '_analyze', flaky)
    with app.app_context():
        org.plan_batch(10, 'smart')
        while org.process_queue(3, api_key='k'):
            pass
        s = org.summary()
        assert s['errors'] == 1 and s['ready'] == 9                      # one bad one never stalls the rest
        assert org.plan_batch(10, 'smart')[1] == 10                      # the next batch picks up different designs


def test_duplicates_in_an_existing_library_are_found_without_touching_anything(app, library, monkeypatch, tmp_path):
    before = _snapshot(app)
    data = {}
    with app.app_context():
        for did in library[:6]:
            d = db.session.get(Design, did)
            data[did] = _png(0 if did in library[:2] else did)           # first two are the same artwork
            fp.store_fingerprint(d, data[did])
        db.session.commit()
        fp.suggest_for(db.session.get(Design, library[1]))
        db.session.commit()
        kinds = {r.relation_type for r in DesignRelation.query.all()}
        assert 'exact_duplicate' in kinds
        assert all(r.status == 'suggested' for r in DesignRelation.query.all())
    assert _snapshot(app) == before                                      # suggestions only


def test_the_safety_guards_hold_for_a_big_run(app, library, admin_client, monkeypatch):
    _fake_ai(monkeypatch)
    app.config['OPENAI_API_KEY'] = 'k'
    try:
        admin_client.post('/admin/design-library/organize', data={'action': 'analyze', 'size': '200', 'mode': 'smart'})
        with app.app_context():
            while org.process_queue(10, api_key='k'):
                pass
        denied = admin_client.post('/admin/design-library/organize', data={'action': 'apply_confident'}, follow_redirects=True)
        assert 'download the backup first' in denied.get_data(as_text=True)
        with app.app_context():
            assert DesignCategoryLink.query.count() == 0
        backup = admin_client.get('/admin/design-library/organize/backup.json')
        assert backup.status_code == 200 and len(backup.get_json()['designs']) == 42      # every live design incl. colorways
        admin_client.post('/admin/design-library/organize', data={'action': 'apply_confident'})
        with app.app_context():
            assert DesignCategoryLink.query.count() >= 40
    finally:
        app.config['OPENAI_API_KEY'] = None
