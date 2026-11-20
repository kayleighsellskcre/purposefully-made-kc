"""Admin search box and the list of emails that did not send."""
from flask_mail import Message

from models import EmailFailure, ManualInvoice, Order, db


def _failed_email(app, to='pat@example.com'):
    from utils import mailer
    with app.app_context():
        app.config['BREVO_API_KEY'] = ''
        app.config['MAIL_SERVER'] = None
        assert mailer.send(app, Message(subject='Your invoice', recipients=[to], html='<p>hi</p>'), 'invoice INV-1') is False
        return EmailFailure.query.order_by(EmailFailure.id.desc()).first().id


def test_a_failed_email_is_remembered_and_shown_on_the_dashboard(app, seed, admin_client):
    _failed_email(app)
    page = admin_client.get('/admin/email-problems').get_data(as_text=True)
    assert 'Your invoice' in page and 'pat@example.com' in page and 'Resend' in page
    assert '1 email did not send' in admin_client.get('/admin/').get_data(as_text=True)


def test_resend_removes_it_only_when_it_really_goes(app, seed, admin_client, monkeypatch):
    from utils import mailer
    row_id = _failed_email(app)
    monkeypatch.setattr(mailer, 'send', lambda *a, **k: False)
    admin_client.post(f'/admin/email-problems/{row_id}/resend')
    with app.app_context():
        assert db.session.get(EmailFailure, row_id).resolved is False
    monkeypatch.setattr(mailer, 'send', lambda *a, **k: True)
    admin_client.post(f'/admin/email-problems/{row_id}/resend')
    with app.app_context():
        assert db.session.get(EmailFailure, row_id).resolved is True
    assert 'Every email went out' in admin_client.get('/admin/email-problems').get_data(as_text=True)


def test_search_finds_orders_invoices_and_goes_straight_to_a_single_answer(app, seed, admin_client):
    with app.app_context():
        db.session.add(ManualInvoice(number='INV-ZED-1', kind='invoice', customer_name='Zelda Quill', email='zq@example.com',
                                     phone='(816) 555-0142', items_json='[]'))
        db.session.add(ManualInvoice(number='INV-ZED-2', kind='invoice', customer_name='Zelda Quill', email='zq@example.com',
                                     items_json='[]'))
        db.session.commit()
    many = admin_client.get('/admin/search?q=Zelda')
    html = many.get_data(as_text=True)
    assert many.status_code == 200 and 'INV-ZED-1' in html and 'INV-ZED-2' in html
    one = admin_client.get('/admin/search?q=INV-ZED-2')
    assert one.status_code == 302 and '/invoices/' in one.headers['Location']
    phone = admin_client.get('/admin/search?q=816-555-0142')
    assert phone.status_code == 302                                  # phone numbers match however they were typed
    assert 'Nothing found' in admin_client.get('/admin/search?q=qqqqqq').get_data(as_text=True)


def test_search_needs_an_admin(app, seed):
    assert app.test_client().get('/admin/search?q=a').status_code in (302, 401, 403)


def test_a_quiet_problem_is_listed_once_and_does_not_disturb_the_page_work(app, seed):
    from models import SiteError
    from utils.quiet_errors import report_quiet
    with app.test_request_context('/admin/orders'):
        pending = ManualInvoice(number='INV-Q-1', kind='invoice', customer_name='Q', items_json='[]')
        db.session.add(pending)
        db.session.commit()
        pending.note = 'kept'                                   # unsaved work the caller is in the middle of
        for _ in range(3):
            try:
                raise ValueError('card fee lookup failed')
            except ValueError:
                report_quiet('refreshing the card fee')
        assert pending in db.session.dirty                  # the caller's own work is still waiting, not saved by the report
        rows = SiteError.query.filter(SiteError.message.like('%refreshing the card fee%')).all()
        assert len(rows) == 1 and 'the page still worked' in rows[0].message
        db.session.rollback()
