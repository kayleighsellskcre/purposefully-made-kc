"""Year-end pieces for the CPA: the inventory count (valued at cost), the mileage log, and a check of what Stripe and
PayPal took in against what they paid out. Money is in whole cents; days are Kansas City days.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from models import (ApparelInventory, Expense, InventoryCount, InventoryCountLine, LedgerEntry, ManualInvoice,
                    MileageFavorite, MileageTrip, Supply, TransferInventory, db)
from utils import ledger as L

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
KINDS = [('blanks', 'Blank garments'), ('transfers', 'DTF transfers'), ('supplies', 'Supplies and packaging'), ('other', 'Other')]
KIND_LABELS = dict(KINDS)


# ---- inventory count ---------------------------------------------------------------------------

def count_for(year):
    return InventoryCount.query.filter_by(year=int(year)).first()


def start_count(year):
    """Begin a count for a year by copying today's stock records. Returns the count (the existing one if there is one)."""
    year = int(year)
    existing = count_for(year)
    if existing:
        return existing
    today = L.kc_today()
    count = InventoryCount(year=year, as_of=date(year, 12, 31) if year < today.year else today)
    db.session.add(count)
    db.session.flush()

    def add(kind, description, quantity, unit_cost):
        if int(quantity or 0) > 0:
            count.lines.append(InventoryCountLine(kind=kind, description=description[:200], quantity=int(quantity),
                                                  unit_cost_cents=L.to_cents(unit_cost)))
    for row in ApparelInventory.query.order_by(ApparelInventory.brand, ApparelInventory.color, ApparelInventory.size).all():
        add('blanks', f'{row.brand} {row.color} {row.size}'.strip(), row.quantity, row.cost_per_unit)
    for row in TransferInventory.query.order_by(TransferInventory.design_name).all():
        add('transfers', f'{row.design_name} {row.size or ""}'.strip(), row.quantity, row.cost_per_sheet)
    for row in Supply.query.order_by(Supply.category, Supply.name).all():
        add('supplies', row.name, row.quantity, row.cost_per_unit)
    db.session.commit()
    return count


def _editable(line):
    if line is None or line.count.locked_at:
        raise ValueError('That count is locked, so it can no longer change.')
    return line


def update_line(line_id, quantity, unit_cost_dollars):
    line = _editable(db.session.get(InventoryCountLine, int(line_id)))
    line.quantity = max(0, int(quantity or 0))
    line.unit_cost_cents = max(0, L.to_cents(unit_cost_dollars))
    db.session.commit()
    return line


def add_line(count, kind, description, quantity, unit_cost_dollars):
    if count.locked_at:
        raise ValueError('That count is locked, so it can no longer change.')
    description = (description or '').strip()
    if not description:
        raise ValueError('Describe what you counted.')
    line = InventoryCountLine(count_id=count.id, kind=kind if kind in KIND_LABELS else 'other', description=description[:200],
                              quantity=max(0, int(quantity or 0)), unit_cost_cents=max(0, L.to_cents(unit_cost_dollars)))
    db.session.add(line)
    db.session.commit()
    return line


def delete_line(line_id):
    line = _editable(db.session.get(InventoryCountLine, int(line_id)))
    db.session.delete(line)
    db.session.commit()


def lock_count(count):
    if not count.locked_at:
        count.locked_at = datetime.utcnow()
        db.session.commit()
    return count


def count_totals(count):
    """({kind: cents}, total cents) for a count, valued at cost."""
    by_kind = {k: 0 for k, _n in KINDS}
    for line in count.lines:
        by_kind[line.kind] = by_kind.get(line.kind, 0) + line.value_cents
    return by_kind, sum(by_kind.values())


# ---- mileage -----------------------------------------------------------------------------------

def to_tenths(miles):
    value = Decimal(str(miles or 0)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    tenths = int(value * 10)
    if tenths <= 0:
        raise ValueError('Enter the miles for the trip, like 12.5.')
    return tenths


def miles_text(tenths):
    return f'{int(tenths or 0) / 10:,.1f}'


def add_trip(day, start, destination, purpose, miles):
    trip = MileageTrip(trip_date=day, start=(start or '').strip()[:120] or None, destination=(destination or '').strip()[:120] or None,
                       purpose=(purpose or '').strip()[:200] or None, miles_tenths=to_tenths(miles))
    db.session.add(trip)
    db.session.commit()
    return trip


def add_favorite(label, start, destination, purpose, miles):
    label = (label or '').strip()
    if not label:
        raise ValueError('Give the saved trip a short name, like "Supplier pickup".')
    fav = MileageFavorite(label=label[:80], start=(start or '').strip()[:120] or None,
                          destination=(destination or '').strip()[:120] or None,
                          purpose=(purpose or '').strip()[:200] or None, miles_tenths=to_tenths(miles))
    db.session.add(fav)
    db.session.commit()
    return fav


def log_favorite(favorite_id, day):
    fav = db.session.get(MileageFavorite, int(favorite_id))
    if fav is None:
        raise ValueError('That saved trip was not found.')
    trip = MileageTrip(trip_date=day, start=fav.start, destination=fav.destination, purpose=fav.purpose or fav.label,
                       miles_tenths=fav.miles_tenths)
    db.session.add(trip)
    db.session.commit()
    return trip


def trips_in_year(year):
    return (MileageTrip.query.filter(MileageTrip.trip_date >= date(year, 1, 1), MileageTrip.trip_date <= date(year, 12, 31))
            .order_by(MileageTrip.trip_date, MileageTrip.id).all())


# ---- what the processors took in against what they paid out -----------------------------------------

_MONEY_IN = (L.SALE, L.SHIPPING, L.TAX, L.DISCOUNT)
_REFUNDS = (L.REFUND, L.REFUND_TAX)


def processor_summary(year):
    """For Stripe and PayPal, month by month: money in, refunds, fees, what should be left, and what was paid out.

    'Gross' is money in before refunds and fees, which is how a 1099-K reports it. A small running balance is normal:
    a processor pays out a day or two after the sale.
    """
    year = int(year)
    rows = (db.session.query(func.extract('month', LedgerEntry.kc_date), LedgerEntry.pay_source, LedgerEntry.entry_type,
                             func.sum(LedgerEntry.amount_cents))
            .filter(LedgerEntry.kc_date >= date(year, 1, 1), LedgerEntry.kc_date <= date(year, 12, 31),
                    LedgerEntry.pay_source.in_(['stripe', 'paypal']),
                    LedgerEntry.entry_type.in_(list(_MONEY_IN) + list(_REFUNDS) + [L.FEE, L.PAYOUT]))
            .group_by(func.extract('month', LedgerEntry.kc_date), LedgerEntry.pay_source, LedgerEntry.entry_type).all())
    cells = {}
    for month, source, entry_type, cents in rows:
        cell = cells.setdefault((source, int(month)), {'in': 0, 'refunds': 0, 'fees': 0, 'paid_out': 0})
        cents = int(cents or 0)
        if entry_type in _MONEY_IN:
            cell['in'] += cents
        elif entry_type in _REFUNDS:
            cell['refunds'] += cents
        elif entry_type == L.FEE:
            cell['fees'] += cents
        else:
            cell['paid_out'] += cents
    result = {}
    for source in ('stripe', 'paypal'):
        table, balance = [], 0
        totals = {'in': 0, 'refunds': 0, 'fees': 0, 'expected': 0, 'paid_out': 0}
        for m in range(1, 13):
            c = cells.get((source, m), {'in': 0, 'refunds': 0, 'fees': 0, 'paid_out': 0})
            expected = c['in'] + c['refunds'] + c['fees']
            balance += expected - c['paid_out']
            table.append({'month': MONTHS[m - 1], 'in': c['in'], 'refunds': c['refunds'], 'fees': c['fees'], 'expected': expected,
                          'paid_out': c['paid_out'], 'balance': balance})
            for k in ('in', 'refunds', 'fees', 'paid_out'):
                totals[k] += c[k]
            totals['expected'] += expected
        totals['balance'] = balance
        result[source] = {'rows': table, 'totals': totals}
    return result


# ---- the checklist before the package goes to the CPA ----------------------------------------------

def open_invoice_rows(as_of=None):
    """Hand-made invoices that still have a balance (not income yet, on a cash basis)."""
    from utils.receipts import doc_from_invoice
    out = []
    for inv in ManualInvoice.query.order_by(ManualInvoice.issued_at).all():
        doc = doc_from_invoice(inv)
        if doc['balance'] > 0.004:
            out.append({'number': inv.number, 'customer': inv.company or inv.customer_name or '', 'issued': inv.issued_at,
                        'total_cents': L.to_cents(doc['total']), 'paid_cents': L.to_cents(doc['paid']),
                        'balance_cents': L.to_cents(doc['balance'])})
    return out


def package_checks(year):
    """What is ready and what needs a look before the year's package goes to the CPA. [(level, text, endpoint)]."""
    year = int(year)
    first, last = date(year, 1, 1), date(year, 12, 31)
    checks = []
    missing = Expense.query.filter(Expense.expense_date >= first, Expense.expense_date <= last, Expense.voided_at.is_(None),
                                   Expense.receipt_url.is_(None)).count()
    total_expenses = Expense.query.filter(Expense.expense_date >= first, Expense.expense_date <= last,
                                          Expense.voided_at.is_(None)).count()
    checks.append(('warn' if missing else 'ok',
                   f'{missing} of {total_expenses} expenses have no receipt.' if missing else
                   (f'All {total_expenses} expenses have a receipt.' if total_expenses else 'No expenses recorded for this year yet.'),
                   'admin.expenses'))
    est = L.estimate_counts()
    checks.append(('warn' if est['fees'] or est['cogs'] else 'ok',
                   f"{est['fees']} orders use an estimated processing fee and {est['cogs']} an estimated cost of goods."
                   if est['fees'] or est['cogs'] else 'Every fee and cost of goods is a real figure.', 'admin.reports'))
    count = count_for(year)
    if count is None:
        checks.append(('warn', f'There is no {year} inventory count yet.', 'admin.inventory_count'))
    elif not count.locked_at:
        checks.append(('warn', f'The {year} inventory count is started but not locked.', 'admin.inventory_count'))
    else:
        checks.append(('ok', f'The {year} inventory count is locked at {L.dollars(count_totals(count)[1])}.', 'admin.inventory_count'))
    report = L.sales_tax_report(first, last)
    if report['out_of_state_tax']:
        checks.append(('warn', f"{L.dollars(report['out_of_state_tax'])} of Kansas tax was collected on out-of-state shipments.",
                       'admin.sales_tax_report'))
    else:
        checks.append(('ok', 'No Kansas tax was collected on out-of-state shipments.', 'admin.sales_tax_report'))
    open_rows = open_invoice_rows()
    if open_rows:
        checks.append(('info', f"{len(open_rows)} open invoice{'s' if len(open_rows) != 1 else ''} worth "
                               f"{L.dollars(sum(r['balance_cents'] for r in open_rows))} (not income until paid).", 'admin.invoices'))
    summary = processor_summary(year)
    balance = summary['stripe']['totals']['balance']
    if abs(balance) > 5000:
        checks.append(('warn', f'Stripe sales less fees and refunds is {L.dollars(abs(balance))} '
                               f"{'more' if balance > 0 else 'less'} than its payouts. Check the payout events are switched on.",
                       'admin.payout_check'))
    else:
        checks.append(('ok', 'Stripe sales line up with its payouts.', 'admin.payout_check'))
    return checks
