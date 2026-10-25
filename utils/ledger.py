"""One ledger for every dollar, in whole cents, in Kansas City time.

Rules this module keeps:
  * Entries are never edited or deleted. If a number changes later (a real Stripe fee replaces an estimate, a
    refund is recorded, an invoice gets another payment), a new dated adjustment entry carries the difference.
  * Cash basis: money counts on the day it was received, not the day it was ordered or invoiced.
  * Reports group by the Kansas City calendar day (kc_date), so a 9 pm sale lands on the right day and month.
  * Sales tax collected is kept apart from income. Processing fees are an expense (Commissions and fees).
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func

from models import Expense, FinancialEntry, LedgerEntry, ManualInvoice, Order, db

CENTRAL = ZoneInfo('America/Chicago')

SALE, SHIPPING, TAX, DISCOUNT = 'sale', 'shipping', 'sales_tax', 'discount'
REFUND, REFUND_TAX = 'refund', 'refund_tax'
FEE, COGS, EXPENSE = 'processing_fee', 'cogs', 'expense'
OTHER_INCOME, CONTRIBUTION, DRAW = 'other_income', 'owner_contribution', 'owner_draw'
PAYOUT = 'payout'                       # a transfer to the bank: not income, not an expense

TYPE_LABELS = {
    SALE: 'Sales', SHIPPING: 'Shipping charged', TAX: 'Sales tax collected', DISCOUNT: 'Discounts',
    REFUND: 'Refunds', REFUND_TAX: 'Sales tax refunded', FEE: 'Processing fees', COGS: 'Cost of goods',
    EXPENSE: 'Expenses', OTHER_INCOME: 'Other income', CONTRIBUTION: 'Owner contributions', DRAW: 'Owner draws',
    PAYOUT: 'Payouts to bank',
}

FEE_CATEGORY = 'Commissions and fees'

# Schedule C lines are a guide for the CPA to confirm. Equipment is recorded as Supplies (the Equipment box).
EXPENSE_CATEGORIES = [
    ('Advertising', '8'), ('Car and truck (mileage)', '9'), (FEE_CATEGORY, '10'), ('Contract labor', '11'),
    ('Insurance', '15'), ('Legal and professional', '17'), ('Office expense', '18'), ('Rent', '20'),
    ('Repairs', '21'), ('Supplies', '22'), ('Taxes and licenses', '23'), ('Travel', '24a'), ('Meals', '24b'),
    ('Utilities', '25'), ('Software and subscriptions', '27a'), ('Shipping and postage', '27a'), ('Other', '27a'),
]
EXPENSE_LINE = dict(EXPENSE_CATEGORIES)
PAY_METHODS = ['Card', 'Cash', 'Check', 'Venmo', 'PayPal', 'Bank transfer', 'Other']


# ---- money and time ----------------------------------------------------------------------------

def to_cents(value) -> int:
    """Dollars (a float from the database, a string, a Decimal) to whole cents, rounded half up."""
    return int((Decimal(str(value or 0)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def dollars(cents) -> str:
    """12345 -> '$123.45', -500 -> '-$5.00'."""
    cents = int(cents or 0)
    sign = '-' if cents < 0 else ''
    return f'{sign}${abs(cents) / 100:,.2f}'


def kc_now() -> datetime:
    return datetime.now(CENTRAL)


def kc_today() -> date:
    return kc_now().date()


def kc_day(dt: datetime) -> date:
    """The Kansas City calendar day for a stored (UTC) time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CENTRAL).date()


# ---- writing entries ---------------------------------------------------------------------------

def _add(entry_type, cents, *, when, source_key=None, category=None, **extra):
    row = LedgerEntry(entry_type=entry_type, amount_cents=int(cents), occurred_at=when, kc_date=kc_day(when),
                      source_key=source_key, category=category, **extra)
    db.session.add(row)
    return row


def sync_source(source_key, desired, *, when, current, estimate_types=(), when_map=None, **meta):
    """Make the ledger match what one order or invoice says it should total, by adding only the difference.

    desired: {entry_type: cents}. current: {(source_key, entry_type): cents already in the ledger}.
    Returns how many entries were added.
    """
    added = 0
    base_note = meta.pop('note', None)
    types = set(desired) | {t for (k, t) in current if k == source_key}
    for entry_type in types:
        want = int(desired.get(entry_type, 0))
        have = int(current.get((source_key, entry_type), 0))
        delta = want - have
        if delta == 0:
            continue
        first = (source_key, entry_type) not in current
        category = FEE_CATEGORY if entry_type == FEE else None
        first_when = (when_map or {}).get(entry_type) or when          # a refund counts on the day it went out
        _add(entry_type, delta, when=first_when if first else datetime.utcnow(), source_key=source_key, category=category,
             is_estimate=entry_type in estimate_types,
             note=base_note if first else 'Adjustment: the order or invoice changed' + (f'. {base_note}' if base_note else ''), **meta)
        added += 1
    return added


def _pay_source(method):
    method = (method or '').lower()
    if method in ('stripe', 'card'):
        return 'stripe'
    if method == 'paypal':
        return 'paypal'
    if method in ('cash', 'check', 'venmo'):
        return method
    return 'other'


def _channel(order):
    if (order.payment_method or '') == 'company_invoice':
        return 'company'
    if order.collection_id:
        return 'group'
    if (order.payment_method or '') == 'cash':
        return 'cash'
    return 'retail'


def _refund_parts(total_cents, tax_cents, refunded_cents, fully_refunded):
    """Split what was refunded into the sale part and the sales tax part (in proportion to the order)."""
    refunded = int(refunded_cents or 0)
    if fully_refunded:
        refunded = max(refunded, total_cents)                  # a manual "refunded" tick means all of it
    refunded = min(refunded, total_cents)
    if refunded <= 0 or total_cents <= 0:
        return 0, 0
    tax_part = int((Decimal(refunded) * Decimal(tax_cents) / Decimal(total_cents)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return refunded - tax_part, tax_part


def refund_day(obj):
    """When a refund went out: the recorded time, else the last time the record changed."""
    return getattr(obj, 'refunded_at', None) or getattr(obj, 'updated_at', None) or datetime.utcnow()


def order_desired(order):
    """What the ledger should show for one order, as {entry_type: cents}. Empty until it is paid."""
    paid = (order.payment_status or '') in ('paid', 'refunded') or bool(order.is_refunded)
    if not paid:
        return {}, ()
    merchandise, shipping, tax = to_cents(order.subtotal), to_cents(order.shipping_cost), to_cents(order.tax)
    want = {SALE: merchandise, SHIPPING: shipping, TAX: tax}
    estimates = []
    if order.processing_fee:
        want[FEE] = -to_cents(order.processing_fee)
        if not order.processing_fee_is_actual:
            estimates.append(FEE)
    if order.cost_of_goods:
        want[COGS] = -to_cents(order.cost_of_goods)
        if not order.cogs_is_actual:
            estimates.append(COGS)
    refund, refund_tax = _refund_parts(merchandise + shipping + tax, tax, getattr(order, 'refunded_cents', 0), order.is_refunded)
    if refund or refund_tax:
        want[REFUND], want[REFUND_TAX] = -refund, -refund_tax
    return want, tuple(estimates)


def invoice_desired(inv):
    """Hand-made invoices count only as they are paid (cash basis), in proportion to each payment."""
    from utils.receipts import doc_from_invoice
    doc = doc_from_invoice(inv)
    total, paid = to_cents(doc['total']), to_cents(doc['paid'])
    if paid <= 0 or total <= 0:
        return {}
    ratio = Decimal(paid) / Decimal(total)

    def part(value):
        return int((Decimal(to_cents(value)) * ratio).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    shipping, tax, discount = part(doc['shipping']), part(doc['tax']), part(doc['discount'])
    want = {SHIPPING: shipping, TAX: tax, SALE: paid - shipping - tax + discount}     # the pieces add up to what was paid
    if discount:
        want[DISCOUNT] = -discount
    refund, refund_tax = _refund_parts(paid, tax, getattr(inv, 'refunded_cents', 0), False)
    if refund or refund_tax:
        want[REFUND], want[REFUND_TAX] = -refund, -refund_tax
    return want


def _current_sums():
    rows = (db.session.query(LedgerEntry.source_key, LedgerEntry.entry_type, func.sum(LedgerEntry.amount_cents))
            .filter(LedgerEntry.source_key.isnot(None)).group_by(LedgerEntry.source_key, LedgerEntry.entry_type).all())
    return {(k, t): int(v or 0) for k, t, v in rows}


_LEGACY_MAP = {          # the five boxes on the old Financial page
    'revenue': (OTHER_INCOME, None), 'cogs': (COGS, None), 'advertising': (EXPENSE, 'Advertising'),
    'equipment': (EXPENSE, 'Supplies'), 'misc': (EXPENSE, 'Other'),
}


def import_legacy_entries(current):
    """Bring the old manual Financial entries into the ledger once. The originals are left untouched."""
    added = 0
    for e in FinancialEntry.query.order_by(FinancialEntry.id).all():
        key = f'legacy:{e.id}'
        if e.order_id or any(k == key for (k, _t) in current):          # entries tied to an order are already in its cost
            continue
        kind, category = _LEGACY_MAP.get((e.category or '').lower(), (EXPENSE, 'Other'))
        cents = to_cents(abs(e.amount or 0))
        if cents == 0:
            continue
        signed = cents if kind == OTHER_INCOME else -cents
        when = e.entry_date or e.created_at or datetime.utcnow()
        _add(kind, signed, when=when, source_key=key, category=category, pay_source='other', channel=None,
             note=f'Imported from the earlier Financial page: {e.description or e.category}')
        added += 1
    return added


_LAST_SYNC = {'at': 0.0}


def sync_all(force=False, min_gap=60):
    """Bring the ledger up to date with every paid order, invoice and old manual entry. Safe to run any time."""
    now = time.time()
    if not force and now - _LAST_SYNC['at'] < min_gap:
        return 0
    _LAST_SYNC['at'] = now
    from utils import sales_tax
    current = _current_sums()
    added = 0
    tax_labels = {}                       # order or invoice id -> (where taxed, was tax charged, rate)
    for order in Order.query.all():
        want, estimates = order_desired(order)
        key = f'order:{order.id}'
        if not want and not any(k == key for (k, _t) in current):
            continue
        guessed, effective = sales_tax.classify_order(order)
        if not order.tax_jurisdiction:
            order.tax_jurisdiction = guessed                 # the label is kept on the order from now on
        if order.tax_rate_percent is None:
            order.tax_rate_percent = effective
        label = (order.tax_jurisdiction, bool(order.tax and order.tax > 0), order.tax_rate_percent)
        tax_labels[('order', order.id)] = label
        when = order.paid_at or order.created_at or datetime.utcnow()
        added += sync_source(key, want, when=when, current=current, estimate_types=estimates,
                             when_map={REFUND: refund_day(order), REFUND_TAX: refund_day(order)},
                             order_id=order.id, pay_source=_pay_source(order.payment_method), channel=_channel(order),
                             collection_id=order.collection_id, jurisdiction=label[0], taxable=label[1],
                             tax_rate_percent=label[2])
    for inv in ManualInvoice.query.all():
        want = invoice_desired(inv)
        key = f'invoice:{inv.id}'
        if not want and not any(k == key for (k, _t) in current):
            continue
        if want and not inv.paid_at:
            inv.paid_at = inv.updated_at or inv.issued_at or datetime.utcnow()      # first time we notice the payment
        label = (sales_tax.INVOICE, (inv.tax_rate or 0) > 0, float(inv.tax_rate or 0))
        tax_labels[('invoice', inv.id)] = label
        added += sync_source(key, want, when=inv.paid_at or datetime.utcnow(), current=current,
                             when_map={REFUND: refund_day(inv), REFUND_TAX: refund_day(inv)},
                             invoice_id=inv.id, pay_source=_pay_source(inv.payment_method), channel='invoice',
                             jurisdiction=label[0], taxable=label[1], tax_rate_percent=label[2])
    _label_older_entries(tax_labels)
    added += import_legacy_entries(current)
    db.session.commit()
    return added


def _label_older_entries(tax_labels):
    """Entries written before the sales tax labels existed get them now. Only the label changes, never an amount."""
    rows = (LedgerEntry.query.filter(LedgerEntry.jurisdiction.is_(None))
            .filter(db.or_(LedgerEntry.order_id.isnot(None), LedgerEntry.invoice_id.isnot(None))).all())
    for row in rows:
        label = tax_labels.get(('order', row.order_id)) if row.order_id else tax_labels.get(('invoice', row.invoice_id))
        if label:
            row.jurisdiction, row.taxable, row.tax_rate_percent = label


# ---- expenses and owner money ------------------------------------------------------------------

def add_expense(*, when_day: date, vendor, amount_dollars, category, payment_method=None, note=None, receipt_url=None,
                is_equipment=False, user_id=None, recurring_id=None):
    cents = to_cents(amount_dollars)
    if cents <= 0:
        raise ValueError('The amount must be more than zero.')
    if category not in EXPENSE_LINE:
        raise ValueError('Choose a category.')
    exp = Expense(expense_date=when_day, vendor=(vendor or '').strip()[:120] or None, amount_cents=cents, category=category,
                  payment_method=payment_method, note=(note or '').strip() or None, receipt_url=receipt_url,
                  is_equipment=bool(is_equipment), created_by_id=user_id, recurring_id=recurring_id)
    db.session.add(exp)
    db.session.flush()
    noon = datetime.combine(when_day, datetime.min.time()).replace(hour=12, tzinfo=CENTRAL).astimezone(timezone.utc)
    _add(EXPENSE, -cents, when=noon.replace(tzinfo=None), source_key=f'expense:{exp.id}', category=category,
         expense_id=exp.id, vendor=exp.vendor, pay_source=_pay_source(payment_method), created_by_id=user_id,
         note=exp.note)
    db.session.commit()
    return exp


def void_expense(expense_id, user_id=None):
    """Voiding adds a reversing entry today; the original entry and the expense stay on record."""
    exp = db.session.get(Expense, expense_id)
    if exp is None or exp.voided_at:
        return None
    exp.voided_at = datetime.utcnow()
    _add(EXPENSE, exp.amount_cents, when=datetime.utcnow(), source_key=f'expense:{exp.id}', category=exp.category,
         expense_id=exp.id, vendor=exp.vendor, created_by_id=user_id, note='Voided: reverses the original entry')
    db.session.commit()
    return exp


def add_owner_entry(kind, *, when_day: date, amount_dollars, note=None, user_id=None):
    if kind not in (CONTRIBUTION, DRAW):
        raise ValueError('Unknown entry type.')
    cents = to_cents(amount_dollars)
    if cents <= 0:
        raise ValueError('The amount must be more than zero.')
    noon = datetime.combine(when_day, datetime.min.time()).replace(hour=12, tzinfo=CENTRAL).astimezone(timezone.utc)
    row = _add(kind, cents if kind == CONTRIBUTION else -cents, when=noon.replace(tzinfo=None), source_key='manual',
               pay_source='bank', created_by_id=user_id, note=(note or '').strip() or None)
    db.session.commit()
    return row


# ---- periods and reports -----------------------------------------------------------------------

PERIODS = [('this_month', 'This month'), ('last_month', 'Last month'), ('q1', 'Q1'), ('q2', 'Q2'), ('q3', 'Q3'),
           ('q4', 'Q4'), ('ytd', 'Year to date'), ('last_year', 'Last year'), ('custom', 'Custom')]


def _month_end(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def resolve_period(period, *, year=None, start=None, end=None, today=None):
    """(first_day, last_day, label) for a report period, in Kansas City days."""
    today = today or kc_today()
    year = int(year or today.year)
    month_names = '%B %Y'
    if period == 'last_month':
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        return first, _month_end(first), first.strftime(month_names)
    if period in ('q1', 'q2', 'q3', 'q4'):
        q = int(period[1])
        first = date(year, 3 * q - 2, 1)
        return first, _month_end(date(year, 3 * q, 1)), f'Q{q} {year}'
    if period == 'ytd':
        return date(today.year, 1, 1), today, f'Year to date {today.year}'
    if period == 'last_year':
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1)
    if period == 'custom' and start and end:
        if end < start:
            start, end = end, start
        return start, end, f"{start.strftime('%b %d, %Y').replace(' 0', ' ')} to {end.strftime('%b %d, %Y').replace(' 0', ' ')}"
    first = today.replace(day=1)                      # this_month, and the fallback
    return first, _month_end(first), first.strftime(month_names)


def parse_day(text):
    try:
        return datetime.strptime((text or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _sums(start, end):
    rows = (db.session.query(LedgerEntry.entry_type, LedgerEntry.category, func.sum(LedgerEntry.amount_cents))
            .filter(LedgerEntry.kc_date >= start, LedgerEntry.kc_date <= end)
            .group_by(LedgerEntry.entry_type, LedgerEntry.category).all())
    return [(t, c, int(v or 0)) for t, c, v in rows]


def pnl(start: date, end: date):
    """Profit and loss for a range of Kansas City days. Every figure is in cents, with the filter that lists its entries."""
    by_type, expenses = {}, {}
    for entry_type, category, cents in _sums(start, end):
        by_type[entry_type] = by_type.get(entry_type, 0) + cents
        if entry_type in (EXPENSE, FEE):
            label = category or 'Other'
            expenses[label] = expenses.get(label, 0) - cents                     # shown as a positive cost
    sales, shipping = by_type.get(SALE, 0), by_type.get(SHIPPING, 0)
    discounts, refunds = by_type.get(DISCOUNT, 0), by_type.get(REFUND, 0)
    gross_sales = sales + shipping
    net_sales = gross_sales + discounts + refunds
    cogs = -by_type.get(COGS, 0)
    gross_profit = net_sales - cogs
    other_income = by_type.get(OTHER_INCOME, 0)
    total_expenses = sum(expenses.values())
    ordered = sorted(expenses.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        'start': start, 'end': end,
        'sales': sales, 'shipping': shipping, 'gross_sales': gross_sales, 'discounts': discounts, 'refunds': refunds,
        'net_sales': net_sales, 'cogs': cogs, 'gross_profit': gross_profit, 'other_income': other_income,
        'expenses': ordered, 'total_expenses': total_expenses,
        'net_profit': gross_profit + other_income - total_expenses,
        'tax_collected': by_type.get(TAX, 0) + by_type.get(REFUND_TAX, 0),
        'contributions': by_type.get(CONTRIBUTION, 0), 'draws': -by_type.get(DRAW, 0),
    }


def monthly(year: int):
    """Twelve months of the profit and loss for one year, Kansas City time."""
    out = []
    for m in range(1, 13):
        first = date(year, m, 1)
        out.append((first.strftime('%b'), pnl(first, _month_end(first))))
    return out


def sales_tax_report(start: date, end: date):
    """Sales and tax collected, grouped by where each sale was taxed. All figures in cents."""
    from utils import sales_tax
    types = [SALE, DISCOUNT, REFUND, SHIPPING, TAX, REFUND_TAX]
    rows = (db.session.query(LedgerEntry.jurisdiction, LedgerEntry.taxable, LedgerEntry.entry_type,
                             func.sum(LedgerEntry.amount_cents),
                             func.count(func.distinct(LedgerEntry.source_key)))
            .filter(LedgerEntry.kc_date >= start, LedgerEntry.kc_date <= end, LedgerEntry.entry_type.in_(types))
            .group_by(LedgerEntry.jurisdiction, LedgerEntry.taxable, LedgerEntry.entry_type).all())
    groups = {}
    for jurisdiction, taxable, entry_type, cents, count in rows:
        g = groups.setdefault(jurisdiction or 'other', {'taxable': 0, 'not_taxed': 0, 'shipping': 0, 'tax': 0, 'orders': 0})
        cents = int(cents or 0)
        if entry_type in (SALE, DISCOUNT, REFUND):
            g['taxable' if taxable else 'not_taxed'] += cents
            if entry_type == SALE:
                g['orders'] += int(count or 0)
        elif entry_type == SHIPPING:
            g['shipping'] += cents
        else:
            g['tax'] += cents
    labels = dict(sales_tax.JURISDICTION_LABELS, other='Other or older entries')
    order = [sales_tax.LOCAL, sales_tax.KS_SHIPPED, sales_tax.OUT_OF_STATE, sales_tax.INVOICE, 'other']
    table = []
    for key in order:
        if key in groups:
            g = groups[key]
            rate = round(100.0 * g['tax'] / g['taxable'], 2) if g['taxable'] > 0 else 0.0
            table.append(dict(g, key=key, label=labels[key], rate=rate))
    totals = {k: sum(r[k] for r in table) for k in ('taxable', 'not_taxed', 'shipping', 'tax', 'orders')}
    out_of_state_tax = groups.get(sales_tax.OUT_OF_STATE, {}).get('tax', 0)
    return {'rows': table, 'totals': totals, 'out_of_state_tax': out_of_state_tax}


def estimate_counts():
    """How many paid orders still use an estimated fee or an estimated cost of goods."""
    paid = Order.query.filter(Order.payment_status == 'paid', Order.is_refunded.isnot(True))
    return {'fees': paid.filter(Order.processing_fee.isnot(None), Order.processing_fee_is_actual.isnot(True)).count(),
            'cogs': paid.filter(Order.cost_of_goods.isnot(None), Order.cogs_is_actual.isnot(True)).count()}


def sales_by_channel(start: date, end: date):
    rows = (db.session.query(LedgerEntry.channel, func.sum(LedgerEntry.amount_cents))
            .filter(LedgerEntry.kc_date >= start, LedgerEntry.kc_date <= end,
                    LedgerEntry.entry_type.in_([SALE, SHIPPING, DISCOUNT, REFUND]))
            .group_by(LedgerEntry.channel).all())
    names = {'retail': 'Shop orders', 'group': 'Group orders', 'company': 'Company orders', 'invoice': 'Invoices',
             'cash': 'Cash at pickup', None: 'Other'}
    return sorted(((names.get(c, c or 'Other'), int(v or 0)) for c, v in rows), key=lambda kv: -kv[1])
