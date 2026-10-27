"""Artwork belongs to one group unless the owner puts it in another, and moving it around is easy."""
import json

from models import Collection, Design, Organization, db
from utils import districts as DS
from utils import group_designs as GD
from utils.group_orders import allowed_design_ids


def _school(app, seed):
    with app.app_context():
        d = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Cheer', 'Volleyball', 'Band'], {})])
        school = d.schools.first()
        stores = {DS.store_label(s): s.id for s in DS.stores_of(school, True)}
        art = [Design(filename=f'art{i}.png', file_path=f'uploads/designs/art{i}.png', title=f'Art {i}', is_gallery=True,
                      uploaded_by_user_id=seed['admin_id']) for i in range(3)]
        db.session.add_all(art)
        db.session.commit()
        return school.id, stores, [a.id for a in art]


def _ids(app, store_id):
    with app.app_context():
        return allowed_design_ids(db.session.get(Collection, store_id))


def test_artwork_added_to_one_store_does_not_appear_in_the_others(app, seed):
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        GD.attach(db.session.get(Collection, stores['Cheer']), art[:2], show_at_top=True)
        db.session.commit()
    assert set(art[:2]) <= set(_ids(app, stores['Cheer']))
    for other in ('Volleyball', 'Band', 'Spirit'):
        if other in stores:
            assert not set(art) & set(_ids(app, stores[other]))


def test_a_main_logo_can_be_kept_in_just_one_store(app, seed, admin_client):
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        DS.set_school_logos(db.session.get(Organization, school_id), [art[0]])
        db.session.commit()
    assert all(art[0] in _ids(app, sid) for sid in stores.values())          # a main logo goes to every store, on purpose
    resp = admin_client.post(f'/admin/districts/school/{school_id}', data={
        'action': 'logo_to_store', 'design_id': art[0], 'store_id': stores['Cheer']}, follow_redirects=True)
    assert resp.status_code == 200 and b'belongs to Mill Valley Cheer only' in resp.data
    assert art[0] in _ids(app, stores['Cheer'])
    assert not any(art[0] in _ids(app, sid) for name, sid in stores.items() if name != 'Cheer')
    with app.app_context():
        assert DS.school_logos(db.session.get(Organization, school_id)) == []


def test_taking_a_design_off_one_group_keeps_the_artwork_and_the_other_groups(app, seed, admin_client):
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        for name in ('Cheer', 'Band'):
            GD.attach(db.session.get(Collection, stores[name]), [art[0]], show_at_top=True)
        db.session.commit()
    admin_client.post(f"/admin/collections/{stores['Cheer']}/designs/{art[0]}/detach")
    assert art[0] not in _ids(app, stores['Cheer']) and art[0] in _ids(app, stores['Band'])
    with app.app_context():
        assert db.session.get(Design, art[0]) is not None
        assert art[0] not in json.loads(db.session.get(Collection, stores['Cheer']).showcase_design_ids or '[]')


def test_a_design_can_be_copied_to_another_group_from_the_edit_page(app, seed, admin_client):
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        GD.attach(db.session.get(Collection, stores['Cheer']), art[:2])
        db.session.commit()
    admin_client.post(f"/admin/collections/{stores['Cheer']}/designs/{art[0]}/copy-to", data={'target_id': stores['Band']})
    assert art[0] in _ids(app, stores['Band']) and art[0] in _ids(app, stores['Cheer'])
    html = admin_client.get(f"/admin/collections/{stores['Cheer']}/edit").get_data(as_text=True)
    assert 'Also use in...' in html and f'id="copyDesign{art[0]}"' in html and f'id="detachDesign{art[0]}"' in html


def test_the_edit_page_offers_artwork_from_sibling_groups(app, seed, admin_client):
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        GD.attach(db.session.get(Collection, stores['Volleyball']), [art[2]])
        db.session.commit()
    html = admin_client.get(f"/admin/collections/{stores['Band']}/edit").get_data(as_text=True)
    assert 'Use artwork from another group' in html and f'value="{art[2]}" form="attachDesigns"' in html
    admin_client.post(f"/admin/collections/{stores['Band']}/designs/attach", data={'design_ids': [art[2]]})
    assert art[2] in _ids(app, stores['Band']) and art[2] in _ids(app, stores['Volleyball'])


def test_a_stores_artwork_never_shows_up_in_another_stores_customizer(app, seed, guest):
    """The bug: every store of a school pooled the artwork of all its sibling stores in the style picker."""
    import json as _json

    from models import Product
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Cheer', 'Volleyball'], {})])
        school = d.schools.first()
        stores = {DS.store_label(s): s for s in DS.stores_of(school, True)}
        for s in stores.values():
            s.products.append(tee)
        cheer = Design(filename='CHEERLOGO.png', file_path='uploads/designs/CHEERLOGO.png', title='Cheer Logo', is_gallery=False,
                       uploaded_by_user_id=seed['admin_id'])
        db.session.add(cheer)
        db.session.flush()
        stores['Cheer'].allowed_design_ids = _json.dumps([cheer.id])
        stores['Cheer'].showcase_design_ids = _json.dumps([cheer.id])
        db.session.commit()
        slugs = {name: s.slug for name, s in stores.items()}
        tee_slug, cheer_id = tee.slug, cheer.id
    for name, slug in slugs.items():
        guest.get(f'/c/{slug}')
        html = guest.get(f'/shop/customize/{tee_slug}').get_data(as_text=True)
        assert ('CHEERLOGO' in html) == (name == 'Cheer'), name
    from utils.group_orders import design_allowed_for_collection
    with app.app_context():
        assert design_allowed_for_collection(db.session.get(Design, cheer_id), db.session.get(Collection, stores_id(app, slugs['Cheer'])))
        assert not design_allowed_for_collection(db.session.get(Design, cheer_id), db.session.get(Collection, stores_id(app, slugs['Volleyball'])))


def stores_id(app, slug):
    return Collection.query.filter_by(slug=slug).first().id


def test_the_logo_strip_shows_every_main_design_with_the_ticked_ones_first(app, seed):
    from utils.group_orders import load_showcase_designs
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        store = db.session.get(Collection, stores['Cheer'])
        GD.attach(store, art)
        db.session.get(Design, art[1]).parent_design_id = art[0]            # a color version of the first design
        store.showcase_design_ids = json.dumps([art[2]])                    # only the third is ticked "Show at top"
        db.session.commit()
        shown = [d['id'] for d in load_showcase_designs(store)]
        assert shown == [art[2], art[0]]                                    # ticked first, then the other main design, no color version
        store.showcase_design_ids = None
        db.session.commit()
        assert [d['id'] for d in load_showcase_designs(store)] == [art[0], art[2]]


def test_files_uploaded_together_can_be_linked_as_colors_on_the_spot(app, seed):
    from werkzeug.datastructures import MultiDict
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        shown = GD.link_uploaded_colors([], MultiDict([('new_uploaded_designs', str(i)) for i in art[:2]] + [('link_new_uploads', 'on')]))
        assert shown == [art[0]]                                           # only the main image is also shown at the top
        first, second, third = (db.session.get(Design, i) for i in art)
        assert second.parent_design_id == first.id and first.parent_design_id is None and third.parent_design_id is None
        assert second.variant_label and first.variant_label
        # without the tick nothing is linked
        assert GD.link_uploaded_colors([], MultiDict([('new_uploaded_designs', str(art[2]))])) == [art[2]]


def test_linking_colors_keeps_the_show_at_top_tick_on_the_main_design(app, seed, admin_client):
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        store = db.session.get(Collection, stores['Cheer'])
        GD.attach(store, art[:2])
        store.showcase_design_ids = json.dumps([art[1]])                   # ticked on the color that is about to be linked
        db.session.commit()
        store_id = store.id
    resp = admin_client.post(f'/admin/collections/{store_id}/designs/link-colors', data={'design_ids': [art[0], art[1]]}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        store = db.session.get(Collection, store_id)
        assert json.loads(store.showcase_design_ids) == [art[0]]
        assert db.session.get(Design, art[1]).parent_design_id == art[0]


def test_a_group_can_have_several_back_images_with_colors_tied_to_a_main_one(app, seed, admin_client):
    from utils import group_designs as GD2
    school_id, stores, art = _school(app, seed)
    with app.app_context():
        store = db.session.get(Collection, stores['Cheer'])
        store_id = store.id
        GD2.set_back_ids(store, [art[0], art[1], art[2]])
        db.session.commit()
        assert GD2.back_ids(store) == art and store.back_design_id == art[0]
        assert not set(art) & set(allowed_design_ids(store))                    # never offered as a front choice
    resp = admin_client.post(f'/admin/collections/{store_id}/back-designs/link', data={'back_pick': [art[0], art[1]]}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        store = db.session.get(Collection, store_id)
        fams = GD2.back_families(store)
        assert [f['id'] for f in fams] == [art[0], art[2]]                         # two main images
        assert [c['id'] for c in fams[0]['colors']] == [art[1]] and fams[1]['colors'] == []
        # removing the main takes its colors with it
        GD2.set_back_ids(store, [art[1], art[2]])
        assert GD2.back_ids(store) == [art[2]] and store.back_design_id == art[2]
    page = admin_client.get(f'/admin/collections/{store_id}/edit').get_data(as_text=True)      # the edit page lists them with their colors
    assert page.count('class="back-art-card"') == 2 and 'unlinkBack' in page and 'linkBackDesigns' in page
    resp = admin_client.post(f'/admin/collections/{store_id}/back-designs/{art[1]}/unlink')
    assert resp.status_code in (302, 200)


def test_saving_the_form_keeps_ticked_back_images_and_links_new_uploads(app, seed):
    from werkzeug.datastructures import MultiDict
    from utils import group_designs as GD2
    from utils.group_orders import apply_locked_back_design
    school_id, stores, art = _school(app, seed)
    with app.test_request_context('/', method='POST', data=MultiDict([
            ('back_designs_listed', '1'), ('back_design_ids', str(art[0])), ('back_design_ids', str(art[1])),
            ('new_back_designs', str(art[0])), ('new_back_designs', str(art[1])), ('link_new_back_uploads', 'on')])):
        store = db.session.get(Collection, stores['Cheer'])
        apply_locked_back_design(store, None)
        db.session.commit()
        assert GD2.back_ids(store) == [art[0], art[1]]
        assert db.session.get(Design, art[1]).parent_design_id == art[0]
    with app.test_request_context('/', method='POST', data=MultiDict([('back_designs_listed', '1'), ('back_design_ids', str(art[0]))])):
        store = db.session.get(Collection, stores['Cheer'])
        apply_locked_back_design(store, None)
        assert GD2.back_ids(store) == [art[0]]                                     # unticking the color removed it
    with app.test_request_context('/', method='POST', data=MultiDict([('back_designs_listed', '1')])):
        store = db.session.get(Collection, stores['Cheer'])
        apply_locked_back_design(store, None)
        assert GD2.back_ids(store) == [] and store.back_design_id is None
