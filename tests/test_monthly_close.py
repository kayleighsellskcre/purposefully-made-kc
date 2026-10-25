"""The monthly close email: last month's numbers, sent once, with the P&L attached."""
import threading
from datetime import date, datetime

import pytest

from models import Order, db
from utils import ledger as L
from utils import monthly_close as MC


def _in_db(app, fn):
    out = {}

    def run():
        with app.app_context():
            try:
                out['value'] = fn()
            except Exception as exc:          # pragma: no cover
                out['error'] = exc
    t = threading.Thread(target=run)
    t.start()
    t.join()
    if 'error' in out:
        raise out['error']
    return out.get('value')


@pytest.fixture(autouse=True)
def _unthrottled():
    L._LAST_SYNC['at'] = 0.0
    yield
    L._LAST_SYNC['at'] = 0.0


def test_previous_month_handles_january():
    assert MC.previous_month(date(2026, 1, 2))[:2] == (date(2025, 12, 1), date(2025, 12, 31))
    assert MC.previous_month(date(2026, 3, 2))[2] == 'February 2026'


def _setup():
    db.session.add(Order(order_number='PMKC-MC1', email='a@example.com', subtotal=100.0, shipping_cost=0.0, tax=9.5, total=109.5,
                         payment_status='paid', status='paid', payment_method='stripe', paid_at=datetime(2026, 9, 15, 18, 0)))
    db.session.commit()
    L.add_expense(when_day=date(2026, 9, 20), vendor='Shop', amount_dollars='20', category='Supplies')


def test_summary_uses_last_month_and_flags_missing_receipts(app, seed):
    def go():
        _setup()
        L.sync_all(force=True)
        s = MC.summary(date(2026, 10, 2))
        assert s['label'] == 'September 2026' and s['p']['net_sales'] == 10000
        assert any('no receipt' in t for t in s['looks'])
    _in_db(app, go)


def test_close_email_goes_once_with_the_pdf(app, seed, monkeypatch):
    sent = []

    def fake_send(to, subject, heading, paragraphs, **kw):
        sent.append((to, subject, kw.get('attachments'), kw.get('details')))
        return True
    monkeypatch.setattr('utils.sponsor_emails._send', fake_send)

    def go():
        _setup()
        assert MC.send_close(date(2026, 10, 2)) is True
        assert MC.send_close(date(2026, 10, 3)) is False                  # already sent for September
        assert len(sent) == 1
        assert MC.send_close(date(2026, 10, 3), force=True) is True       # the button resends
        assert MC.send_close(date(2026, 11, 2)) is True                   # a new month sends again
    _in_db(app, go)
    to, subject, attachments, details = sent[0]
    assert 'September 2026 is closed' in subject and attachments[0][2].startswith(b'%PDF')
    assert ('Net sales', '$100.00') in details


def test_a_failed_send_is_tried_again_later(app, seed, monkeypatch):
    monkeypatch.setattr('utils.sponsor_emails._send', lambda *a, **k: False)

    def go():
        assert MC.send_close(date(2026, 10, 2)) is False
        monkeypatch.setattr('utils.sponsor_emails._send', lambda *a, **k: True)
        assert MC.send_close(date(2026, 10, 3)) is True
    _in_db(app, go)


def test_button_works_for_admin(admin_client, monkeypatch):
    monkeypatch.setattr('utils.sponsor_emails._send', lambda *a, **k: True)
    assert admin_client.post('/admin/operations/reports/close-email').status_code in (302, 303)


def test_button_is_closed_to_guests(guest):
    assert guest.post('/admin/operations/reports/close-email').status_code in (302, 303, 400, 401, 403, 404)
