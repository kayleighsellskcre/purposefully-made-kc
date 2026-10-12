"""The admin is told every time someone sets up a group; banners never say "no rush" next to a deadline."""
from datetime import datetime, timedelta

from models import AdminNotification, Collection, db
from tests.conftest import CUSTOMER_EMAIL
from tests.test_group_orders import _base_form, _post


def _alerts(outbox):
    return [m for m in outbox if m.subject.startswith('New group order:')]


# ── The admin hears about every new group ───────────────────────────────────

def test_a_new_group_emails_the_admin_and_lands_in_the_inbox(customer_client, app, seed, outbox):
    soon = (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d')
    resp = _post(customer_client, _base_form(seed, name='Falcons Spirit Wear', order_deadline=soon))
    assert resp.status_code == 200

    mail = _alerts(outbox)
    assert len(mail) == 1
    alert = mail[0]
    assert alert.recipients == [app.config['ADMIN_EMAIL']]
    assert alert.subject == 'New group order: Falcons Spirit Wear'
    assert CUSTOMER_EMAIL in alert.body and CUSTOMER_EMAIL in alert.html
    assert '/admin/collections/' in alert.body and '/c/' in alert.body       # open-in-admin + store link
    assert alert.reply_to == CUSTOMER_EMAIL                                   # replying reaches the organizer
    assert 'No deadline' not in alert.body                                    # the deadline they chose is shown

    with app.app_context():
        notes = AdminNotification.query.filter_by(kind='group_order').all()
        assert len(notes) == 1
        assert notes[0].title == 'New group order: Falcons Spirit Wear'
        assert notes[0].url.startswith('/admin/collections/')


def test_the_alert_shows_no_deadline_when_there_is_none(customer_client, seed, outbox):
    _post(customer_client, _base_form(seed, name='No Deadline Group'))
    assert 'No deadline' in _alerts(outbox)[0].body


def test_a_group_the_admin_sets_up_themself_does_not_alert_them(admin_client, app, seed, outbox):
    resp = admin_client.post('/shop/group-orders/create', data=_base_form(seed, name='Admin Made'),
                             content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert _alerts(outbox) == []
    with app.app_context():
        assert AdminNotification.query.filter_by(kind='group_order').count() == 0


def test_a_multi_team_organization_is_one_alert_listing_the_teams(customer_client, seed, outbox):
    from tests.test_multi_team_group_orders import _wizard
    resp = customer_client.post('/shop/group-orders/create', data=_wizard(seed),
                                content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    mail = _alerts(outbox)
    assert len(mail) == 1                                                     # one alert, not one per team
    for team in ('Basketball', 'Soccer', 'Volleyball'):
        assert team in mail[0].body


def test_a_problem_sending_the_alert_never_blocks_the_group(customer_client, app, seed, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('inbox is down')
    monkeypatch.setattr('utils.group_notifications.create_notification', boom)
    monkeypatch.setattr('utils.group_notifications.send', boom)
    resp = _post(customer_client, _base_form(seed, name='Still Created'))
    assert resp.status_code == 200
    with app.app_context():
        assert Collection.query.filter_by(name='Still Created').count() == 1


def test_the_inbox_labels_the_item(client, app, seed):
    from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL, _login
    _login(client, CUSTOMER_EMAIL)
    _post(client, _base_form(seed, name='Inbox Group'))
    client.get('/auth/logout')
    _login(client, ADMIN_EMAIL)
    html = client.get('/admin/notifications').get_data(as_text=True)
    assert 'New group order' in html and 'Inbox Group' in html


# ── "Orders open ... no rush" must not appear next to a deadline ────────────

def _not_open_yet(app, seed, deadline):
    from utils.group_orders import parse_order_deadline, parse_order_opens
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.order_opens_at = parse_order_opens((datetime.utcnow() + timedelta(days=5)).strftime('%Y-%m-%d'))
        coll.order_deadline = parse_order_deadline(deadline) if deadline else None
        db.session.commit()
        return coll.slug


def test_a_group_with_a_deadline_says_when_it_opens_and_closes(client, app, seed):
    slug = _not_open_yet(app, seed, (datetime.utcnow() + timedelta(days=40)).strftime('%Y-%m-%d'))
    html = client.get(f'/c/{slug}').get_data(as_text=True)
    assert 'throughout the school year' not in html and 'throughout the entire school year' not in html
    assert 'and close' in html
    assert 'no rush' not in html.lower()


def test_a_group_without_a_deadline_keeps_the_all_year_wording(client, app, seed):
    slug = _not_open_yet(app, seed, None)
    html = client.get(f'/c/{slug}').get_data(as_text=True)
    assert 'throughout the school year' in html
