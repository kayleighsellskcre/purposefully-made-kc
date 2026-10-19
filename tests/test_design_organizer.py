"""Stage 3: organize the existing library safely - preview first, only add, always undoable."""
import json

import pytest

from models import Design, DesignCategoryLink, DesignProposal, DesignTagLink, db
from utils import design_ai as ai
from utils import design_organizer as org
from utils import design_tags as dt


def _make(app, title='Football Mama', folder='sports', **over):
    with app.app_context():
        design = Design(filename=f'{title}.png', original_filename=f'{title}.png', file_path='designs/x.png',
                        title=title, is_gallery=True, folder=folder, **over)
        db.session.add(design)
        db.session.commit()
        return design.id


@pytest.fixture()
def lib(app, seed):
    with app.app_context():
        dt.ensure_vocabulary()
        for design in Design.query.all():            # the shared test catalog already has a few designs: leave those out
            design.ai_status = 'done'
        db.session.commit()
    return app


def _raw(**over):
    raw = {'title': 'Vintage Football Mama', 'colors': ['Black'], 'visible_text': 'Football Mama', 'style': 'vintage',
           'audience': 'mom', 'collections': [{'key': 'sports-game-day', 'sub': 'football', 'confidence': 0.9},
                                              {'key': 'family-relationships', 'sub': 'moms', 'confidence': 0.85}],
           'tags': ['football-mom', 'vintage'], 'keywords': ['mama'], 'protected': False}
    raw.update(over)
    return raw


def _ready(app, design_id, raw=None, mode='smart', monkeypatch=None):
    """Queue one design, analyze it with a pretend AI answer, and return its proposal id."""
    with app.app_context():
        batch, count = org.plan_batch(1, mode)
        assert count == 1
        if monkeypatch is not None:
            monkeypatch.setattr(org, 'load_design_bytes', lambda d, **k: b'img')
            monkeypatch.setattr(org, 'request_classification', lambda *a, **k: raw if raw is not None else _raw())
        org.process_queue(5, api_key='k')
        return DesignProposal.query.filter_by(design_id=design_id).one().id


# -- Who gets looked at --------------------------------------------------------------

def test_only_published_main_designs_not_yet_organized_are_eligible(lib):
    main = _make(lib)
    with lib.app_context():
        child = Design(filename='c.png', file_path='c.png', title='Child', is_gallery=True, parent_design_id=main)
        hidden = Design(filename='h.png', file_path='h.png', title='Hidden', is_gallery=False)
        done = Design(filename='d.png', file_path='d.png', title='Done', is_gallery=True, ai_status='done')
        db.session.add_all([child, hidden, done])
        db.session.commit()
        assert [d.id for d in org.eligible_query().all()] == [main]


def test_a_design_is_never_queued_twice(lib):
    _make(lib)
    with lib.app_context():
        assert org.plan_batch(10)[1] == 1
        assert org.plan_batch(10)[1] == 0                                              # already in the pipeline
        assert DesignProposal.query.count() == 1


def test_the_estimate_is_small_and_free_for_name_only(lib):
    assert org.estimate(1000, 'smart')[1] == pytest.approx(0.5)
    assert org.estimate(1000, 'name')[1] == 0.0


# -- Analyzing ------------------------------------------------------------------------

def test_analyzing_saves_a_proposal_and_changes_nothing_on_the_design(lib, monkeypatch):
    did = _make(lib)
    pid = _ready(lib, did, monkeypatch=monkeypatch)
    with lib.app_context():
        row = db.session.get(DesignProposal, pid)
        design = db.session.get(Design, did)
        assert row.status == 'ready' and row.confidence == pytest.approx(0.9) and not row.needs_attention
        assert design.ai_status is None and design.style is None                       # nothing applied yet
        assert DesignCategoryLink.query.filter_by(design_id=did).count() == 0
        assert DesignTagLink.query.filter_by(design_id=did).count() == 0


def test_a_name_only_run_uses_no_ai_and_asks_for_your_okay(lib):
    did = _make(lib, title='Vintage Football Mama', folder=None)
    with lib.app_context():
        org.plan_batch(5, 'name')
        org.process_queue(5, api_key='')
        row = DesignProposal.query.filter_by(design_id=did).one()
        assert row.status == 'ready' and row.needs_attention                            # modest confidence, so you decide
        assert 'football' in json.loads(row.result_json)['tags']


def test_if_the_ai_fails_the_name_is_used_and_nothing_breaks(lib, monkeypatch):
    did = _make(lib, title='Christmas Mama')
    pid = _ready(lib, did, raw={}, monkeypatch=monkeypatch)
    with lib.app_context():
        row = db.session.get(DesignProposal, pid)
        assert row.status == 'ready' and json.loads(row.result_json)['source'] == 'name'


def test_a_stuck_analysis_is_picked_up_again(lib):
    did = _make(lib)
    with lib.app_context():
        org.plan_batch(1, 'name')
        row = DesignProposal.query.filter_by(design_id=did).one()
        row.status = 'processing'
        row.processed_at = org._now() - org.STALE_AFTER * 2
        db.session.commit()
        assert org.process_queue(5, api_key='') == 1


# -- Applying: only adds ----------------------------------------------------------------

def test_applying_adds_to_the_new_library_but_leaves_your_folders_and_name_alone(lib, monkeypatch):
    did = _make(lib, title='Football Mama', folder='sports', extra_categories='couples')
    pid = _ready(lib, did, monkeypatch=monkeypatch)
    with lib.app_context():
        assert org.apply_proposal(db.session.get(DesignProposal, pid), user_id=1)
        db.session.commit()
        design = db.session.get(Design, did)
        assert design.title == 'Football Mama' and design.folder == 'sports' and design.extra_categories == 'couples'
        links = {(l.category_key, l.subcategory_key, l.source) for l in DesignCategoryLink.query.filter_by(design_id=did)}
        assert ('sports-game-day', None, 'legacy') in links and ('family-relationships', None, 'legacy') in links
        assert ('sports-game-day', 'football', 'auto') in links and ('family-relationships', 'moms', 'auto') in links
        assert {'football', 'mom', 'vintage'} <= set(dt.design_tag_slugs(design))
        assert design.style == 'Vintage' and design.ai_status == 'done'


def test_a_generic_name_is_replaced_but_a_name_you_wrote_never_is(lib, monkeypatch):
    generic = _make(lib, title='IMG 4821')
    pid = _ready(lib, generic, monkeypatch=monkeypatch)
    with lib.app_context():
        org.apply_proposal(db.session.get(DesignProposal, pid))
        db.session.commit()
        assert db.session.get(Design, generic).title == 'Vintage Football Mama'
    mine = _make(lib, title='IMG 9999')
    with lib.app_context():
        design = db.session.get(Design, mine)
        dt.record_correction(design, 'title', 'IMG 9999', 'IMG 9999', 'renamed')       # locks the title
        db.session.commit()
    pid2 = _ready(lib, mine, monkeypatch=monkeypatch)
    with lib.app_context():
        org.apply_proposal(db.session.get(DesignProposal, pid2))
        db.session.commit()
        assert db.session.get(Design, mine).title == 'IMG 9999'


def test_unsure_categories_are_not_added_even_when_you_apply(lib, monkeypatch):
    did = _make(lib, folder='evergreen')
    raw = _raw(collections=[{'key': 'sports-game-day', 'sub': 'football', 'confidence': 0.5}], tags=[])
    pid = _ready(lib, did, raw=raw, monkeypatch=monkeypatch)
    with lib.app_context():
        row = db.session.get(DesignProposal, pid)
        assert row.needs_attention
        org.apply_proposal(row)
        db.session.commit()
        assert DesignCategoryLink.query.filter_by(design_id=did, source='auto').count() == 0


def test_a_protected_name_is_noted_but_the_design_stays_live(lib, monkeypatch):
    did = _make(lib, title='Chiefs Kingdom')
    raw = _raw(visible_text='Chiefs Kingdom', tags=['kc-chiefs'], protected=True)
    pid = _ready(lib, did, raw=raw, monkeypatch=monkeypatch)
    with lib.app_context():
        org.apply_proposal(db.session.get(DesignProposal, pid))
        db.session.commit()
        design = db.session.get(Design, did)
        assert design.ip_status == 'noted' and design.is_gallery is True


def test_only_ready_proposals_can_be_applied_and_only_once(lib, monkeypatch):
    did = _make(lib)
    pid = _ready(lib, did, monkeypatch=monkeypatch)
    with lib.app_context():
        row = db.session.get(DesignProposal, pid)
        assert org.apply_proposal(row) is True
        assert org.apply_proposal(row) is False
        db.session.commit()
        assert DesignTagLink.query.filter_by(design_id=did).count() == len(set(dt.design_tag_slugs(db.session.get(Design, did))))


# -- Undo ---------------------------------------------------------------------------------

def test_undo_puts_the_design_back_exactly_as_it_was(lib, monkeypatch):
    did = _make(lib, title='IMG 1', folder='faith', extra_categories='kc', style=None)
    with lib.app_context():
        before = db.session.get(Design, did)
        snapshot = {f: getattr(before, f) for f in ('title', 'folder', 'extra_categories', 'style', 'audience', 'keywords',
                                                    'ai_status', 'ip_status', 'ai_confidence')}
    pid = _ready(lib, did, monkeypatch=monkeypatch)
    with lib.app_context():
        row = db.session.get(DesignProposal, pid)
        org.apply_proposal(row)
        db.session.commit()
        assert DesignCategoryLink.query.filter_by(design_id=did).count() > 0
        assert org.undo_proposal(db.session.get(DesignProposal, pid))
        db.session.commit()
        design = db.session.get(Design, did)
        assert {f: getattr(design, f) for f in snapshot} == snapshot
        assert DesignCategoryLink.query.filter_by(design_id=did).count() == 0
        assert DesignTagLink.query.filter_by(design_id=did).count() == 0
        assert db.session.get(DesignProposal, pid).status == 'undone'


def test_undo_never_removes_a_tag_or_category_you_added_after_applying(lib, monkeypatch):
    did = _make(lib)
    pid = _ready(lib, did, monkeypatch=monkeypatch)
    with lib.app_context():
        org.apply_proposal(db.session.get(DesignProposal, pid))
        db.session.commit()
        design = db.session.get(Design, did)
        dt.set_manual_tags(design, dt.design_tag_slugs(design) + ['christmas'])
        db.session.commit()
        org.undo_proposal(db.session.get(DesignProposal, pid))
        db.session.commit()
        assert dt.design_tag_slugs(db.session.get(Design, did)) == ['christmas'] or 'christmas' in dt.design_tag_slugs(db.session.get(Design, did))


# -- The page and the backup -----------------------------------------------------------------

def test_the_backup_lists_every_design_with_its_folders_tags_and_categories(lib, admin_client):
    did = _make(lib, title='Football Mama', folder='sports')
    with lib.app_context():
        dt.apply_auto_tags(db.session.get(Design, did), ['mom'])
        db.session.commit()
    resp = admin_client.get('/admin/design-library/organize/backup.json')
    assert resp.status_code == 200 and 'attachment' in resp.headers['Content-Disposition']
    rows = {r['id']: r for r in json.loads(resp.get_data(as_text=True))['designs']}
    assert rows[did]['folder'] == 'sports' and ['mom', 'auto'] in rows[did]['tags']


def test_the_organize_page_walks_through_look_preview_apply_and_undo(lib, admin_client, monkeypatch):
    did = _make(lib, title='Football Mama', folder='sports')
    monkeypatch.setattr(org, 'load_design_bytes', lambda d, **k: b'img')
    monkeypatch.setattr(org, 'request_classification', lambda *a, **k: _raw())
    lib.config['OPENAI_API_KEY'] = 'k'
    try:
        page = admin_client.get('/admin/design-library/organize').get_data(as_text=True)
        assert 'Organize your library' in page and 'Download a backup copy' in page and 'Look at this batch' in page
        resp = admin_client.post('/admin/design-library/organize', data={'action': 'analyze', 'size': '10', 'mode': 'smart'},
                                 follow_redirects=True)
        assert 'Looking at 1 design' in resp.get_data(as_text=True)
        page = admin_client.get('/admin/design-library/organize').get_data(as_text=True)
        assert 'Confident (1)' in page and 'Football Mama' in page and 'Today:' in page and 'sports' in page
        assert 'Vintage' in page and 'Apply all 1 confident' in page
        resp = admin_client.post('/admin/design-library/organize', data={'action': 'apply_confident'}, follow_redirects=True)
        assert 'Applied to 1 design' in resp.get_data(as_text=True) and 'A backup was saved first' in resp.get_data(as_text=True)
        assert org.last_auto_backup() is not None
        assert 'Recently organized' in resp.get_data(as_text=True)
        with lib.app_context():
            pid = DesignProposal.query.filter_by(design_id=did).one().id
        resp = admin_client.post('/admin/design-library/organize', data={'action': 'undo', 'proposal_id': pid}, follow_redirects=True)
        assert 'back exactly as it was' in resp.get_data(as_text=True)
        with lib.app_context():
            assert db.session.get(Design, did).ai_status is None
    finally:
        lib.config['OPENAI_API_KEY'] = None


def test_apply_confident_skips_the_ones_that_need_your_okay(lib, admin_client, monkeypatch):
    sure = _make(lib, title='Sure')
    pid = _ready(lib, sure, monkeypatch=monkeypatch)
    unsure = _make(lib, title='Unsure', folder=None)
    _ready(lib, unsure, raw=_raw(collections=[{'key': 'sports-game-day', 'sub': None, 'confidence': 0.4}]), monkeypatch=monkeypatch)
    admin_client.post('/admin/design-library/organize', data={'action': 'apply_confident'})
    with lib.app_context():
        assert DesignProposal.query.filter_by(design_id=sure).one().status == 'applied'
        assert DesignProposal.query.filter_by(design_id=unsure).one().status == 'ready'


def test_skipped_designs_are_not_suggested_again(lib, admin_client, monkeypatch):
    did = _make(lib)
    pid = _ready(lib, did, monkeypatch=monkeypatch)
    admin_client.post('/admin/design-library/organize', data={'action': 'skip', 'ids': pid})
    with lib.app_context():
        assert DesignProposal.query.get(pid).status == 'skipped'
        assert org.plan_batch(10)[1] == 0


def test_the_progress_endpoint_does_a_little_work_and_reports(lib, admin_client):
    _make(lib, title='Vintage Football Mama')
    with lib.app_context():
        org.plan_batch(5, 'name')
    body = admin_client.post('/admin/design-library/organize/process').get_json()
    assert body['processed'] == 1 and body['summary']['queued'] == 0 and body['summary']['ready'] == 1


def test_the_background_job_works_through_the_queue(lib):
    from scheduler import design_organize_job
    _make(lib, title='Vintage Football Mama')
    with lib.app_context():
        org.plan_batch(5, 'name')
    design_organize_job(lib)
    with lib.app_context():
        assert DesignProposal.query.filter_by(status='ready').count() == 1


def test_only_the_admin_can_use_the_organizer(client):
    for method, url in (('get', '/admin/design-library/organize'), ('post', '/admin/design-library/organize'),
                        ('post', '/admin/design-library/organize/process'),
                        ('get', '/admin/design-library/organize/backup.json')):
        assert getattr(client, method)(url).status_code in (302, 400, 401, 403)


def test_an_undone_design_is_not_suggested_again_either(lib, monkeypatch):
    did = _make(lib)
    pid = _ready(lib, did, monkeypatch=monkeypatch)
    with lib.app_context():
        org.apply_proposal(db.session.get(DesignProposal, pid))
        db.session.commit()
        org.undo_proposal(db.session.get(DesignProposal, pid))
        db.session.commit()
        assert org.plan_batch(10)[1] == 0


def test_designs_already_in_a_folder_you_chose_do_not_wait_for_your_okay_and_apply_with_nothing_blocking(lib, admin_client, monkeypatch):
    did = _make(lib, title='Make Heaven Crowded', folder='faith')
    with lib.app_context():
        org.plan_batch(5, 'name')
        org.process_queue(5, api_key='')
        row = DesignProposal.query.filter_by(design_id=did).one()
        assert row.status == 'ready' and row.needs_attention is False       # the folder is carried over safely
    page = admin_client.get('/admin/design-library/organize').get_data(as_text=True)
    assert 'Faith &amp; Inspiration' in page and 'your current folder' in page
    resp = admin_client.post('/admin/design-library/organize', data={'action': 'apply', 'ids': [row.id]}, follow_redirects=True)
    assert 'Applied to 1 design' in resp.get_data(as_text=True)
    with lib.app_context():
        link = DesignCategoryLink.query.filter_by(design_id=did).one()
        assert (link.category_key, link.source) == ('faith-inspiration', 'legacy')


def test_applying_with_nothing_ticked_says_so(lib, admin_client):
    resp = admin_client.post('/admin/design-library/organize', data={'action': 'apply'}, follow_redirects=True)
    assert 'Tick the designs you want to apply first' in resp.get_data(as_text=True)
