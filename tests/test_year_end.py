"""Year-end: inventory count, mileage, the Stripe/PayPal check, and the CPA package zip."""
import io
import threading
import zipfile
from datetime import date, datetime

import pytest

from models import (ApparelInventory, Expense, InventoryCount, MileageTrip, Order, Payout, Supply, db)
from utils import cpa_package, year_end as Y
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
def _unthrottled():
    L._LAST_SYNC['at'] = 0.0
    yield
    L._LAST_SYNC['at'] = 0.0


def _paid_order(number='PMKC-Y1', source='stripe', day=datetime(2026, 3, 10, 18, 0)):
    o = Order(order_number=number, email='amy@example.com', subtotal=100.0, shipping_cost=0.0, tax=9.5, total=109.5,
              payment_status='paid', status='paid', payment_method=source, paid_at=day)
    db.session.add(o)
    db.session.commit()
    return o


# ---- inventory count ----

def test_count_copies_stock_and_values_at_cost(app, seed):
    def go():
        db.session.add(ApparelInventory(brand='Bella+Canvas', color='Black', size='M', quantity=10, cost_per_unit=4.25))
        db.session.add(ApparelInventory(brand='Bella+Canvas', color='Black', size='L', quantity=0, cost_per_unit=4.25))
        db.session.add(Supply(name='Poly mailers', category='packaging', quantity=100, cost_per_unit=0.15))
        db.session.commit()
        count = Y.start_count(2025)
        assert count.as_of == date(2025, 12, 31)
        assert Y.start_count(2025).id == count.id                      # starting twice does not duplicate
        by_kind, total = Y.count_totals(count)
        assert len(count.lines) == 2                                   # the zero-quantity row is left out
        assert by_kind['blanks'] == 4250 and by_kind['supplies'] == 1500 and total == 5750
    _in_db(app, go)


def test_count_edits_then_locks_for_good(app, seed):
    def go():
        count = Y.start_count(2025)
        line = Y.add_line(count, 'other', 'Display rack', 2, '30.00')
        Y.update_line(line.id, 3, '31.50')
        assert Y.count_totals(count)[1] == 9450
        with pytest.raises(ValueError):
            Y.add_line(count, 'other', '', 1, 1)                      # needs a description
        Y.lock_count(count)
        for attempt in (lambda: Y.update_line(line.id, 1, '1'), lambda: Y.delete_line(line.id),
                        lambda: Y.add_line(count, 'other', 'More', 1, 1)):
            with pytest.raises(ValueError):
                attempt()
        assert Y.count_totals(count)[1] == 9450
    _in_db(app, go)


# ---- mileage ----

def test_mileage_tenths_and_favorites(app, seed):
    def go():
        assert Y.to_tenths('12.5') == 125 and Y.to_tenths(0.24) == 2 and Y.miles_text(125) == '12.5'
        with pytest.raises(ValueError):
            Y.to_tenths(0)
        Y.add_trip(date(2026, 2, 1), 'Home', 'Post office', 'Shipping', '3.2')
        fav = Y.add_favorite('Supplier run', 'Home', 'Supplier', 'Pick up blanks', '18.6')
        trip = Y.log_favorite(fav.id, date(2026, 2, 5))
        assert trip.miles_tenths == 186 and trip.purpose == 'Pick up blanks'
        Y.add_trip(date(2025, 12, 30), None, None, None, 4)
        assert sum(t.miles_tenths for t in Y.trips_in_year(2026)) == 32 + 186
        with pytest.raises(ValueError):
            Y.add_favorite('  ', None, None, None, 1)
    _in_db(app, go)


# ---- Stripe and PayPal against payouts ----

def test_processor_summary_nets_fees_refunds_and_payouts(app, seed):
    def go():
        o = _paid_order()
        o.processing_fee = 3.5
        o.processing_fee_is_actual = True
        db.session.commit()
        L.sync_all(force=True)
        summary = Y.processor_summary(2026)
        mar = summary['stripe']['rows'][2]
        assert mar['in'] == 10950 and mar['fees'] == -350 and mar['expected'] == 10600
        assert summary['stripe']['totals']['balance'] == 10600
        assert summary['paypal']['totals']['in'] == 0
    _in_db(app, go)


# ---- the checklist ----

def test_checks_flag_missing_receipts_and_uncounted_inventory(app, seed):
    def go():
        L.add_expense(when_day=date(2026, 4, 1), vendor='Shop', amount_dollars='20', category='Supplies')
        texts = [t for _lvl, t, _ep in Y.package_checks(2026)]
        assert any('1 of 1 expenses have no receipt' in t for t in texts)
        assert any('no 2026 inventory count' in t for t in texts)
        Y.lock_count(Y.start_count(2026))
        texts = [t for _lvl, t, _ep in Y.package_checks(2026)]
        assert any('2026 inventory count is locked' in t for t in texts)
    _in_db(app, go)


# ---- the package ----

def test_package_has_every_file_and_ties_to_the_books(app, seed, tmp_path):
    def go():
        _paid_order()
        receipt = tmp_path / 'r.png'
        receipt.write_bytes(b'\x89PNG fake receipt')
        app.static_folder = str(tmp_path)
        L.add_expense(when_day=date(2026, 5, 2), vendor='Heat Press Co', amount_dollars='250', category='Supplies',
                      receipt_url='/static/r.png', is_equipment=True)
        L.add_expense(when_day=date(2026, 5, 3), vendor='No Receipt Shop', amount_dollars='12.5', category='Office expense')
        Y.add_trip(date(2026, 6, 1), 'Home', 'Post office', 'Shipping', '5.5')
        Y.lock_count(Y.start_count(2026))
        L.sync_all(force=True)
        return cpa_package.build_package(2026, app)
    data = _in_db(app, go)
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    for prefix in ('01-Summary-Letter-2026.pdf', '02-Profit-and-Loss-2026.pdf', '03-Monthly-Profit-and-Loss-2026.pdf',
                   '04-Sales-Tax-2026.pdf', '04-Sales-Tax-2026.csv', '05-General-Ledger-2026.csv', '06-Sales-Detail-2026.csv',
                   '07-Expenses-2026.csv', '08-Equipment-2026.csv', '09-Mileage-2026.csv', '10-Inventory-Count-2026.csv',
                   '11-Stripe-and-PayPal-Summary-2026.csv', '12-Payouts-2026.csv', '13-Open-Invoices.csv',
                   '14-Owner-Contributions-and-Draws-2026.csv', 'README.txt', 'MISSING-RECEIPTS.txt'):
        assert prefix in names, prefix
    assert zf.read('01-Summary-Letter-2026.pdf').startswith(b'%PDF')
    assert 'receipts/2026-05-02_heat-press-co_250.00.png' in names
    assert zf.read('receipts/2026-05-02_heat-press-co_250.00.png') == b'\x89PNG fake receipt'
    assert 'No Receipt Shop' in zf.read('MISSING-RECEIPTS.txt').decode()
    expenses = zf.read('07-Expenses-2026.csv').decode('utf-8-sig')
    assert 'Heat Press Co' in expenses and '250.00' in expenses and 'receipts/2026-05-02' in expenses
    assert 'Heat Press Co' in zf.read('08-Equipment-2026.csv').decode('utf-8-sig')
    assert '5.5' in zf.read('09-Mileage-2026.csv').decode('utf-8-sig')
    assert 'PMKC-Y1' in zf.read('06-Sales-Detail-2026.csv').decode('utf-8-sig')
    assert 'PMKC-Y1' in zf.read('05-General-Ledger-2026.csv').decode('utf-8-sig')


def test_package_for_an_empty_year_still_builds(app, seed):
    data = _in_db(app, lambda: cpa_package.build_package(2019, app))
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert '01-Summary-Letter-2019.pdf' in names and 'README.txt' in names and '10-Inventory-Count-2019.csv' not in names


# ---- pages and access ----

def test_year_end_pages_need_admin(guest):
    for path in ('/admin/operations/cpa-package', '/admin/operations/inventory-count', '/admin/operations/mileage',
                 '/admin/operations/payout-check', '/admin/operations/cpa-package.zip'):
        resp = guest.get(path)
        assert resp.status_code in (301, 302, 303, 401, 403, 404), path


def test_year_end_pages_and_download_for_admin(admin_client):
    for path in ('/admin/operations/inventory-count?year=2026', '/admin/operations/mileage', '/admin/operations/payout-check',
                 '/admin/operations/cpa-package?year=2026'):
        assert admin_client.get(path).status_code == 200, path
    resp = admin_client.get('/admin/operations/cpa-package.zip?year=2026')
    assert resp.status_code == 200 and resp.mimetype == 'application/zip'
    assert zipfile.ZipFile(io.BytesIO(resp.data)).testzip() is None
