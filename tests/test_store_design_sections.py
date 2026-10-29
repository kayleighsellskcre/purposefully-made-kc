"""A group store page: only "Show at top" designs in the strip, the full list as a folded picker with headings,
names exactly as stored, rename and headings from the edit page, and a number in the school page Items column."""
import json
import re

from models import Collection, Design, User, db
from utils import districts as DS
from utils import group_designs as GD


def _store(app, seed, titles):
    with app.app_context():
        d = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Cheer'], {})])
        school = d.schools.first()
        store = next(s for s in DS.stores_of(school, True) if DS.store_label(s) == 'Cheer')
        art = [Design(filename=f'a{i}.png', file_path=f'uploads/designs/a{i}.png', title=t, is_gallery=True,
                      uploaded_by_user_id=seed['admin_id']) for i, t in enumerate(titles)]
        db.session.add_all(art)
        db.session.commit()
        ids = [a.id for a in art]
        store.allowed_design_ids = json.dumps(ids)
        store.showcase_design_ids = json.dumps(ids[:1])
        store.design_sections = json.dumps({str(ids[0]): 'General Spirit', str(ids[1]): 'Family', str(ids[2]): 'Red Friday'})
        db.session.commit()
        return school.id, store.id, store.slug, ids


TITLES = ['MV - Go JAGS', 'Jag Mom Sunglasses', 'Red Friday Leaping Jaguar']


def test_the_strip_has_only_top_designs_and_the_picker_has_everything_under_headings(app, seed, guest):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    html = guest.get(f'/c/{slug}').get_data(as_text=True)
    strip = re.search(r'class="group-order-showcase".*?</div>\s*</div>', html, re.S).group(0)
    assert strip.count('<img') == 1 and 'MV - Go JAGS' in strip
    picker = html[html.index('class="store-picker"'):]
    assert picker.count('store-picker-tile') >= 3
    for heading in ('General Spirit', 'Family', 'Red Friday'):
        assert f'>{heading}</h3>' in picker
    assert html.index('class="store-picker"') > html.index('design-board')           # below the products, not above them


def test_names_show_exactly_as_stored(app, seed, guest):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    html = guest.get(f'/c/{slug}').get_data(as_text=True)
    assert 'MV - Go JAGS' in html and 'Mv - Go Jags' not in html


def test_saving_headings_and_renaming_from_the_edit_form(app, seed):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    with app.app_context():
        store = db.session.get(Collection, store_id)
        admin = db.session.get(User, seed['admin_id'])
        form = {f'design_section_{ids[0]}': ' Family ', f'design_section_{ids[1]}': '', f'design_name_{ids[2]}': 'Red Friday - Jaguar'}
        assert GD.save_design_labels(store, form, admin) == 1
        db.session.commit()
        assert GD.sections_map(store) == {ids[0]: 'Family', ids[2]: 'Red Friday'}
        assert db.session.get(Design, ids[2]).title == 'Red Friday - Jaguar'


def test_only_the_uploader_or_an_admin_can_rename_a_design(app, seed):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    with app.app_context():
        store = db.session.get(Collection, store_id)
        customer = db.session.get(User, seed['customer_id'])
        assert GD.save_design_labels(store, {f'design_name_{ids[0]}': 'Hijacked'}, customer) == 0
        assert db.session.get(Design, ids[0]).title == 'MV - Go JAGS'


def test_the_school_page_items_column_is_a_number(app, seed, admin_client):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    html = admin_client.get(f'/admin/districts/school/{school_id}').get_data(as_text=True)
    assert 'built-in method' not in html and 'bound method' not in html


def test_file_names_keep_capitals_and_dashes():
    from utils.design_metadata import clean_filename_title, title_from_filename
    assert title_from_filename('MV-go JAGS_pennant') == 'MV-go JAGS Pennant'
    assert clean_filename_title('MV-Go-JAGS.png') == 'MV Go JAGS'          # a file name's dashes still separate words


def test_several_designs_can_be_taken_off_or_deleted_at_once(app, seed, admin_client):
    school_id, store_id, slug, ids = _store(app, seed, TITLES + ['Extra One'])
    resp = admin_client.post(f'/admin/collections/{store_id}/designs/bulk', data={'action': 'detach', 'pick': ids[:2]})
    assert resp.status_code == 302 and resp.headers['Location'].endswith(f'/admin/collections/{store_id}/edit')
    with app.app_context():
        assert json.loads(db.session.get(Collection, store_id).allowed_design_ids) == ids[2:]
        assert all(db.session.get(Design, i) is not None for i in ids)                # the artwork stays on file
    admin_client.post(f'/admin/collections/{store_id}/designs/bulk', data={'action': 'delete', 'pick': ids[2:]})
    with app.app_context():
        assert db.session.get(Collection, store_id).allowed_design_ids is None
        assert all(db.session.get(Design, i) is None for i in ids[2:])
        assert db.session.get(Design, ids[0]) is not None


def test_bulk_change_is_for_admins_only(app, seed, guest):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    resp = guest.post(f'/admin/collections/{store_id}/designs/bulk', data={'action': 'delete', 'pick': ids})
    assert resp.status_code == 302 and 'login' in resp.headers['Location']
    with app.app_context():
        assert db.session.get(Design, ids[0]) is not None


def test_bulk_change_needs_a_selection(app, seed, admin_client):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    admin_client.post(f'/admin/collections/{store_id}/designs/bulk', data={'action': 'delete'})
    with app.app_context():
        assert json.loads(db.session.get(Collection, store_id).allowed_design_ids) == ids


def test_the_edit_page_has_select_boxes_and_a_bulk_bar(app, seed, admin_client):
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    html = admin_client.get(f'/admin/collections/{store_id}/edit').get_data(as_text=True)
    assert html.count('js-design-pick') >= 3 and 'designBulkBar' in html and 'Delete selected' in html
