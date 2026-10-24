"""The year-end CPA package: one zip with every report, the ledger behind it, and every receipt.

Everything is built from the ledger and the records already in the site, so the package always matches the Reports
page. Nothing in it is edited or invented. A receipt that cannot be fetched is listed in MISSING-RECEIPTS.txt.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from datetime import date

from sqlalchemy.orm import joinedload

from models import Expense, LedgerEntry, Payout, db
from utils import ledger as L
from utils import year_end as Y

RECEIPT_MAX_FILES = 300
RECEIPT_MAX_BYTES = 15 * 1024 * 1024
RECEIPT_TOTAL_BYTES = 150 * 1024 * 1024


def _csv(header, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')        # the marker lets Excel open it cleanly


def _money(cents):
    return f'{int(cents or 0) / 100:.2f}'


def _slug(text, limit=40):
    return (re.sub(r'[^a-z0-9]+', '-', (text or 'receipt').lower()).strip('-') or 'receipt')[:limit]


def read_receipt(url, app):
    """The bytes of a stored receipt (from the cloud bucket or the local uploads folder), or None."""
    if not url:
        return None
    try:
        if url.startswith(('http://', 'https://')):
            import requests
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            return resp.content if len(resp.content) <= RECEIPT_MAX_BYTES else None
        rel = url.split('?')[0].lstrip('/')
        rel = rel[len('static/'):] if rel.startswith('static/') else rel
        path = os.path.join(app.static_folder, *rel.split('/'))
        if os.path.isfile(path) and os.path.getsize(path) <= RECEIPT_MAX_BYTES:
            with open(path, 'rb') as fh:
                return fh.read()
    except Exception:
        app.logger.warning('receipt could not be fetched for the CPA package: %s', url)
    return None


def _ext(url):
    ext = os.path.splitext((url or '').split('?')[0])[1].lower()
    return ext if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.pdf') else '.jpg'


def _year_bounds(year):
    return date(year, 1, 1), date(year, 12, 31)


def ledger_csv(year):
    first, last = _year_bounds(year)
    rows = []
    for e in (LedgerEntry.query.options(joinedload(LedgerEntry.order), joinedload(LedgerEntry.invoice))
              .filter(LedgerEntry.kc_date >= first, LedgerEntry.kc_date <= last).order_by(LedgerEntry.kc_date, LedgerEntry.id).all()):
        rows.append([e.kc_date.isoformat(), L.TYPE_LABELS.get(e.entry_type, e.entry_type), e.category or '', _money(e.amount_cents),
                     e.pay_source or '', e.channel or '', e.jurisdiction or '', e.order.order_number if e.order else '',
                     e.invoice.number if e.invoice else '', e.vendor or '', 'yes' if e.is_estimate else '', e.note or ''])
    return _csv(['Date', 'Type', 'Category', 'Amount', 'Paid through', 'Channel', 'Where taxed', 'Order', 'Invoice', 'Vendor',
                 'Estimate', 'Note'], rows)


def sales_detail_csv(year):
    """One line per order or invoice that had money move in the year."""
    first, last = _year_bounds(year)
    groups = {}
    entries = (LedgerEntry.query.options(joinedload(LedgerEntry.order), joinedload(LedgerEntry.invoice))
               .filter(LedgerEntry.kc_date >= first, LedgerEntry.kc_date <= last,
                       db.or_(LedgerEntry.source_key.like('order:%'), LedgerEntry.source_key.like('invoice:%')))
               .order_by(LedgerEntry.kc_date, LedgerEntry.id).all())
    for e in entries:
        g = groups.setdefault(e.source_key, {'date': e.kc_date, 'ref': e.order.order_number if e.order else (e.invoice.number if e.invoice else e.source_key),
                                             'channel': e.channel or '', 'where': e.jurisdiction or '', 'sale': 0, 'discount': 0, 'ship': 0,
                                             'tax': 0, 'refund': 0, 'fee': 0, 'cogs': 0})
        if e.entry_type == L.SALE:
            g['sale'] += e.amount_cents
        elif e.entry_type == L.DISCOUNT:
            g['discount'] += e.amount_cents
        elif e.entry_type == L.SHIPPING:
            g['ship'] += e.amount_cents
        elif e.entry_type == L.TAX:
            g['tax'] += e.amount_cents
        elif e.entry_type in (L.REFUND, L.REFUND_TAX):
            g['refund'] += e.amount_cents
        elif e.entry_type == L.FEE:
            g['fee'] += e.amount_cents
        elif e.entry_type == L.COGS:
            g['cogs'] += e.amount_cents
    rows = [[g['date'].isoformat(), g['ref'], g['channel'], g['where'], _money(g['sale']), _money(g['discount']), _money(g['ship']),
             _money(g['tax']), _money(g['refund']), _money(g['fee']), _money(g['cogs'])] for g in groups.values()]
    return _csv(['Date', 'Order or invoice', 'Channel', 'Where taxed', 'Sales', 'Discounts', 'Shipping charged', 'Sales tax collected',
                 'Refunds', 'Processing fee', 'Cost of goods'], rows)


def build_package(year, app):
    """The zip as bytes."""
    from utils.business_info import BUSINESS
    from utils import sales_tax
    from utils.report_pdf import (build_monthly_pdf, build_pnl_pdf, build_sales_tax_pdf, build_summary_letter_pdf)
    year = int(year)
    first, last = _year_bounds(year)
    p = L.pnl(first, last)
    report = L.sales_tax_report(first, last)
    checks = Y.package_checks(year)
    processors = Y.processor_summary(year)
    count = Y.count_for(year)
    open_rows = Y.open_invoice_rows()
    trips = Y.trips_in_year(year)

    files = {}
    expenses = (Expense.query.filter(Expense.expense_date >= first, Expense.expense_date <= last)
                .order_by(Expense.expense_date, Expense.id).all())

    # receipts: named by date, vendor and amount
    receipt_names, missing, taken, total_bytes = {}, [], set(), 0
    for exp in expenses:
        if exp.voided_at:
            continue
        data = read_receipt(exp.receipt_url, app) if len(receipt_names) < RECEIPT_MAX_FILES else None
        if data is None or total_bytes + len(data) > RECEIPT_TOTAL_BYTES:
            missing.append(f"{exp.expense_date.isoformat()}  {exp.vendor or 'no vendor'}  ${exp.amount_cents / 100:.2f}  "
                           f"{'receipt file could not be fetched' if exp.receipt_url else 'no receipt attached'}")
            continue
        base = f"receipts/{exp.expense_date.isoformat()}_{_slug(exp.vendor)}_{exp.amount_cents / 100:.2f}"
        name, n = base + _ext(exp.receipt_url), 1
        while name in taken:
            n += 1
            name = f'{base}-{n}{_ext(exp.receipt_url)}'
        taken.add(name)
        files[name] = data
        receipt_names[exp.id] = name
        total_bytes += len(data)

    expense_lines = [(name, L.EXPENSE_LINE.get(name, ''), cents) for name, cents in p['expenses']]
    stripe_gross, paypal_gross = processors['stripe']['totals']['in'], processors['paypal']['totals']['in']
    extras = {'inventory_cents': Y.count_totals(count)[1] if count else None, 'stripe_gross': stripe_gross, 'paypal_gross': paypal_gross,
              'open_count': len(open_rows), 'open_cents': sum(r['balance_cents'] for r in open_rows),
              'miles': Y.miles_text(sum(t.miles_tenths for t in trips))}
    flags = [(level, text) for level, text, _endpoint in checks]

    files[f'01-Summary-Letter-{year}.pdf'] = build_summary_letter_pdf(year, p, extras, flags, BUSINESS, expense_lines)
    files[f'02-Profit-and-Loss-{year}.pdf'] = build_pnl_pdf(p, str(year), BUSINESS, channels=L.sales_by_channel(first, last),
                                                            estimates=L.estimate_counts())
    files[f'03-Monthly-Profit-and-Loss-{year}.pdf'] = build_monthly_pdf(year, L.monthly(year), BUSINESS)
    files[f'04-Sales-Tax-{year}.pdf'] = build_sales_tax_pdf(report, str(year), BUSINESS, sales_tax.rate_percent())
    tax_rows = [[r['label'], r['orders'], _money(r['taxable']), _money(r['not_taxed']), _money(r['shipping']), _money(r['tax'])]
                for r in report['rows']]
    t = report['totals']
    tax_rows.append(['Total', t['orders'], _money(t['taxable']), _money(t['not_taxed']), _money(t['shipping']), _money(t['tax'])])
    files[f'04-Sales-Tax-{year}.csv'] = _csv(['Where taxed', 'Orders', 'Taxable sales', 'Not taxed', 'Shipping charged', 'Tax collected'], tax_rows)
    files[f'05-General-Ledger-{year}.csv'] = ledger_csv(year)
    files[f'06-Sales-Detail-{year}.csv'] = sales_detail_csv(year)
    files[f'07-Expenses-{year}.csv'] = _csv(
        ['Date', 'Vendor', 'Category', 'Schedule C line (confirm)', 'Amount', 'Paid with', 'Equipment', 'Voided', 'Receipt file', 'Note'],
        [[e.expense_date.isoformat(), e.vendor or '', e.category, L.EXPENSE_LINE.get(e.category, ''), _money(e.amount_cents),
          e.payment_method or '', 'yes' if e.is_equipment else '', 'yes' if e.voided_at else '', receipt_names.get(e.id, ''), e.note or '']
         for e in expenses])
    files[f'08-Equipment-{year}.csv'] = _csv(
        ['Date', 'Item', 'Cost', 'Paid with', 'Receipt file'],
        [[e.expense_date.isoformat(), e.vendor or e.note or '', _money(e.amount_cents), e.payment_method or '', receipt_names.get(e.id, '')]
         for e in expenses if e.is_equipment and not e.voided_at])
    files[f'09-Mileage-{year}.csv'] = _csv(
        ['Date', 'From', 'To', 'Why', 'Miles'],
        [[tr.trip_date.isoformat(), tr.start or '', tr.destination or '', tr.purpose or '', Y.miles_text(tr.miles_tenths)] for tr in trips]
        + [['Total', '', '', '', Y.miles_text(sum(tr.miles_tenths for tr in trips))]])
    if count:
        by_kind, total = Y.count_totals(count)
        files[f'10-Inventory-Count-{year}.csv'] = _csv(
            ['Type', 'Description', 'Quantity', 'Unit cost', 'Value at cost'],
            [[Y.KIND_LABELS.get(ln.kind, ln.kind), ln.description, ln.quantity, _money(ln.unit_cost_cents), _money(ln.value_cents)]
             for ln in count.lines] + [['Total at cost', f"as of {count.as_of.isoformat()}" + (' (locked)' if count.locked_at else ' (not locked)'),
                                        '', '', _money(total)]])
    proc_rows = []
    for key, name in (('stripe', 'Stripe'), ('paypal', 'PayPal')):
        for r in processors[key]['rows']:
            proc_rows.append([name, f"{r['month']} {year}", _money(r['in']), _money(r['refunds']), _money(r['fees']),
                              _money(r['expected']), _money(r['paid_out']), _money(r['balance'])])
        tt = processors[key]['totals']
        proc_rows.append([name, f'{year} total (1099-K gross is the money in)', _money(tt['in']), _money(tt['refunds']), _money(tt['fees']),
                          _money(tt['expected']), _money(tt['paid_out']), _money(tt['balance'])])
    files[f'11-Stripe-and-PayPal-Summary-{year}.csv'] = _csv(
        ['Processor', 'Month', 'Money in (gross)', 'Refunds', 'Fees', 'Should be left', 'Paid out', 'Still owed to you'], proc_rows)
    payouts = (Payout.query.filter(Payout.arrival_date >= first, Payout.arrival_date <= last).order_by(Payout.arrival_date).all())
    files[f'12-Payouts-{year}.csv'] = _csv(['Arrives', 'From', 'Status', 'Amount', 'Reference'],
                                           [[pp.arrival_date.isoformat() if pp.arrival_date else '', pp.provider, pp.status or '',
                                             _money(pp.amount_cents), pp.provider_id] for pp in payouts])
    files['13-Open-Invoices.csv'] = _csv(['Invoice', 'Customer', 'Issued', 'Total', 'Paid so far', 'Balance'],
                                         [[r['number'], r['customer'], r['issued'].date().isoformat() if r['issued'] else '',
                                           _money(r['total_cents']), _money(r['paid_cents']), _money(r['balance_cents'])] for r in open_rows])
    owner = (LedgerEntry.query.filter(LedgerEntry.kc_date >= first, LedgerEntry.kc_date <= last,
                                      LedgerEntry.entry_type.in_([L.CONTRIBUTION, L.DRAW])).order_by(LedgerEntry.kc_date, LedgerEntry.id).all())
    files[f'14-Owner-Contributions-and-Draws-{year}.csv'] = _csv(
        ['Date', 'Type', 'Amount', 'Note'], [[e.kc_date.isoformat(), L.TYPE_LABELS.get(e.entry_type, ''), _money(e.amount_cents), e.note or ''] for e in owner])
    if missing:
        files['MISSING-RECEIPTS.txt'] = ('These expenses have no receipt in this package:\n\n' + '\n'.join(missing) + '\n').encode('utf-8')
    files['README.txt'] = _readme(year, bool(count), len(receipt_names), len(missing)).encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    return buf.getvalue()


def _readme(year, has_count, receipts, missing):
    return f'''PURPOSEFULLY MADE KC: {year} CPA PACKAGE

Start with 01-Summary-Letter. It has the key totals and anything that needs a look.

How the books are kept
  Cash basis. Money counts on the day it was received. Dates and months use Kansas City time.
  Nothing is edited or deleted. A correction is a new dated entry (see the ledger).
  DTF transfers are cost of goods. Equipment is recorded as supplies. Inventory is valued at cost.
  Sales tax collected is shown apart from income. Processing fees are an expense (Commissions and fees).

Files
  01  Summary letter (PDF)
  02  Profit and loss for the year (PDF)
  03  Profit and loss by month (PDF)
  04  Sales tax by where each sale was taxed (PDF and CSV)
  05  General ledger: every money event (CSV)
  06  Sales detail by order and invoice (CSV)
  07  Expenses by category with the Schedule C line to confirm (CSV)
  receipts/  {receipts} receipt files named date_vendor_amount{f"  ({missing} expenses have none, see MISSING-RECEIPTS.txt)" if missing else ""}
  08  Equipment purchases (CSV)
  09  Mileage log (CSV). Apply the standard mileage rate to the total.
  10  Inventory count at year end, valued at cost (CSV){"" if has_count else "  NOT INCLUDED: no count has been made for this year"}
  11  Stripe and PayPal summary, with the 1099-K comparison (CSV)
  12  Stripe payouts (CSV)
  13  Open invoices (CSV)
  14  Owner contributions and draws (CSV)

This is a record of the books, not tax advice. Categories and methods are for the CPA to confirm.
'''
