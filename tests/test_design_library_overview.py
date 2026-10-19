"""Admin library overview and learning from repeated corrections."""
from models import Design, DesignCategoryLink, DesignCorrection, db
from utils import design_learning as dl
from utils import design_tags as dt


def _d(title, coll=None):
    d = Design(filename=f'{title}.png', file_path=f'uploads/{title}.png', title=title, is_gallery=True, design_fee=0)
    db.session.add(d)
    db.session.flush()
    if coll:
        db.session.add(DesignCategoryLink(design_id=d.id, category_key=coll, is_primary=True))
    return d


def test_one_off_fixes_are_not_lessons_but_repeats_are(app, seed):
    with app.app_context():
        dt.ensure_vocabulary()
        ds = [_d(f'D{i}') for i in range(4)]
        for d in ds[:2]:
            dt.record_correction(d, 'tag', 'vintage', '', 'tag_removed')
        assert dl.lessons() == []
        for d in ds[2:]:
            dt.record_correction(d, 'tag', 'vintage', '', 'tag_removed')
        dt.record_correction(ds[0], 'tag', 'vintage', '', 'tag_removed')   # same design twice counts once
        db.session.commit()
        found = dl.lessons()
        assert len(found) == 1 and found[0]['count'] == 4 and 'Vintage' in found[0]['text']
        assert 'House rules' in dl.prompt_addendum()


def test_repeated_category_moves_become_a_lesson(app, seed):
    with app.app_context():
        for i in range(2):
            dt.record_correction(_d(f'M{i}'), 'categories', 'Football, Moms', 'Moms', 'categories_changed')
        db.session.commit()
        assert any(l['kind'] == 'category' and 'Football' in l['text'] for l in dl.lessons())


def test_no_lessons_means_the_ai_prompt_is_unchanged(app, seed):
    from utils.design_ai import _prompt
    with app.app_context():
        assert 'House rules' not in _prompt()


def test_overview_page_shows_the_numbers(app, seed, admin_client):
    with app.app_context():
        _d('Filed One', 'faith-inspiration')
        _d('Loose One')
        db.session.commit()
    page = admin_client.get('/admin/design-library').get_data(as_text=True)
    assert 'Design Library' in page and 'Not filed yet' in page and 'Faith &amp; Inspiration' in page


def test_overview_page_needs_admin(app, seed, client):
    r = client.get('/admin/design-library')
    assert r.status_code in (302, 401, 403)


def test_the_checklist_walks_through_backup_read_apply_and_compare(app, seed, admin_client):
    from utils import design_organizer as org
    with app.app_context():
        _d('Waiting One')
        db.session.commit()
        steps = {s['n']: s for s in org.checklist()['steps']}
        assert not steps[1]['done'] and not steps[2]['done'] and org.checklist()['any_work']
        assert not org.backup_is_fresh() and org.backup_age_days() is None
    page = admin_client.get('/admin/design-library').get_data(as_text=True)
    assert 'Organize your existing designs' in page and 'Save a backup' in page
    admin_client.get('/admin/design-library/organize/backup.json')
    with app.app_context():
        assert org.backup_is_fresh()
        assert org.checklist()['steps'][0]['done']


def test_a_backup_older_than_a_week_must_be_renewed(app, seed):
    from datetime import datetime, timedelta
    from models import SystemSettings
    from utils import design_organizer as org
    with app.app_context():
        org.mark_backup()
        row = SystemSettings.query.filter_by(key=org.BACKUP_KEY).first()
        row.value = (datetime.utcnow() - timedelta(days=9)).isoformat()
        db.session.commit()
        assert not org.backup_is_fresh()
