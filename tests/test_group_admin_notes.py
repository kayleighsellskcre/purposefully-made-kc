"""The owner's private notes on a group order: saved, shown to her, and never anywhere a customer or organizer can see."""
from models import Collection, db

NOTE = 'Invoice the PTA in January. Use the 2024 logo.'


def _slug(app, cid):
    with app.app_context():
        return db.session.get(Collection, cid).slug


def test_the_owner_can_save_a_note_and_sees_it_on_the_edit_page_and_the_list(app, seed, admin_client):
    cid = seed['collection_id']
    resp = admin_client.post(f'/admin/collections/{cid}/notes', data={'admin_notes': NOTE})
    assert resp.status_code == 302
    edit = admin_client.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert NOTE in edit and 'Only you can see this' in edit
    listing = admin_client.get('/admin/collections').get_data(as_text=True)
    assert 'Your note:' in listing and 'Invoice the PTA in January' in listing


def test_a_note_never_shows_on_the_public_store_or_the_organizers_own_edit_page(app, seed, admin_client):
    cid = seed['collection_id']
    admin_client.post(f'/admin/collections/{cid}/notes', data={'admin_notes': NOTE})
    slug = _slug(app, cid)
    organizer_page = admin_client.get(f'/shop/group-orders/{slug}/edit').get_data(as_text=True)
    assert NOTE not in organizer_page
    admin_client.get('/auth/logout')
    assert NOTE not in admin_client.get(f'/collection/{slug}').get_data(as_text=True)


def test_only_the_owner_can_save_a_note(app, seed, customer_client):
    cid = seed['collection_id']
    resp = customer_client.post(f'/admin/collections/{cid}/notes', data={'admin_notes': 'sneaky'})
    assert resp.status_code in (302, 401, 403)
    with app.app_context():
        assert not db.session.get(Collection, cid).admin_notes


def test_clearing_the_box_removes_the_note(app, seed, admin_client):
    cid = seed['collection_id']
    admin_client.post(f'/admin/collections/{cid}/notes', data={'admin_notes': NOTE})
    admin_client.post(f'/admin/collections/{cid}/notes', data={'admin_notes': '   '})
    with app.app_context():
        assert db.session.get(Collection, cid).admin_notes is None
