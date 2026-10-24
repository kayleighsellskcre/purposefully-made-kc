"""The books: ledger, cash basis, Kansas City days, profit and loss, expenses, owner money, PDFs."""
import io
import json
import re
import threading
from datetime import date, datetime

import pytest

from models import Expense, FinancialEntry, LedgerEntry, ManualInvoice, Order, db
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
    return out.get('value')


@pytest.fixture(autouse=True)
def _books_unthrottled():
    L._LAST_SYNC['at'] = 0.0
    yield
    L._LAST_SYNC['at'] = 0.0


def _order(number='PMKC-B1', **kw):
    defaults = dict(email='amy@example.com', subtotal=100.0, shipping_cost=11.0, tax=9.5, total=120.5,
                    payment_status='paid', status='paid', payment_method='stripe',
                    paid_at=datetime(2026, 10, 15, 18, 0))
    defaults.update(kw)
    o = Order(order_number=number, **defaults)
    db.session.add(o)
    db.session.flush()
    return o


def _sum(entry_type, **filters):
    q = db.session.query(db.func.coalesce(db.func.sum(LedgerEntry.amount_cents), 0)).filter(LedgerEntry.entry_type == entry_type)
    for k, v in filters.items():
        q = q.filter(getattr(LedgerEntry, k) == v)
    return int(q.scalar())


# ---- money and periods ----

def test_cents_are_exact_and_round_half_up():
    assert L.to_cents(0.1 + 0.2) == 30 and L.to_cents('19.995') == 2000 and L.to_cents(None) == 0 and L.to_cents(1234.5) == 123450
    assert L.dollars(123456) == '$1,234.56' and L.dollars(-500) == '-$5.00' and L.dollars(0) == '$0.00'


def test_periods_in_kansas_city_days():
    today = date(2026, 1, 20)
    assert L.resolve_period('this_month', today=today)[:2] == (date(2026, 1, 1), date(2026, 1, 31))
    assert L.resolve_period('last_month', today=today)[:2] == (date(2025, 12, 1), date(2025, 12, 31))
    assert L.resolve_period('q2', year=2026, today=today)[:2] == (date(2026, 4, 1), date(2026, 6, 30))
    assert L.resolve_period('q4', year=2026, today=today)[2] == 'Q4 2026'
    assert L.resolve_period('ytd', today=today)[:2] == (date(2026, 1, 1), today)
    assert L.resolve_period('last_year', today=today)[:2] == (date(2025, 1, 1), date(2025, 12, 31))
    assert L.resolve_period('custom', start=date(2026, 3, 9), end=date(2026, 3, 2), today=today)[:2] == (date(2026, 3, 2), date(2026, 3, 9))
    assert L.resolve_period('this_month', today=date(2024, 2, 10))[1] == date(2024, 2, 29)         # leap year


def test_a_late_sale_lands_on_the_right_kansas_city_day_and_year(app, seed):
    def go():
        # 3:30 AM UTC on Jan 1 is 9:30 PM on Dec 31 in Kansas City
        _order(paid_at=datetime(2026, 1, 1, 3, 30))
        db.session.commit()
        L.sync_all(force=True)
        day = LedgerEntry.query.filter_by(entry_type=L.SALE).first().kc_date
        return day, L.pnl(date(2025, 1, 1), date(2025, 12, 31))['sales'], L.pnl(date(2026, 1, 1), date(2026, 12, 31))['sales']
    day, in_2025, in_2026 = _in_db(app, go)
    assert day == date(2025, 12, 31) and in_2025 == 10000 and in_2026 == 0


# ---- orders into the ledger ----

def test_a_paid_order_writes_every_line_once(app, seed):
    def go():
        _order(processing_fee=3.75, processing_fee_is_actual=False, cost_of_goods=40.0, cogs_is_actual=True)
        _order('PMKC-B2', payment_status='pending', status='new')                       # unpaid: nothing yet
        db.session.commit()
        first = L.sync_all(force=True)
        second = L.sync_all(force=True)
        return (first, second, _sum(L.SALE), _sum(L.SHIPPING), _sum(L.TAX), _sum(L.FEE), _sum(L.COGS),
                LedgerEntry.query.filter_by(entry_type=L.FEE).first().is_estimate,
                LedgerEntry.query.filter_by(entry_type=L.COGS).first().is_estimate)
    first, second, sale, ship, tax, fee, cogs, fee_est, cogs_est = _in_db(app, go)
    assert (first, second) == (5, 0)                                                    # sale, shipping, tax, fee, cogs
    assert (sale, ship, tax, fee, cogs) == (10000, 1100, 950, -375, -4000)
    assert fee_est is True and cogs_est is False


def test_a_real_fee_arrives_as_an_adjustment_not_an_edit(app, seed):
    def go():
        o = _order(processing_fee=3.75, processing_fee_is_actual=False)
        db.session.commit()
        L.sync_all(force=True)
        original = LedgerEntry.query.filter_by(entry_type=L.FEE).first()
        original_id, original_cents = original.id, original.amount_cents
        o.processing_fee, o.processing_fee_is_actual = 3.62, True
        db.session.commit()
        L.sync_all(force=True)
        rows = LedgerEntry.query.filter_by(entry_type=L.FEE).order_by(LedgerEntry.id).all()
        return original_id, original_cents, [(r.id, r.amount_cents, r.note) for r in rows], _sum(L.FEE)
    original_id, original_cents, rows, total = _in_db(app, go)
    assert original_cents == -375 and rows[0][:2] == (original_id, -375)               # the first entry is untouched
    assert len(rows) == 2 and rows[1][1] == 13 and 'Adjustment' in rows[1][2] and total == -362


def test_a_refund_takes_back_the_sale_and_the_tax(app, seed):
    def go():
        o = _order()
        db.session.commit()
        L.sync_all(force=True)
        o.is_refunded, o.payment_status = True, 'refunded'
        db.session.commit()
        L.sync_all(force=True)
        p = L.pnl(date(2026, 10, 1), date(2026, 10, 31))
        return p['refunds'], p['net_sales'], p['tax_collected']
    refunds, net_sales, tax = _in_db(app, go)
    assert (refunds, net_sales, tax) == (-11100, 0, 0)


def test_unpaid_and_cancelled_orders_never_count(app, seed):
    def go():
        _order('PMKC-B3', payment_status='pending', status='new')
        _order('PMKC-B4', payment_status='failed', status='cancelled')
        db.session.commit()
        return L.sync_all(force=True), LedgerEntry.query.count()
    assert _in_db(app, go) == (0, 0)


def test_channels_follow_how_the_order_was_paid(app, seed):
    def go():
        _order('PMKC-C1', payment_method='cash')
        _order('PMKC-C2', payment_method='company_invoice')
        _order('PMKC-C3', collection_id=seed['collection_id'])
        db.session.commit()
        L.sync_all(force=True)
        return dict(L.sales_by_channel(date(2026, 10, 1), date(2026, 10, 31)))
    got = _in_db(app, go)
    assert set(got) == {'Cash at pickup', 'Company orders', 'Group orders'} and all(v == 11100 for v in got.values())


# ---- invoices: cash basis ----

def _invoice(**kw):
    inv = ManualInvoice(number=kw.pop('number', 'INV-2026-0001'), customer_name='Amy', email='a@example.com',
                        items_json=json.dumps([{'description': 'Tees', 'qty': 10, 'unit': 20.0}]), tax_rate=10.0,
                        shipping=0, discount=0, amount_paid=kw.pop('amount_paid', 0), payment_method='Venmo', **kw)
    db.session.add(inv)
    db.session.flush()
    return inv


def test_invoices_count_only_as_they_are_paid(app, seed):
    def go():
        inv = _invoice()                                    # $200 plus $20 tax = $220, nothing paid
        db.session.commit()
        none_yet = L.sync_all(force=True)
        inv.amount_paid = 110.0                             # half paid
        db.session.commit()
        L.sync_all(force=True)
        half = (_sum(L.SALE), _sum(L.TAX))
        inv.amount_paid = 220.0                             # the rest arrives
        db.session.commit()
        L.sync_all(force=True)
        return none_yet, half, (_sum(L.SALE), _sum(L.TAX)), inv.paid_at is not None
    none_yet, half, full, has_date = _in_db(app, go)
    assert none_yet == 0 and half == (10000, 1000) and full == (20000, 2000) and has_date


def test_invoice_discount_and_shipping_add_up_to_what_was_paid(app, seed):
    def go():
        inv = _invoice(amount_paid=0)
        inv.shipping, inv.discount = 15.0, 20.0
        db.session.commit()
        from utils.receipts import doc_from_invoice
        total = doc_from_invoice(inv)['total']
        inv.amount_paid = total
        db.session.commit()
        L.sync_all(force=True)
        total_in = sum(r.amount_cents for r in LedgerEntry.query.filter(LedgerEntry.invoice_id == inv.id).all())
        return total_in, L.to_cents(total), _sum(L.DISCOUNT)
    total_in, total_cents, discount = _in_db(app, go)
    assert total_in == total_cents and discount == -2000


# ---- profit and loss ----

def test_profit_and_loss_adds_up(app, seed):
    def go():
        _order(processing_fee=3.75, cost_of_goods=40.0, cogs_is_actual=True)
        db.session.commit()
        L.sync_all(force=True)
        L.add_expense(when_day=date(2026, 10, 20), vendor='Adobe', amount_dollars='25.00', category='Software and subscriptions')
        L.add_expense(when_day=date(2026, 10, 21), vendor='Stripe monthly', amount_dollars='1.00', category=L.FEE_CATEGORY)
        return L.pnl(date(2026, 10, 1), date(2026, 10, 31))
    p = _in_db(app, go)
    assert p['gross_sales'] == 11100 and p['net_sales'] == 11100 and p['cogs'] == 4000 and p['gross_profit'] == 7100
    assert dict(p['expenses']) == {'Software and subscriptions': 2500, L.FEE_CATEGORY: 475}      # fees and manual fees together
    assert p['total_expenses'] == 2975 and p['net_profit'] == 7100 - 2975
    assert p['tax_collected'] == 950                                                           # reported apart from income


def test_other_months_stay_out_of_the_period(app, seed):
    def go():
        _order(paid_at=datetime(2026, 9, 30, 20, 0))                     # September
        db.session.commit()
        L.sync_all(force=True)
        return L.pnl(date(2026, 10, 1), date(2026, 10, 31))['net_sales'], L.pnl(date(2026, 9, 1), date(2026, 9, 30))['net_sales']
    assert _in_db(app, go) == (0, 11100)


def test_monthly_view_has_twelve_months_in_order(app, seed):
    def go():
        _order(paid_at=datetime(2026, 3, 5, 18, 0))
        db.session.commit()
        L.sync_all(force=True)
        return [(m, p['net_sales']) for m, p in L.monthly(2026)]
    months = _in_db(app, go)
    assert [m for m, _v in months] == ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    assert dict(months)['Mar'] == 11100 and sum(v for _m, v in months) == 11100


# ---- expenses and owner money ----

def test_expenses_and_voids_keep_the_trail(app, seed):
    def go():
        exp = L.add_expense(when_day=date(2026, 5, 2), vendor='Heat press', amount_dollars='499.99', category='Supplies',
                            is_equipment=True, payment_method='Card')
        before = L.pnl(date(2026, 5, 1), date(2026, 5, 31))['total_expenses']
        L.void_expense(exp.id)
        after = L.pnl(date(2026, 5, 1), date(2026, 5, 31))['total_expenses']
        # the voiding is dated today, so the original month still shows it and today's month shows the reversal
        rows = LedgerEntry.query.filter_by(expense_id=exp.id).order_by(LedgerEntry.id).all()
        return before, after, [r.amount_cents for r in rows], db.session.get(Expense, exp.id).voided_at is not None, exp.is_equipment
    before, after, rows, voided, equipment = _in_db(app, go)
    assert before == 49999 and rows == [-49999, 49999] and sum(rows) == 0 and voided and equipment
    assert after == 49999                                                  # history is not rewritten


def test_bad_expenses_are_refused(app, seed):
    def go():
        problems = []
        for kw in ({'amount_dollars': '0', 'category': 'Supplies'}, {'amount_dollars': '5', 'category': 'Nonsense'}):
            try:
                L.add_expense(when_day=date(2026, 5, 2), vendor='x', **kw)
            except ValueError as exc:
                problems.append(str(exc))
        return problems, LedgerEntry.query.count()
    problems, count = _in_db(app, go)
    assert len(problems) == 2 and count == 0


def test_owner_money_stays_out_of_profit(app, seed):
    def go():
        L.add_owner_entry(L.DRAW, when_day=date(2026, 6, 3), amount_dollars='300', note='Paycheck')
        L.add_owner_entry(L.CONTRIBUTION, when_day=date(2026, 6, 4), amount_dollars='1000')
        return L.pnl(date(2026, 6, 1), date(2026, 6, 30))
    p = _in_db(app, go)
    assert p['draws'] == 30000 and p['contributions'] == 100000 and p['net_profit'] == 0 and p['total_expenses'] == 0


def test_old_financial_entries_come_in_once_and_are_left_alone(app, seed):
    def go():
        o = _order('PMKC-L0', cost_of_goods=10.0, cogs_is_actual=True)
        db.session.add_all([
            FinancialEntry(category='revenue', amount=200.0, description='Craft fair', entry_date=datetime(2026, 4, 5, 18, 0)),
            FinancialEntry(category='advertising', amount=50.0, description='Flyers', entry_date=datetime(2026, 4, 6, 18, 0)),
            FinancialEntry(category='equipment', amount=80.0, description='Cutter', entry_date=datetime(2026, 4, 7, 18, 0)),
            FinancialEntry(category='cogs', amount=999.0, description='Already in the order', order_id=o.id,
                           entry_date=datetime(2026, 4, 8, 18, 0)),
        ])
        db.session.commit()
        L.sync_all(force=True)
        L.sync_all(force=True)
        p = L.pnl(date(2026, 4, 1), date(2026, 4, 30))
        return dict(p['expenses']), p['other_income'], FinancialEntry.query.count(), LedgerEntry.query.filter(LedgerEntry.source_key.like('legacy:%')).count()
    expenses, other, originals, imported = _in_db(app, go)
    assert expenses == {'Advertising': 5000, 'Supplies': 8000} and other == 20000
    assert originals == 4 and imported == 3                               # the order-linked one is not double counted


# ---- pages and PDFs ----

def _pages(pdf):
    return len(re.findall(rb'/Type\s*/Page(?!s)', pdf))


def test_reports_page_shows_the_numbers_with_click_through(admin_client, app, seed):
    _in_db(app, lambda: (_order(processing_fee=3.75, cost_of_goods=40.0), db.session.commit()))
    html = admin_client.get('/admin/operations/reports?period=custom&from=2026-10-01&to=2026-10-31').get_data(as_text=True)
    assert 'Profit and loss' in html and '$111.00' in html and 'Net profit' in html
    assert '/admin/operations/ledger?' in html and 'type=sale,shipping' in html
    assert 'Q1' in html and 'Last month' in html and 'Year to date' in html
    assert 'estimated processing fee' in html                               # the heads-up about estimates


def test_ledger_page_filters_and_downloads_csv(admin_client, app, seed):
    _in_db(app, lambda: (_order(processing_fee=3.75), db.session.commit()))
    page = admin_client.get('/admin/operations/ledger?type=processing_fee').get_data(as_text=True)
    assert 'Processing fees' in page and '-$3.75' in page and 'PMKC-B1' in page and 'Sales tax collected</td>' not in page
    csv_resp = admin_client.get('/admin/operations/ledger?format=csv&type=sales_tax')
    assert csv_resp.mimetype == 'text/csv' and '9.50' in csv_resp.get_data(as_text=True)


def test_expense_form_saves_with_a_receipt(admin_client, app, seed, monkeypatch):
    import utils.cloud_storage as cs
    monkeypatch.setattr(cs, 'store_upload', lambda f, sub, prefix: f'https://cdn.example/{sub}/{f.filename}')
    resp = admin_client.post('/admin/operations/expenses', data={
        'action': 'expense', 'day': '2026-10-10', 'amount': '42.50', 'vendor': 'Staples', 'category': 'Office expense',
        'payment_method': 'Card', 'receipt': (io.BytesIO(b'%PDF-1.4 fake'), 'receipt.pdf')}, content_type='multipart/form-data')
    assert resp.status_code == 302
    page = admin_client.get('/admin/operations/expenses?year=2026').get_data(as_text=True)
    assert 'Staples' in page and '$42.50' in page and 'https://cdn.example/receipts/receipt.pdf' in page
    admin_client.post('/admin/operations/expenses', data={'action': 'expense', 'day': '2026-10-11', 'amount': '5', 'vendor': 'No receipt', 'category': 'Supplies'})
    assert '1 without a receipt' in admin_client.get('/admin/operations/expenses?year=2026').get_data(as_text=True)
    bad = admin_client.post('/admin/operations/expenses', data={'action': 'expense', 'amount': '9', 'category': 'Nonsense'}, follow_redirects=True)
    assert 'Choose a category' in bad.get_data(as_text=True)


def test_report_pdfs_are_one_page_and_monthly_is_landscape(admin_client, app, seed):
    _in_db(app, lambda: (_order(processing_fee=3.75, cost_of_goods=40.0), db.session.commit()))
    pnl = admin_client.get('/admin/operations/reports/pnl.pdf?period=custom&from=2026-10-01&to=2026-10-31')
    assert pnl.mimetype == 'application/pdf' and pnl.data.startswith(b'%PDF') and _pages(pnl.data) == 1
    monthly = admin_client.get('/admin/operations/reports/monthly.pdf?year=2026')
    assert monthly.data.startswith(b'%PDF') and _pages(monthly.data) == 1 and re.search(rb'/MediaBox\s*\[\s*0\s+0\s+792', monthly.data)


def test_books_pages_are_admin_only(guest, seed):
    for url in ('/admin/operations/reports', '/admin/operations/ledger', '/admin/operations/expenses',
                '/admin/operations/reports/pnl.pdf', '/admin/operations/reports/monthly.pdf'):
        assert guest.get(url).status_code in (302, 401, 403, 404), url


def test_financial_page_calls_gross_profit_what_it_is(admin_client, seed):
    html = admin_client.get('/admin/operations/financial').get_data(as_text=True)
    assert 'Gross profit' in html and 'True Profit' not in html and '/admin/operations/reports' in html
