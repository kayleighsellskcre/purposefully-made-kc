"""Admin site-error list: dismiss rows after they have been checked."""
from models import SiteError, db


def _add_error(app, error_id, path='/api/artwork-fits'):
    with app.app_context():
        row = SiteError(
            error_id=error_id,
            path=path,
            method='GET',
            message='RuntimeError: Working outside of application context.',
        )
        db.session.add(row)
        db.session.commit()


def test_site_errors_page_has_dismiss_and_clear(admin_client, app):
    _add_error(app, 'aa11bb22cc33dd44')
    html = admin_client.get('/admin/site-errors').get_data(as_text=True)
    assert 'aa11bb22cc33dd44' in html
    assert 'Dismiss' in html
    assert 'Clear all' in html
    assert '/admin/site-errors/aa11bb22cc33dd44/delete' in html


def test_admin_can_dismiss_one_error(admin_client, app):
    _add_error(app, 'aa11bb22cc33dd44')
    _add_error(app, 'ee55ff6677889900')
    resp = admin_client.post(
        '/admin/site-errors/aa11bb22cc33dd44/delete',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'aa11bb22cc33dd44' not in body
    assert 'ee55ff6677889900' in body
    with app.app_context():
        assert SiteError.query.filter_by(error_id='aa11bb22cc33dd44').first() is None
        assert SiteError.query.filter_by(error_id='ee55ff6677889900').first() is not None


def test_admin_can_clear_all_errors(admin_client, app):
    _add_error(app, 'aa11bb22cc33dd44')
    _add_error(app, 'ee55ff6677889900')
    resp = admin_client.post('/admin/site-errors/clear', follow_redirects=True)
    assert resp.status_code == 200
    assert 'No recorded 500s yet' in resp.get_data(as_text=True)
    with app.app_context():
        assert SiteError.query.count() == 0


def test_a_guest_cannot_clear_site_errors(guest, app):
    _add_error(app, 'aa11bb22cc33dd44')
    resp = guest.post('/admin/site-errors/clear', follow_redirects=False)
    assert resp.status_code in (302, 401, 403, 404)
    with app.app_context():
        assert SiteError.query.count() == 1
