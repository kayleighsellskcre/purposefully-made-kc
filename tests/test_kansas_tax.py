"""Kansas Sales Tax: due dates, the three portal parts, what needs review, the filing record and reminders."""
import json
import threading
from datetime import date, datetime

from models import KsFiling, Order, db
from utils import ks_tax as K
from utils import ledger as L


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
    return out['value']


def _paid(number, subtotal, tax, when, **kw):
    defaults = dict(email='a@example.com', subtotal=subtotal, shipping_cost=0.0, tax=tax, total=round(subtotal + tax, 2),
                    payment_status='paid', status='paid', payment_method='stripe', fulfillment_method='pickup', paid_at=when)
    defaults.update(kw)
    o = Order(order_number=number, **defaults)
    db.session.add(o)
    db.session.flush()
    return o


def _keys(items):
    return [k for _f, k, _t, _d in items]


def test_due_date_is_the_25th_moved_to_the_next_business_day():
    assert K.computed_due_date(date(2026, 9, 30)) == date(2026, 10, 26)      # Oct 25 2026 is a Sunday
    assert K.computed_due_date(date(2026, 12, 31)) == date(2027, 1, 25)      # a Monday
    assert K.computed_due_date(date(2026, 6, 30)) == date(2026, 7, 27)       # Jul 25 2026 is a Saturday
    assert K.due_date(date(2026, 9, 30), date(2026, 10, 30)) == date(2026, 10, 30)   # what the portal shows wins


def test_periods_follow_the_filing_frequency():
    assert K.period_for(date(2026, 8, 14), 'quarterly') == (date(2026, 7, 1), date(2026, 9, 30))
    assert K.period_for(date(2026, 12, 2), 'quarterly') == (date(2026, 10, 1), date(2026, 12, 31))
    assert K.period_for(date(2026, 2, 10), 'monthly') == (date(2026, 2, 1), date(2026, 2, 28))
    assert K.period_for(date(2026, 2, 10), 'annual') == (date(2026, 1, 1), date(2026, 12, 31))
    assert K.period_label(date(2026, 7, 1), date(2026, 9, 30), 'quarterly') == 'Q3 2026'


def test_the_report_reproduces_the_quarter_she_filed(app, seed):
    def make():
        _paid('PMKC-K1', 300.0, 28.5, datetime(2026, 8, 5, 18, 0))
        _paid('PMKC-K2', 300.0, 28.5, datetime(2026, 8, 20, 18, 0))
        _paid('PMKC-K3', 270.0, 25.65, datetime(2026, 9, 12, 18, 0))
        db.session.commit()
        L.sync_all(force=True)
        return K.build_report(date(2026, 7, 1), date(2026, 9, 30))
    report = _in_db(app, make)
    [row] = report['rows']
    assert row['code'] == 'SHAJO' and row['rate'] == 9.6
    assert row['gross'] == 87000 and row['net'] == 87000
    assert row['calc'] == 8352 and row['collected'] == 8265 and row['diff'] == 87     # $83.52, $82.65, $0.87 short
    assert report['totals']['diff'] == 87 and report['has_activity']


def test_out_of_state_orders_are_line_m_and_missing_tracking_needs_review(app, seed):
    def make():
        _paid('PMKC-K4', 100.0, 9.5, datetime(2026, 8, 5, 18, 0))
        _paid('PMKC-K5', 50.0, 0.0, datetime(2026, 8, 6, 18, 0), fulfillment_method='shipping', shipping_state='MO', shipping_zip='64105')
        _paid('PMKC-K6', 25.0, 0.0, datetime(2026, 8, 7, 18, 0), fulfillment_method='shipping', shipping_state='MO', shipping_zip='64105',
              tracking_number='9400111')
        db.session.commit()
        L.sync_all(force=True)
        return K.build_report(date(2026, 7, 1), date(2026, 9, 30))
    report = _in_db(app, make)
    [row] = report['rows']
    assert report['line_m']['amount'] == 7500 and len(report['line_m']['orders']) == 2
    assert row['gross'] == 17500 and row['deductions'] == 7500 and row['net'] == 10000       # the deduction is entered once
    assert row['calc'] == 960
    assert [r['kind'] for r in report['review']].count('proof') == 1                          # only the one with no tracking


def test_a_kansas_shipment_waits_for_a_code_then_is_reported_under_it(app, seed):
    def make():
        o = _paid('PMKC-K7', 100.0, 9.5, datetime(2026, 8, 5, 18, 0), fulfillment_method='shipping', shipping_state='KS', shipping_zip='66202')
        db.session.commit()
        L.sync_all(force=True)
        first = K.build_report(date(2026, 7, 1), date(2026, 9, 30))
        K.save_jurisdiction('OVRPK', 'Overland Park', 9.475)
        o = db.session.get(Order, o.id)
        o.ks_code = 'OVRPK'
        db.session.commit()
        return first, K.build_report(date(2026, 7, 1), date(2026, 9, 30))
    first, second = _in_db(app, make)
    assert [r['kind'] for r in first['review']] == ['destination']
    assert [r['code'] for r in second['rows']] == ['OVRPK'] and not second['review']
    assert second['rows'][0]['calc'] == 948                                                   # 9.475% of $100, to the cent


def test_the_page_opens_and_saving_a_filing_keeps_a_copy_of_the_numbers(app, seed, admin_client):
    def make():
        _paid('PMKC-K8', 100.0, 9.5, datetime(2026, 8, 5, 18, 0))
        db.session.commit()
        L.sync_all(force=True)
    _in_db(app, make)
    page = admin_client.get('/admin/operations/kansas-tax?start=2026-07-01').get_data(as_text=True)
    assert 'Q3 2026' in page and 'Monday, October 26' in page and 'Part III' in page and 'Part II' in page and 'Part I' in page
    assert 'data-copy="9.60"' in page                                                          # the tax can be copied
    resp = admin_client.post('/admin/operations/kansas-tax/save', data={
        'start': '2026-07-01', 'action': 'filing', 'return_filed_on': '2026-10-27', 'confirmation_number': 'ABC123',
        'tax': '9.60', 'penalty': '1.00', 'interest': '0.20', 'total_paid': '10.80', 'payment_status': 'scheduled',
        'payment_settles_on': '2099-10-30'})
    assert resp.status_code == 302

    def check():
        f = KsFiling.query.filter_by(period_start=date(2026, 7, 1)).one()
        return f.confirmation_number, f.total_paid_cents, f.payment_status, json.loads(f.snapshot_json)['totals']['calc']
    assert _in_db(app, check) == ('ABC123', 1080, 'scheduled', 960)
    filed = admin_client.get('/admin/operations/kansas-tax?start=2026-07-01').get_data(as_text=True)
    assert 'Filed Oct 27, 2026' in filed
    assert 'numbers you submitted' in filed
    assert 'Payment scheduled for Oct 30, 2099' in filed


def test_reminders_go_out_once_and_stop_when_the_return_is_filed(app, seed):
    def make():
        today = date(2026, 10, 12)                                                            # 14 days before Oct 26
        first = _keys(K.due_reminders(today))
        mid = _keys(K.due_reminders(date(2026, 10, 15)))                                      # 11 days left: not a reminder day
        f = K.get_filing(date(2026, 7, 1), date(2026, 9, 30))
        f.reminders_sent = json.dumps(['return:14'])
        db.session.commit()
        again = _keys(K.due_reminders(today))
        f.reminders_sent = None
        f.return_filed_on = date(2026, 10, 12)
        db.session.commit()
        return first, mid, again, _keys(K.due_reminders(today))
    first, mid, again, filed = _in_db(app, make)
    assert first == ['return:14'] and mid == [] and again == [] and filed == []


def test_a_zero_quarter_is_still_reminded_and_overdue_shows_which_part_needs_attention(app, seed):
    def make():
        due = _keys(K.due_reminders(date(2026, 10, 24)))                                      # 2 days left, no sales at all
        f = K.get_filing(date(2026, 7, 1), date(2026, 9, 30))
        late = K.status_of(f, date(2026, 9, 30), date(2026, 10, 29))
        f.return_filed_on = date(2026, 10, 28)
        late_paid = K.status_of(f, date(2026, 9, 30), date(2026, 10, 29))
        return due, late['return_tone'], late['return_text'], late_paid['pay_text'], late_paid['pay_tone']
    due, tone, text, pay_text, pay_tone = _in_db(app, make)
    assert due == ['return:2']
    assert tone == 'bad' and text == 'Overdue by 3 days'
    assert pay_text == 'Payment outstanding' and pay_tone == 'bad'


def test_changing_the_pickup_rate_changes_what_checkout_charges(app, seed):
    def make():
        from utils import sales_tax
        sales_tax.clear_cache()
        before = sales_tax.rate_percent()
        K.save_jurisdiction('SHAJO', 'Shawnee / Johnson County', 9.6)
        return before, sales_tax.rate_percent()
    before, after = _in_db(app, make)
    assert before == 9.5 and after == 9.6
