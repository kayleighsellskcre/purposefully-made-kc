"""Admin design gallery: edit metadata and remove/delete actions."""
from models import Design

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
