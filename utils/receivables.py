"""Money customers still owe on hand-made invoices: how old each is, a log of cash/Venmo/check payments, and gentle
reminders at 7, 14 and 30 days.

A payment recorded here adds to the invoice and is written to the books the same day (cash basis). Customer reminders only
go out when the owner has switched them on.
"""
from __future__ import annotations

from datetime import datetime, timezone

from models import InvoicePayment, ManualInvoice, db
from utils import ledger as L
from utils.site_settings import get_flag, set_setting

REMINDER_DAYS = (7, 14, 30)
MIN_DAYS_BETWEEN = 5
FLAG = 'invoice_reminders_on'
METHODS = ['Cash', 'Venmo', 'Check', 'Card', 'Other']
BUCKETS = [('0 to 7 days', 0, 7), ('8 to 14 days', 8, 14), ('15 to 30 days', 15, 30), ('Over 30 days', 31, 10 ** 6)]


def reminders_on():
    return get_flag(FLAG, False)


def set_reminders(on):
    set_setting(FLAG, '1' if on else '0', 'Email customers a reminder when an invoice is 7, 14 and 30 days old')


def age_days(inv, today=None):
    today = today or L.kc_today()
    issued = inv.issued_at or inv.created_at
    return max(0, (today - L.kc_day(issued)).days) if issued else 0


def open_rows(today=None):
    from utils.receipts import doc_from_invoice
    today = today or L.kc_today()
    rows = []
    for inv in ManualInvoice.query.order_by(ManualInvoice.issued_at).all():
        doc = doc_from_invoice(inv)
        if doc['balance'] <= 0.004:
            continue
        rows.append({'inv': inv, 'doc': doc, 'balance_cents': L.to_cents(doc['balance']), 'age': age_days(inv, today)})
    return rows


def buckets(rows):
    out = []
    for label, low, high in BUCKETS:
        mine = [r for r in rows if low <= r['age'] <= high]
        out.append({'label': label, 'count': len(mine), 'cents': sum(r['balance_cents'] for r in mine)})
    return out


def record_payment(invoice_id, amount_dollars, method, paid_on=None, note=None):
    """Add a payment (cash, Venmo, check) to an invoice and put it on the books. Returns the log entry."""
    from utils.receipts import doc_from_invoice
    inv = db.session.get(ManualInvoice, int(invoice_id))
    if inv is None:
        raise ValueError('That invoice was not found.')
    cents = L.to_cents(amount_dollars)
    if cents <= 0:
        raise ValueError('The amount must be more than zero.')
    if method not in METHODS:
        raise ValueError('Choose how it was paid.')
    balance = L.to_cents(doc_from_invoice(inv)['balance'])
    if cents > balance:
        raise ValueError(f'That is more than the {L.dollars(balance)} still owed on {inv.number}.')
    today = L.kc_today()
    first = not inv.paid_at and (inv.amount_paid or 0) <= 0
    day = paid_on if (first and paid_on and paid_on <= today) else today      # only a first payment can be dated earlier
    inv.amount_paid = round((inv.amount_paid or 0) + cents / 100, 2)
    inv.payment_method = method
    if first:
        noon = datetime.combine(day, datetime.min.time()).replace(hour=12, tzinfo=L.CENTRAL).astimezone(timezone.utc)
        inv.paid_at = noon.replace(tzinfo=None)
    row = InvoicePayment(invoice_id=inv.id, amount_cents=cents, method=method, paid_on=day, note=(note or '').strip()[:200] or None)
    db.session.add(row)
    db.session.commit()
    L.sync_all(force=True)
    return row


def target_stage(age):
    stage = 0
    for i, days in enumerate(REMINDER_DAYS, start=1):
        if age >= days:
            stage = i
    return stage


def send_reminder(inv, stage):
    """Email one reminder. Returns True if it was handed to the mailer."""
    from utils import invoice_emails
    from utils.invoice_pay import ensure_token
    if '@' not in (inv.email or ''):
        return False
    ensure_token(inv)
    return bool(invoice_emails.send_reminder(inv, stage))


def run_reminders(today=None):
    """Send the reminders that are due, once each. Does nothing unless reminders are switched on."""
    if not reminders_on():
        return 0
    today = today or L.kc_today()
    sent = 0
    for row in open_rows(today):
        inv = row['inv']
        stage = target_stage(row['age'])
        if stage <= (inv.reminder_stage or 0):
            continue
        if inv.reminder_sent_at and (today - L.kc_day(inv.reminder_sent_at)).days < MIN_DAYS_BETWEEN:
            continue
        if send_reminder(inv, stage):
            inv.reminder_stage, inv.reminder_sent_at = stage, datetime.utcnow()
            db.session.commit()
            sent += 1
    return sent
