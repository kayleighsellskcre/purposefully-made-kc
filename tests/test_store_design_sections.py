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


def test_bulk_buttons_do_not_depend_on_their_own_value(app, seed, admin_client):
    """The site greys a clicked button before the form is read, which drops the button's own name and value, so the
    chosen action has to travel in a hidden field that the click fills in."""
    school_id, store_id, slug, ids = _store(app, seed, TITLES)
    html = admin_client.get(f'/admin/collections/{store_id}/edit').get_data(as_text=True)
    assert 'id="bulkAction"' in html and 'data-action="delete"' in html and 'data-action="detach"' in html
    assert 'name="action" value="delete"' not in html


def _png(color):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new('RGBA', (20, 20), color).save(buf, 'PNG')
    return buf.getvalue()


def _post_item(client, store_id, entry, data, dry=False):
    import hashlib
    from io import BytesIO
    form = {'design_id': entry['design_id'], 'name': entry['name'], 'category': entry['category'],
            'sha256': entry.get('sha256') or hashlib.sha256(data).hexdigest(), 'file': (BytesIO(data), 'x.png')}
    if dry:
        form['dry_run'] = '1'
    return client.post(f'/admin/collections/{store_id}/artwork-pack/item', data=form, content_type='multipart/form-data').get_json()


def test_artwork_pack_adds_matches_and_sorts_into_headings(app, seed, admin_client):
    school_id, store_id, slug, ids = _store(app, seed, ['Go jags pennant', 'B', 'C'])
    png = _png((200, 30, 30, 120))
    # an existing design with the same name is matched, not duplicated
    assert _post_item(admin_client, store_id, {'design_id': 'MV-29', 'name': 'Go jags pennant', 'category': 'general-spirit'}, png)['status'] == 'matched'
    # checking does not save anything
    assert _post_item(admin_client, store_id, {'design_id': 'MV-44', 'name': 'Jag dad sunglasses', 'category': 'family-fanwear'}, png, dry=True)['status'] == 'added'
    with app.app_context():
        assert len(json.loads(db.session.get(Collection, store_id).allowed_design_ids)) == 3
    assert _post_item(admin_client, store_id, {'design_id': 'MV-44', 'name': 'Jag dad sunglasses', 'category': 'family-fanwear'}, png)['status'] == 'added'
    assert _post_item(admin_client, store_id, {'design_id': 'MV-44', 'name': 'Jag dad sunglasses', 'category': 'family-fanwear'}, png)['status'] == 'matched'
    with app.app_context():
        store = db.session.get(Collection, store_id)
        assert len(json.loads(store.allowed_design_ids)) == 4
        new = Design.query.filter_by(sku='MV-44').one()
        assert new.title == 'Jag Dad Sunglasses' and GD.sections_map(store)[new.id] == 'Family'


def test_artwork_pack_refuses_a_damaged_or_wrong_file(app, seed, admin_client):
    school_id, store_id, slug, ids = _store(app, seed, ['Something else', 'B', 'C'])
    entry = {'design_id': 'MV-01', 'name': 'Calm jaguar', 'category': 'general-spirit'}
    assert _post_item(admin_client, store_id, dict(entry, sha256='0' * 64), _png((1, 2, 3, 255)))['status'] == 'problem'
    assert _post_item(admin_client, store_id, entry, b'not a picture')['status'] == 'problem'
    assert _post_item(admin_client, store_id, dict(entry, category='cheer'), _png((1, 2, 3, 255)))['status'] == 'problem'


def test_artwork_pack_page_is_linked_and_admin_only(app, seed, admin_client):
    school_id, store_id, slug, ids = _store(app, seed, ['One', 'B', 'C'])
    html = admin_client.get(f'/admin/collections/{store_id}/edit').get_data(as_text=True)
    assert f'/admin/collections/{store_id}/artwork-pack' in html
    assert b'design-manifest.json' in admin_client.get(f'/admin/collections/{store_id}/artwork-pack').data
