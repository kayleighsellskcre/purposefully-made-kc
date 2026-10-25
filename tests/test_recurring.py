"""Monthly bills and the equipment log."""
import threading
from datetime import date

import pytest

from models import Expense, LedgerEntry, db
from utils import ledger as L
from utils import recurring as R


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


def test_a_bill_adds_each_month_once_and_catches_up(app, seed):
    def go():
        R.add_rule(vendor='Canva', amount_dollars='15', category='Software and subscriptions', day_of_month=5,
                   start_date=date(2026, 8, 20))
        assert R.make_due(today=date(2026, 10, 3)) == 2                   # Aug 5 and Sep 5; Oct 5 is not here yet
        assert R.make_due(today=date(2026, 10, 3)) == 0                   # never twice
        assert R.make_due(today=date(2026, 10, 5)) == 1
        days = sorted(e.expense_date for e in Expense.query.all())
        assert days == [date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5)]
        assert db.session.query(db.func.sum(LedgerEntry.amount_cents)).filter(LedgerEntry.entry_type == L.EXPENSE).scalar() == -4500
    _in_db(app, go)


def test_a_voided_month_is_not_made_again_and_stopping_halts_new_months(app, seed):
    def go():
        rule = R.add_rule(vendor='Storage', amount_dollars='40', category='Rent', day_of_month=31, start_date=date(2026, 1, 1))
        R.make_due(today=date(2026, 2, 28))
        assert sorted(e.expense_date for e in Expense.query.all()) == [date(2026, 1, 28), date(2026, 2, 28)]   # day clamps to 28
        L.void_expense(Expense.query.order_by(Expense.id).first().id)
        R.make_due(today=date(2026, 2, 28))
        assert Expense.query.count() == 2
        R.set_active(rule.id, False)
        assert R.make_due(today=date(2026, 6, 1)) == 0
        R.set_active(rule.id, True)
        assert R.make_due(today=date(2026, 3, 30)) == 1
    _in_db(app, go)


def test_bad_bills_are_refused(app, seed):
    def go():
        for kw in (dict(vendor='', amount_dollars='5', category='Rent'), dict(vendor='X', amount_dollars='0', category='Rent'),
                   dict(vendor='X', amount_dollars='5', category='Nope')):
            with pytest.raises(ValueError):
                R.add_rule(**kw)
    _in_db(app, go)


def test_pages_work_for_admin_and_not_guests(admin_client):
    resp = admin_client.get('/admin/operations/recurring')
    assert resp.status_code == 200 and b'Monthly Bills' in resp.data
    resp = admin_client.get('/admin/operations/equipment')
    assert resp.status_code == 200 and b'Equipment' in resp.data
    csv = admin_client.get('/admin/operations/equipment?format=csv')
    assert csv.status_code == 200 and csv.data.startswith(b'Date,Item,Cost')


def test_guests_cannot_open_the_pages(guest):
    for path in ('/admin/operations/recurring', '/admin/operations/equipment'):
        assert guest.get(path).status_code in (301, 302, 303, 401, 403, 404)
