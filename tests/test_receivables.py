"""Who owes you: ages, recording cash/Venmo payments onto the books, and the optional 7/14/30 day reminders."""
import json
import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from models import InvoicePayment, LedgerEntry, ManualInvoice, db
from utils import ledger as L
from utils import receivables as R


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


def _kc_noon(days_old):
    """Midday Kansas City, days_old days ago, as stored UTC, so the test never lands on a midnight edge."""
    noon = datetime.combine(L.kc_today() - timedelta(days=days_old), datetime.min.time()).replace(hour=12, tzinfo=L.CENTRAL)
    return noon.astimezone(timezone.utc).replace(tzinfo=None)


def _invoice(number='INV-T-1', days_old=0, email='cust@example.com', total_units=100.0):
    inv = ManualInvoice(number=number, customer_name='Dana Smith', email=email, tax_rate=0.0,
                        items_json=json.dumps([{'description': 'Shirts', 'qty': 1, 'unit': total_units}]),
                        issued_at=_kc_noon(days_old))
    db.session.add(inv)
    db.session.commit()
    return inv


def _income():
    return int(db.session.query(db.func.coalesce(db.func.sum(LedgerEntry.amount_cents), 0))
               .filter(LedgerEntry.entry_type.in_([L.SALE, L.SHIPPING, L.TAX])).scalar())


def test_ages_and_buckets(app, seed):
    def go():
        _invoice('A', 3)
        _invoice('B', 20)
        _invoice('C', 45)
        rows = R.open_rows()
        assert sorted(r['age'] for r in rows) == [3, 20, 45]
        b = {x['label']: x['count'] for x in R.buckets(rows)}
        assert b['0 to 7 days'] == 1 and b['15 to 30 days'] == 1 and b['Over 30 days'] == 1
    _in_db(app, go)


def test_a_payment_is_logged_and_lands_on_the_books_once(app, seed):
    def go():
        inv = _invoice()
        assert _income() == 0                                          # unpaid is not income yet
        R.record_payment(inv.id, '40', 'Venmo')
        assert _income() == 4000 and inv.amount_paid == 40.0 and inv.payment_method == 'Venmo'
        R.record_payment(inv.id, '60', 'Cash')
        assert _income() == 10000 and R.open_rows() == []
        assert [p.amount_cents for p in InvoicePayment.query.order_by(InvoicePayment.id)] == [4000, 6000]
        L.sync_all(force=True)
        assert _income() == 10000                                      # syncing again adds nothing
    _in_db(app, go)


def test_a_first_payment_can_be_dated_earlier_but_not_later_ones(app, seed):
    def go():
        inv = _invoice()
        earlier = L.kc_today() - timedelta(days=9)
        R.record_payment(inv.id, '30', 'Cash', paid_on=earlier)
        assert InvoicePayment.query.first().paid_on == earlier
        R.record_payment(inv.id, '30', 'Cash', paid_on=earlier)
        assert InvoicePayment.query.order_by(InvoicePayment.id.desc()).first().paid_on == L.kc_today()
        days = {e.kc_date for e in LedgerEntry.query.filter(LedgerEntry.invoice_id == inv.id)}
        assert earlier in days
    _in_db(app, go)


def test_bad_payments_are_refused(app, seed):
    def go():
        inv = _invoice()
        for args in (('0', 'Cash'), ('150', 'Cash'), ('10', 'Bitcoin')):
            with pytest.raises(ValueError):
                R.record_payment(inv.id, *args)
        with pytest.raises(ValueError):
            R.record_payment(9999, '5', 'Cash')
        assert InvoicePayment.query.count() == 0 and _income() == 0
    _in_db(app, go)


def test_reminders_stay_off_until_turned_on_then_go_once_per_stage(app, seed, monkeypatch):
    sent = []
    monkeypatch.setattr('utils.invoice_emails.send_reminder', lambda inv, stage: sent.append((inv.number, stage)) or True)

    def go():
        _invoice('OLD', 20)
        _invoice('NEW', 2)
        _invoice('NOMAIL', 40, email='')
        assert R.run_reminders() == 0 and sent == []                    # off by default
        R.set_reminders(True)
        assert R.run_reminders() == 1 and sent == [('OLD', 2)]          # 20 days old: the 14 day reminder, once
        assert R.run_reminders() == 0
        later = L.kc_today() + timedelta(days=12)                       # now 32 days old
        assert R.run_reminders(later) == 2                              # OLD reaches 30 days; NEW reaches its first reminder at 14
        assert ('OLD', 3) in sent and ('NEW', 2) in sent and not any(n == 'NOMAIL' for n, _s in sent)
    _in_db(app, go)


def test_a_paid_invoice_gets_no_reminder(app, seed, monkeypatch):
    sent = []
    monkeypatch.setattr('utils.invoice_emails.send_reminder', lambda inv, stage: sent.append(inv.number) or True)

    def go():
        inv = _invoice('PAID', 30)
        R.record_payment(inv.id, '100', 'Check')
        R.set_reminders(True)
        assert R.run_reminders() == 0 and sent == []
    _in_db(app, go)


def test_page_and_actions(admin_client, app):
    resp = admin_client.get('/admin/operations/receivables')
    assert resp.status_code == 200 and b'Who Owes You' in resp.data
    assert b'Turn reminders on' in resp.data
    admin_client.post('/admin/operations/receivables', data={'action': 'auto', 'on': '1'}, follow_redirects=True)
    assert b'Reminders are on' in admin_client.get('/admin/operations/receivables').data


def test_guests_cannot_open_it(guest):
    assert guest.get('/admin/operations/receivables').status_code in (301, 302, 303, 401, 403, 404)
