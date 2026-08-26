"""Admin Design Library remove: keep customer copies, hide from admin fast."""
from models import Design, db

from tests.conftest import CUSTOMER_EMAIL


def test_admin_library_remove_keeps_customer_design(admin_client, seed, app):
    with app.app_context():
        design = Design(
            filename='cust-logo.png',
            original_filename='customer-logo.png',
            file_path='uploads/designs/cust-logo.png',
            is_gallery=False,
            uploaded_by_user_id=seed['customer_id'],
        )
        db.session.add(design)
        db.session.commit()
        design_id = design.id

    resp = admin_client.post(
        f'/admin/designs/{design_id}/delete',
        headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert 'customer' in body['message'].lower()

    with app.app_context():
        design = Design.query.get(design_id)
        assert design is not None
        assert design.hidden_from_admin is True
        assert design.uploaded_by_user_id == seed['customer_id']
        assert design.file_path == 'uploads/designs/cust-logo.png'

    html = admin_client.get('/admin/designs?tab=library').get_data(as_text=True)
    assert f'data-design-id="{design_id}"' not in html


def test_admin_library_hard_deletes_orphan(admin_client, seed, app):
    with app.app_context():
        design = Design(
            filename='orphan.png',
            original_filename='orphan.png',
            file_path='uploads/designs/orphan-missing.png',
            is_gallery=False,
            uploaded_by_user_id=None,
        )
        db.session.add(design)
        db.session.commit()
        design_id = design.id

    resp = admin_client.post(
        f'/admin/designs/{design_id}/delete',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    with app.app_context():
        assert Design.query.get(design_id) is None


def test_customer_still_sees_design_after_admin_remove(client, seed, login, app, admin_client):
    with app.app_context():
        design = Design(
            filename='keep-me.png',
            original_filename='keep-me.png',
            file_path='uploads/designs/keep-me.png',
            is_gallery=False,
            uploaded_by_user_id=seed['customer_id'],
        )
        db.session.add(design)
        db.session.commit()
        design_id = design.id

    assert admin_client.post(
        f'/admin/designs/{design_id}/delete',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    ).status_code == 200

    login(client, CUSTOMER_EMAIL)
    html = client.get('/account/designs').get_data(as_text=True)
    assert 'keep-me' in html
    with app.app_context():
        d = Design.query.get(design_id)
        assert d is not None
        assert d.uploaded_by_user_id == seed['customer_id']
        assert d.hidden_from_admin is True
