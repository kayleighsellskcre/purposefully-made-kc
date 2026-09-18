"""Admin design gallery: edit metadata and remove/delete actions."""
import io

from models import Design, db

from tests.conftest import CUSTOMER_EMAIL


def test_admin_gallery_page_has_edit_controls(admin_client, seed):
    html = admin_client.get('/admin/designs?tab=gallery').get_data(as_text=True)
    assert 'openGalleryEdit' in html
    assert '/design-gallery/' in html and '/edit' in html
    assert 'Remove from Gallery' in html
    assert 'Delete' in html
    assert 'Design Library' in html
    assert 'Gallery' in html


def test_old_design_gallery_url_redirects(admin_client, seed):
    resp = admin_client.get('/admin/design-gallery', follow_redirects=False)
    assert resp.status_code == 301
    assert '/admin/designs' in (resp.headers.get('Location') or '')
    assert 'tab=gallery' in (resp.headers.get('Location') or '')


def test_admin_can_edit_gallery_design_info(admin_client, seed, app):
    with app.app_context():
        design = Design.query.filter_by(is_gallery=True).first()
        assert design is not None
        design_id = design.id

    resp = admin_client.post(
        f'/admin/design-gallery/{design_id}/edit',
        data={
            'title': 'Updated Falcons Logo',
            'folder': 'school',
            'sku': 'DSG-100',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['design']['title'] == 'Updated Falcons Logo'
    assert body['design']['folder'] == 'school'
    assert body['design']['sku'] == 'DSG-100'

    with app.app_context():
        design = Design.query.get(design_id)
        assert design.title == 'Updated Falcons Logo'
        assert design.folder == 'school'
        assert design.sku == 'DSG-100'


def test_gallery_upload_requires_a_folder(admin_client):
    resp = admin_client.post(
        '/admin/design-gallery/upload',
        data={
            'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 40), 'logo.png'),
            'title': 'Unfiled Design',
        },
        content_type='multipart/form-data',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['ok'] is False
    assert 'folder' in (body.get('error') or '').lower()


def test_gallery_upload_stores_the_chosen_folder(admin_client, app, monkeypatch):
    import routes.admin as admin_routes

    def fake_save(file, user_id, **kwargs):
        design = Design(
            filename='helmet.png',
            original_filename=file.filename,
            file_path='uploads/designs/helmet.png',
            is_gallery=True,
            uploaded_by_user_id=user_id,
        )
        db.session.add(design)
        db.session.flush()
        return design

    monkeypatch.setattr(admin_routes, '_save_uploaded_design', fake_save)
    resp = admin_client.post(
        '/admin/design-gallery/upload',
        data={
            'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 40), 'helmet.png'),
            'title': 'Chiefs Helmet',
            'extra_categories': 'sports',
        },
        content_type='multipart/form-data',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    with app.app_context():
        design = Design.query.get(body['design_id'])
        assert design.folder == 'sports'
        assert design.extra_categories is None


def test_gallery_color_upload_inherits_parent_folder(admin_client, app, seed, monkeypatch):
    import routes.admin as admin_routes

    with app.app_context():
        parent = Design.query.filter_by(is_gallery=True).first()
        parent.folder = 'school'
        parent.extra_categories = 'kc'
        db.session.commit()
        parent_id = parent.id

    def fake_save(file, user_id, **kwargs):
        design = Design(
            filename='helmet-white.png',
            original_filename=file.filename,
            file_path='uploads/designs/helmet-white.png',
            is_gallery=True,
            uploaded_by_user_id=user_id,
        )
        db.session.add(design)
        db.session.flush()
        return design

    monkeypatch.setattr(admin_routes, '_save_uploaded_design', fake_save)
    resp = admin_client.post(
        '/admin/design-gallery/upload',
        data={
            'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 40), 'helmet-white.png'),
            'title': 'Ignored',
            'parent_design_id': str(parent_id),
        },
        content_type='multipart/form-data',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    with app.app_context():
        child = Design.query.get(body['design_id'])
        assert child.parent_design_id == parent_id
        assert child.folder == 'school'
        assert child.extra_categories == 'kc'


def test_admin_gallery_offers_set_cover_for_color_variants(admin_client, app, seed):
    with app.app_context():
        main = Design.query.filter_by(is_gallery=True).first()
        child = Design(
            filename='cover-white.png',
            original_filename='cover-white.png',
            file_path='uploads/designs/cover-white.png',
            title=main.title,
            is_gallery=True,
            parent_design_id=main.id,
            variant_label='White',
            uploaded_by_user_id=main.uploaded_by_user_id,
        )
        db.session.add(child)
        db.session.commit()
        child_id = child.id

    html = admin_client.get('/admin/designs?tab=gallery').get_data(as_text=True)
    assert 'Set cover' in html
    assert f'/design-gallery/{child_id}/make-main' in html


def test_admin_can_set_a_color_variant_as_the_gallery_cover(admin_client, app, seed):
    with app.app_context():
        main = Design.query.filter_by(is_gallery=True, parent_design_id=None).first()
        main.variant_label = 'Navy'
        child = Design(
            filename='cover-gold.png',
            original_filename='cover-gold.png',
            file_path='uploads/designs/cover-gold.png',
            title=main.title,
            is_gallery=True,
            parent_design_id=main.id,
            variant_label='Gold',
            uploaded_by_user_id=main.uploaded_by_user_id,
        )
        db.session.add(child)
        db.session.commit()
        old_main_id = main.id
        child_id = child.id

    resp = admin_client.post(
        f'/admin/design-gallery/{child_id}/make-main',
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        new_main = Design.query.get(child_id)
        old_main = Design.query.get(old_main_id)
        assert new_main.parent_design_id is None
        assert old_main.parent_design_id == child_id


def test_customer_cannot_edit_gallery_design(client, seed, login, app):
    login(client, CUSTOMER_EMAIL)
    with app.app_context():
        design = Design.query.filter_by(is_gallery=True).first()
        design_id = design.id
    resp = client.post(
        f'/admin/design-gallery/{design_id}/edit',
        data={'title': 'Hacked', 'folder': 'school'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code in (302, 401, 403)
    with app.app_context():
        design = Design.query.get(design_id)
        assert design.title != 'Hacked'
