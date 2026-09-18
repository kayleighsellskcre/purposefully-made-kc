"""Admin inbox: contact messages and design requests, not orders."""
from models import AdminNotification, CustomDesignRequest

from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL
from tests.test_design_request_flow import a_png, submit as submit_design


def test_dashboard_replaces_test_email_with_notifications(admin_client, seed):
    html = admin_client.get('/admin/').get_data(as_text=True)
    assert 'Notifications' in html
    assert 'Test Email' not in html
    assert '/admin/notifications' in html


def test_contact_form_creates_an_unread_notification(client, app):
    resp = client.post('/contact', data={
        'name': 'Jamie Neighbor',
        'email': 'jamie@example.com',
        'subject': 'Group shirts for Riverview',
        'message': 'Can you do 40 tees by Friday?',
    }, follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        note = AdminNotification.query.filter_by(kind='contact').one()
        assert note.read_at is None
        assert note.from_name == 'Jamie Neighbor'
        assert note.from_email == 'jamie@example.com'
        assert '40 tees' in (note.body or '')
        assert 'Riverview' in (note.preview or note.title)


def test_design_request_creates_an_unread_notification(customer_client, seed, app):
    submit_design(customer_client, upload=a_png())
    with app.app_context():
        req = CustomDesignRequest.query.one()
        note = AdminNotification.query.filter_by(kind='design_request').one()
        assert note.read_at is None
        assert note.related_id == req.id
        assert note.url == f'/admin/custom-design-requests/{req.id}'


def test_orders_do_not_create_inbox_notifications(app, seed):
    with app.app_context():
        assert AdminNotification.query.count() == 0


def test_admin_can_open_the_inbox(admin_client, client, app):
    client.post('/contact', data={
        'name': 'Pat',
        'email': 'pat@example.com',
        'subject': 'Hello',
        'message': 'Just saying hi.',
    })
    html = admin_client.get('/admin/notifications').get_data(as_text=True)
    assert 'Just saying hi' in html
    assert 'Pat' in html
    assert 'Reply by email' in html


def test_customer_cannot_open_the_inbox(client, seed, login):
    login(client, CUSTOMER_EMAIL)
    resp = client.get('/admin/notifications', follow_redirects=False)
    assert resp.status_code in (302, 401, 403)


def test_opening_a_design_notification_marks_it_read(client, seed, login, app):
    login(client, CUSTOMER_EMAIL)
    submit_design(client, upload=a_png())
    with app.app_context():
        note = AdminNotification.query.filter_by(kind='design_request').one()
        note_id = note.id
        dest = note.url
    client.get('/auth/logout')
    login(client, ADMIN_EMAIL)
    resp = client.get(f'/admin/notifications/{note_id}/open', follow_redirects=False)
    assert resp.status_code == 302
    assert dest in (resp.headers.get('Location') or '')
    with app.app_context():
        note = AdminNotification.query.get(note_id)
        assert note.read_at is not None


def test_mark_all_read_clears_the_badge(admin_client, client, app):
    client.post('/contact', data={
        'name': 'Pat',
        'email': 'pat@example.com',
        'subject': 'Hello',
        'message': 'Please call me.',
    })
    admin_client.post('/admin/notifications/mark-all-read', follow_redirects=False)
    with app.app_context():
        assert AdminNotification.query.filter_by(read_at=None).count() == 0
    html = admin_client.get('/admin/').get_data(as_text=True)
    assert 'dash-notify-badge">' not in html
