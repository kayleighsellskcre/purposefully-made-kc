"""Kansas sales tax, set up to follow the Kansas portal screen by screen.

One place decides everything the owner needs when a return is due:

* which period is up, when the return is due (the 25th of the month after the period ends, moved to the next
  business day when that falls on a weekend or a holiday, or the date she types in from the portal),
* the three portal parts built from the same records: Part III (sales and tax by jurisdiction), Part II
  (deductions, including Line M for qualifying out-of-state deliveries) and Part I (tax due),
* a short list of records that need a decision before filing,
* a frozen copy of what was filed.

Cash basis, as the CPA said: a sale counts on the Kansas City day the money arrived (the ledger date), and a
refund counts on the day it went out. Nothing here edits a ledger row or an order's money.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from models import KsFiling, KsJurisdiction, db

FREQUENCIES = [('quarterly', 'Quarterly'), ('monthly', 'Monthly'), ('annual', 'Yearly')]
DEFAULT_CODE, DEFAULT_NAME, DEFAULT_RATE = 'SHAJO', 'Shawnee / Johnson County', 9.6
DEFAULT_REMINDERS = '14,7,2'
TRACK_TOLERANCE_CENTS = 2


# ---- settings -----------------------------------------------------------------------------------

def _get(key, default=''):
    from utils.site_settings import get_setting
    return get_setting(key, default) or default


def _set(key, value, description):
    from utils.site_settings import set_setting
    set_setting(key, value, description)


def frequency():
    value = _get('ks_filing_frequency', 'quarterly')
    return value if value in dict(FREQUENCIES) else 'quarterly'


def save_frequency(value):
    if value not in dict(FREQUENCIES):
        raise ValueError('Pick quarterly, monthly or yearly.')
    _set('ks_filing_frequency', value, 'How often the Kansas sales tax return is due')


def reminder_days():
    """Days before the due date when a reminder goes out, biggest first. Bad entries are ignored."""
    days = []
    for part in _get('ks_reminder_days', DEFAULT_REMINDERS).replace(';', ',').split(','):
        part = part.strip()
        if part.isdigit() and 0 < int(part) <= 60 and int(part) not in days:
            days.append(int(part))
    return sorted(days, reverse=True) or [14, 7, 2]


def save_reminder_days(text):
    days = []
    for part in (text or '').replace(';', ',').split(','):
        part = part.strip()
        if part.isdigit() and 0 < int(part) <= 60 and int(part) not in days:
            days.append(int(part))
    if not days:
        raise ValueError('Enter the days before the due date, like 14, 7, 2.')
    _set('ks_reminder_days', ','.join(str(d) for d in sorted(days, reverse=True)), 'Days before the Kansas due date to remind')


def pickup_code():
    return (_get('ks_pickup_code', DEFAULT_CODE) or DEFAULT_CODE).upper()


def ensure_defaults():
    """Make sure the Shawnee pickup jurisdiction exists, using the rate Kansas lists for it."""
    if KsJurisdiction.query.count() == 0:
        db.session.add(KsJurisdiction(code=DEFAULT_CODE, name=DEFAULT_NAME, rate_percent=DEFAULT_RATE))
        db.session.commit()


def jurisdictions():
    ensure_defaults()
    return KsJurisdiction.query.order_by(KsJurisdiction.code).all()


def jurisdiction_map():
    return {j.code: j for j in jurisdictions()}


def pickup_rate_percent():
    """The rate for the pickup jurisdiction when it is set up, else None (the older Site settings rate applies)."""
    row = KsJurisdiction.query.filter_by(code=pickup_code()).first()
    return float(row.rate_percent) if row is not None else None


def save_jurisdiction(code, name, rate):
    code = (code or '').strip().upper()
    name = (name or '').strip()
    if not code or len(code) > 12 or not code.isalnum():
        raise ValueError('The code is letters and numbers only, like SHAJO.')
    if not name:
        raise ValueError('Give the place a name.')
    try:
        rate = round(float(rate), 4)
    except (TypeError, ValueError):
        raise ValueError('Enter the rate as a number, like 9.6.')
    if not (0 < rate <= 15):
        raise ValueError('Enter a rate between 0 and 15 percent, like 9.6.')
    row = KsJurisdiction.query.filter_by(code=code).first()
    if row is None:
        row = KsJurisdiction(code=code, name=name, rate_percent=rate)
        db.session.add(row)
    else:
        row.name, row.rate_percent = name, rate
    db.session.commit()
    from utils import sales_tax
    sales_tax.clear_cache()
    return row


def stamp_order(order):
    """Pin the jurisdiction code on an order the first time the books see it (shipped-in-Kansas orders wait for a person)."""
    if order.ks_code or order.tax_jurisdiction == 'ks_shipped':
        return
    order.ks_code = pickup_code()


# ---- periods and due dates ------------------------------------------------------------------------

def period_for(day: date, freq: str | None = None):
    freq = freq or frequency()
    if freq == 'monthly':
        start = day.replace(day=1)
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, nxt - timedelta(days=1)
    if freq == 'annual':
        return date(day.year, 1, 1), date(day.year, 12, 31)
    q = (day.month - 1) // 3
    start = date(day.year, q * 3 + 1, 1)
    end_month = q * 3 + 3
    nxt = date(day.year + (end_month == 12), (end_month % 12) + 1, 1)
    return start, nxt - timedelta(days=1)


def next_period_start(end: date) -> date:
    return end + timedelta(days=1)


def previous_period(start: date, freq: str | None = None):
    return period_for(start - timedelta(days=1), freq)


def period_label(start: date, end: date, freq: str | None = None) -> str:
    freq = freq or frequency()
    if freq == 'monthly':
        return start.strftime('%B %Y')
    if freq == 'annual':
        return f'{start.year}'
    return f'Q{(start.month - 1) // 3 + 1} {start.year}'


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = (date(year + (month == 12), (month % 12) + 1, 1)) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def holidays(year: int) -> set:
    """Days Kansas government offices are closed (observed on the nearest weekday when they fall on a weekend)."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    days = set()
    for d in fixed:
        days.add(d)
        if d.weekday() == 5:
            days.add(d - timedelta(days=1))
        elif d.weekday() == 6:
            days.add(d + timedelta(days=1))
    days |= {_nth_weekday(year, 1, 0, 3), _last_weekday(year, 5, 0), _nth_weekday(year, 9, 0, 1),
             _nth_weekday(year, 11, 3, 4)}
    return days


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def computed_due_date(period_end: date) -> date:
    """The 25th of the month after the period ends, or the next business day when that is a weekend or holiday."""
    nxt = (period_end.replace(day=28) + timedelta(days=4)).replace(day=1)
    due = nxt.replace(day=25)
    while not is_business_day(due):
        due += timedelta(days=1)
    return due


def due_date(period_end: date, override: date | None = None) -> date:
    return override or computed_due_date(period_end)


def get_filing(start: date, end: date, create=True):
    row = KsFiling.query.filter_by(period_start=start).first()
    if row is None and create:
        row = KsFiling(period_start=start, period_end=end)
        db.session.add(row)
        db.session.commit()
    return row


def status_of(filing, end: date, today: date):
    """Plain facts for the top card: return state, payment state and what needs attention."""
    due = due_date(end, filing.due_override if filing else None)
    filed = bool(filing and filing.return_filed_on)
    pay = (filing.payment_status if filing else 'unpaid') or 'unpaid'
    days_left = (due - today).days
    ended = today > end
    if filed:
        return_text, return_tone = f'Filed {pretty(filing.return_filed_on)}', 'good'
    elif not ended:
        return_text, return_tone = 'Period still open', 'quiet'
    elif days_left < 0:
        return_text, return_tone = f'Overdue by {-days_left} day{"" if -days_left == 1 else "s"}', 'bad'
    elif days_left == 0:
        return_text, return_tone = 'Due today', 'bad'
    elif days_left <= 7:
        return_text, return_tone = f'Not filed, due in {days_left} day{"" if days_left == 1 else "s"}', 'warn'
    else:
        return_text, return_tone = f'Not filed, due in {days_left} days', 'quiet'
    if pay == 'paid':
        pay_text, pay_tone = 'Payment cleared', 'good'
    elif pay == 'scheduled':
        settle = filing.payment_settles_on
        if settle and settle < today:
            pay_text, pay_tone = 'Payment was due to settle. Confirm it cleared', 'warn'
        else:
            pay_text = 'Payment scheduled' + (f' for {pretty(settle)}' if settle else '')
            pay_tone = 'good'
    elif filed:
        pay_text, pay_tone = ('Payment not recorded' if days_left >= 0 else 'Payment outstanding'), ('warn' if days_left >= 0 else 'bad')
    else:
        pay_text, pay_tone = 'Nothing to pay yet', 'quiet'
    return {'due': due, 'days_left': days_left, 'ended': ended, 'filed': filed, 'pay': pay,
            'return_text': return_text, 'return_tone': return_tone, 'pay_text': pay_text, 'pay_tone': pay_tone,
            'due_moved': due != date(due.year, due.month, 25) and not (filing and filing.due_override),
            'overridden': bool(filing and filing.due_override)}


def banner(today: date):
    """One line for the top of Profit & Loss and the dashboard: the return that needs the owner next.

    Last period's return if it is not filed yet, otherwise the open period's. Returns None if anything goes wrong,
    so a page never fails because of this banner.
    """
    try:
        freq = frequency()
        start, end = period_for(today, freq)
        p_start, p_end = previous_period(start, freq)
        prev = get_filing(p_start, p_end, create=False)
        if prev is None or not prev.return_filed_on:
            use_start, use_end = p_start, p_end
        else:
            use_start, use_end = start, end
        filing = get_filing(use_start, use_end, create=False)
        st = status_of(filing, use_end, today)
        needs = st['ended'] and (not st['filed'] or st['pay_tone'] in ('warn', 'bad'))
        if st['filed'] and st['pay'] == 'paid':
            needs = False
        label = period_label(use_start, use_end, freq)
        if st['filed']:
            headline = f'Kansas sales tax {label}: filed. {st["pay_text"]}.'
        elif st['ended']:
            headline = f'Kansas sales tax {label}: {st["return_text"].lower()}. Due {pretty(st["due"])}.'
        else:
            headline = f'Next Kansas sales tax return: {label}, due {pretty(st["due"])}.'
        tone = st['return_tone'] if not st['filed'] else st['pay_tone']
        return {'headline': headline, 'tone': tone if st['ended'] else 'quiet', 'needs': needs,
                'url': f'/admin/operations/kansas-tax?start={use_start.isoformat()}'}
    except Exception:
        return None


# ---- the report -------------------------------------------------------------------------------------

def _cents(x):
    return int(x or 0)


def pretty(d):
    """Oct 26, 2026 (no leading zero, works on every system)."""
    return f'{d:%b} {d.day}, {d.year}'


def long_day(d):
    return f'{d:%A, %B} {d.day}'


def build_report(first: date, last: date):
    """Everything on the three Kansas screens for one period, from the ledger. Amounts are whole cents."""
    from models import LedgerEntry, ManualInvoice, Order
    from utils import ledger as L
    from utils import sales_tax

    juris = jurisdiction_map()
    home = pickup_code()
    entries = (LedgerEntry.query
               .filter(LedgerEntry.kc_date >= first, LedgerEntry.kc_date <= last,
                       LedgerEntry.entry_type.in_([L.SALE, L.DISCOUNT, L.REFUND, L.TAX, L.REFUND_TAX])).all())
    sources = {}
    for e in entries:
        key = ('order', e.order_id) if e.order_id else (('invoice', e.invoice_id) if e.invoice_id else ('other', e.id))
        s = sources.setdefault(key, {'key': key, 'sales': 0, 'discounts': 0, 'refunds': 0, 'tax': 0, 'jurisdiction': None,
                                     'taxable': None, 'kc_date': e.kc_date})
        amount = _cents(e.amount_cents)
        if e.entry_type == L.SALE:
            s['sales'] += amount
        elif e.entry_type == L.DISCOUNT:
            s['discounts'] += amount
        elif e.entry_type == L.REFUND:
            s['refunds'] += amount
        else:
            s['tax'] += amount
        s['jurisdiction'] = s['jurisdiction'] or e.jurisdiction
        if s['taxable'] is None:
            s['taxable'] = e.taxable
    order_ids = [k[1] for k in sources if k[0] == 'order']
    invoice_ids = [k[1] for k in sources if k[0] == 'invoice']
    orders = {o.id: o for o in Order.query.filter(Order.id.in_(order_ids)).all()} if order_ids else {}
    invoices = {i.id: i for i in ManualInvoice.query.filter(ManualInvoice.id.in_(invoice_ids)).all()} if invoice_ids else {}

    review, rows, line_m, exempt = [], {}, {'amount': 0, 'orders': []}, {'amount': 0, 'orders': []}
    detail = []
    for s in sorted(sources.values(), key=lambda v: (v['kc_date'], str(v['key']))):
        kind, ident = s['key']
        order = orders.get(ident) if kind == 'order' else None
        invoice = invoices.get(ident) if kind == 'invoice' else None
        label = (f'Order {order.order_number}' if order else f'Invoice {invoice.number}' if invoice and getattr(invoice, 'number', None)
                 else f'Invoice {ident}' if invoice else 'Other entry')
        url = f'/admin/orders/{ident}' if order else (f'/admin/invoices/{ident}' if invoice else '')
        net = s['sales'] + s['discounts'] + s['refunds']
        jur = s['jurisdiction'] or (order.tax_jurisdiction if order else None)
        code = (order.ks_code if order and order.ks_code else home)
        s.update(code=code, label=label, url=url, net=net, deduction=0, deduction_line=None)
        if jur == sales_tax.OUT_OF_STATE:
            s.update(deduction=net, deduction_line='M')
            line_m['amount'] += net
            line_m['orders'].append({'label': label, 'url': url, 'amount': net, 'tracking': (order.tracking_number if order else '') or '',
                                     'state': (order.shipping_state if order else '') or ''})
            if order is not None and not (order.tracking_number or '').strip():
                review.append({'kind': 'proof', 'text': f'{label} shipped out of state with no tracking number saved. Kansas wants proof of delivery for Line M.',
                               'url': url, 'fix': 'Add tracking'})
        elif jur == sales_tax.EXEMPT:
            s.update(deduction=net, deduction_line='EX')
            exempt['amount'] += net
            exempt['orders'].append({'label': label, 'url': url, 'amount': net})
        elif jur == sales_tax.KS_SHIPPED and not (order and order.ks_code):
            review.append({'kind': 'destination', 'text': f'{label} shipped within Kansas. Pick the jurisdiction code for where it was delivered. Until then it is counted under {home}.',
                           'url': url, 'fix': 'Choose code', 'order_id': ident})
        elif jur is None:
            review.append({'kind': 'older', 'text': f'{label} has no tax label yet, so it is counted under {home}.', 'url': url, 'fix': 'Open'})
        if code not in juris:
            review.append({'kind': 'code', 'text': f'{label} uses code {code}, which is not in your jurisdiction list.', 'url': url, 'fix': 'Open'})
        r = rows.setdefault(code, {'code': code, 'gross': 0, 'refunds': 0, 'deductions': 0, 'consumed': 0, 'collected': 0, 'orders': 0})
        r['gross'] += s['sales'] + s['discounts']
        r['refunds'] += s['refunds']
        r['deductions'] += s['deduction']
        r['collected'] += s['tax']
        r['orders'] += 1 if s['sales'] else 0
        detail.append(s)

    from utils import inventory_adjust as IA
    adjustments = IA.for_period(first, last)
    consumed = IA.consumed_cents(adjustments)
    if consumed:
        rows.setdefault(home, {'code': home, 'gross': 0, 'refunds': 0, 'deductions': 0, 'consumed': 0, 'collected': 0, 'orders': 0})
        rows[home]['consumed'] += consumed
    undecided = [a for a in adjustments if a.treatment == 'review']
    if undecided:
        worth = sum(a.total_cost_cents for a in undecided)
        review.append({'kind': 'adjustment', 'text': f'{len(undecided)} inventory adjustment{"" if len(undecided) == 1 else "s"} ({L.dollars(worth)} at cost) still need a decision on whether they are reported as merchandise consumed.',
                       'url': f'/admin/operations/adjustments?start={first.isoformat()}', 'fix': 'Decide'})
    table = []
    for code in sorted(rows):
        r = rows[code]
        j = juris.get(code)
        rate = float(j.rate_percent) if j else 0.0
        net_taxable = r['gross'] + r['refunds'] - r['deductions'] + r['consumed']
        r.update(name=(j.name if j else 'Unknown'), rate=rate, net=net_taxable, calc=int(round(net_taxable * rate / 100.0)),
                 calc_consumed=int(round(r['consumed'] * rate / 100.0)))
        r['diff'] = r['calc'] - r['collected']
        table.append(r)
    totals = {k: sum(r[k] for r in table) for k in ('gross', 'refunds', 'deductions', 'consumed', 'net', 'calc', 'collected', 'orders')}
    totals['diff'] = totals['calc'] - totals['collected']
    totals['calc_consumed'] = sum(r['calc_consumed'] for r in table)
    if totals['diff'] - totals['calc_consumed'] > 100:
        review.append({'kind': 'short', 'text': f'Tax collected is {L.dollars(totals["diff"] - totals["calc_consumed"])} less than the rate calls for on your sales. Customers may have been charged an older rate. You owe Kansas the calculated amount.',
                       'url': '/admin/operations/ledger', 'fix': 'See entries'})
    return {'first': first, 'last': last, 'rows': table, 'line_m': line_m, 'exempt': exempt, 'totals': totals,
            'review': review, 'has_activity': bool(sources or adjustments), 'detail': detail,
            'adjustments': len(adjustments)}


def snapshot_of(report):
    """A plain, frozen copy of the report that can be stored and shown later."""
    keep = {k: report[k] for k in ('rows', 'line_m', 'exempt', 'totals')}
    keep['period'] = [report['first'].isoformat(), report['last'].isoformat()]
    keep['saved'] = datetime.utcnow().isoformat(timespec='seconds')
    return json.dumps(keep)


def parse_cents(text):
    """'86.30' or '$1,086.30' to cents. None when blank. Raises ValueError for anything else."""
    cleaned = (text or '').replace('$', '').replace(',', '').strip()
    if not cleaned:
        return None
    return int(round(float(cleaned) * 100))


def parse_date(text):
    text = (text or '').strip()
    if not text:
        return None
    return datetime.strptime(text, '%Y-%m-%d').date()


# ---- reminders ---------------------------------------------------------------------------------------

def _sent(filing):
    try:
        return set(json.loads(filing.reminders_sent or '[]'))
    except (ValueError, TypeError):
        return set()


def due_reminders(today: date):
    """[(filing, key, title, detail)] for reminders that should go out today and have not gone out yet."""
    out = []
    freq = frequency()
    start, end = period_for(today, freq)
    periods = [previous_period(start, freq)]
    if today > end:
        periods.append((start, end))
    seen = set()
    for p_start, p_end in periods:
        if p_start in seen or p_end >= today:
            continue
        seen.add(p_start)
        f = get_filing(p_start, p_end)
        st = status_of(f, p_end, today)
        sent = _sent(f)
        label = period_label(p_start, p_end, freq)
        link_note = f'Open the {label} report to see exactly what to enter.'
        if not st['filed']:
            days = st['days_left']
            key = None
            if days in reminder_days() or days == 0:
                key = f'return:{days}'
            elif days < 0 and (-days) % 3 == 1:
                key = f'overdue:{-days}'
            if key and key not in sent:
                if days > 0:
                    title = f'Kansas sales tax for {label} is due in {days} day{"" if days == 1 else "s"}'
                elif days == 0:
                    title = f'Kansas sales tax for {label} is due today'
                else:
                    title = f'Kansas sales tax for {label} is {-days} day{"" if days == -1 else "s"} overdue'
                detail = f'Due {long_day(st["due"])}. A return is needed even when there were no sales. ' + link_note
                out.append((f, key, title, detail))
        elif st['pay'] == 'scheduled' and f.payment_settles_on and f.payment_settles_on < today and 'verify' not in sent:
            out.append((f, 'verify', f'Check that your {label} Kansas tax payment cleared',
                        f'It was due to settle {pretty(f.payment_settles_on)}. Mark it cleared once you see it in your bank. ' + link_note))
    return out


def run_reminders(app, today: date | None = None):
    """Send each due reminder once: a notice in the admin and an email. Returns how many went out."""
    from utils import ledger as L
    from utils.admin_notifications import create_notification
    today = today or L.kc_today()
    sent_count = 0
    for filing, key, title, detail in due_reminders(today):
        url = f'/admin/operations/kansas-tax?start={filing.period_start.isoformat()}'
        create_notification(kind='tax', title=title, preview=detail, body=detail, url=url, commit=False)
        keys = _sent(filing)
        keys.add(key)
        filing.reminders_sent = json.dumps(sorted(keys))
        db.session.commit()
        sent_count += 1
        try:
            from flask_mail import Message
            from utils.mailer import admin_base_url, admin_recipient, send
            link = admin_base_url(app) + url
            body = f'{title}.\n\n{detail}\n\n{link}\n\nPurposefully Made KC'
            send(app, Message(subject=title, recipients=[admin_recipient(app)], body=body), description='Kansas sales tax reminder')
        except Exception as exc:                      # a mail problem never stops the notice or the next reminder
            app.logger.warning('kansas tax reminder email failed: %s', exc)
    return sent_count
