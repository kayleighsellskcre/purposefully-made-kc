"""The monthly close: on the 2nd, an email to the owner with last month's numbers, what needs a look, and the P&L PDF."""
from __future__ import annotations

from datetime import date, timedelta

from flask import current_app

from models import Expense
from utils import ledger as L
from utils import receivables, year_end as Y
from utils.site_settings import get_setting, set_setting

SENT_KEY = 'monthly_close_sent'


def previous_month(today=None):
    today = today or L.kc_today()
    last = today.replace(day=1) - timedelta(days=1)
    first = last.replace(day=1)
    return first, last, first.strftime('%B %Y')


def summary(today=None):
    """Last month's figures and the things to look at, as plain data."""
    today = today or L.kc_today()
    first, last, label = previous_month(today)
    p = L.pnl(first, last)
    before_first = (first - timedelta(days=1)).replace(day=1)
    before = L.pnl(before_first, first - timedelta(days=1))
    ytd = L.pnl(date(first.year, 1, 1), last)
    looks = []
    missing = Expense.query.filter(Expense.expense_date >= first, Expense.expense_date <= last, Expense.voided_at.is_(None),
                                   Expense.receipt_url.is_(None)).count()
    if missing:
        looks.append(f"{missing} expense{'s' if missing != 1 else ''} from {label} {'have' if missing != 1 else 'has'} no receipt yet.")
    est = L.estimate_counts()
    if est['fees'] or est['cogs']:
        looks.append(f"{est['fees']} orders still use an estimated processing fee and {est['cogs']} an estimated cost of goods.")
    owed = receivables.open_rows(today)
    if owed:
        old = [r for r in owed if r['age'] > 30]
        looks.append(f"{len(owed)} open invoice{'s' if len(owed) != 1 else ''} worth {L.dollars(sum(r['balance_cents'] for r in owed))}"
                     + (f", {len(old)} over 30 days old." if old else "."))
    balance = Y.processor_summary(first.year)['stripe']['totals']['balance']
    if abs(balance) > 5000:
        looks.append(f"Stripe sales less fees and refunds are {L.dollars(abs(balance))} {'more' if balance > 0 else 'less'} than its payouts so far this year.")
    return {'first': first, 'last': last, 'label': label, 'p': p, 'before': before, 'ytd': ytd, 'looks': looks}


def send_close(today=None, force=False):
    """Email the close for last month once. Returns True if it was sent. force=True resends."""
    from utils.business_info import BUSINESS
    from utils.mailer import admin_base_url, admin_recipient
    from utils.report_pdf import build_pnl_pdf
    from utils.sponsor_emails import _safe, _send
    app = current_app._get_current_object()
    today = today or L.kc_today()
    first, last, label = previous_month(today)
    month_key = first.strftime('%Y-%m')
    if not force and get_setting(SENT_KEY, '') == month_key:
        return False
    L.sync_all(force=True)
    s = summary(today)
    p, b, ytd = s['p'], s['before'], s['ytd']
    change = p['net_profit'] - b['net_profit']
    pdf = build_pnl_pdf(p, label, BUSINESS, channels=L.sales_by_channel(first, last), estimates=L.estimate_counts())
    lines = [f"Here is how {label} closed, on a cash basis in Kansas City time.",
             (f"Net profit was {L.dollars(p['net_profit'])}, "
              f"{'up' if change >= 0 else 'down'} {L.dollars(abs(change))} from the month before.")]
    lines += (['Worth a look: ' + ' '.join(s['looks'])] if s['looks'] else ['Nothing needs a look. Everything checked is in order.'])
    sent = _safe(
        _send, admin_recipient(app), f"{label} is closed: net profit {L.dollars(p['net_profit'])}", f"{label} close",
        lines,
        button={'label': 'Open the reports', 'url': f"{admin_base_url(app)}/admin/operations/reports"},
        details=[('Net sales', L.dollars(p['net_sales'])), ('Cost of goods', L.dollars(p['cogs'])),
                 ('Expenses', L.dollars(p['total_expenses'])), ('Net profit', L.dollars(p['net_profit'])),
                 ('Sales tax to set aside', L.dollars(p['tax_collected'])),
                 (f"Year to date profit", L.dollars(ytd['net_profit']))],
        attachments=[(f"Profit-and-Loss-{label.replace(' ', '-')}.pdf", 'application/pdf', pdf)])
    if sent:
        set_setting(SENT_KEY, month_key, 'The last month whose close email was sent')
    return bool(sent)
