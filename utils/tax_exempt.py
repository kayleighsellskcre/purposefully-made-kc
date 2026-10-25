"""Tax-exempt customer accounts (schools, churches, nonprofits) and the sales tax filing reminder.

An exemption belongs to a customer account. When that customer is signed in, checkout charges no sales tax and the order is
labelled as tax exempt. A certificate can expire, and an expired or switched-off exemption charges tax again.
"""
from __future__ import annotations

from datetime import date, timedelta

from models import TaxExemption, User, db
from utils import ledger as L
from utils.site_settings import get_setting, set_setting

FREQUENCY_KEY, DUE_DAY_KEY = 'sales_tax_filing', 'sales_tax_due_day'
FREQUENCIES = [('', 'No reminder'), ('monthly', 'Every month'), ('quarterly', 'Every quarter'), ('annual', 'Once a year')]


def add_exemption(*, email, organization=None, certificate_number=None, certificate_url=None, expires_on=None, note=None):
    email = (email or '').strip().lower()
    user = User.query.filter(db.func.lower(User.email) == email).first() if email else None
    if user is None:
        raise ValueError('There is no account with that email. Ask them to create an account first, then add them here.')
    row = TaxExemption.query.filter_by(user_id=user.id).first() or TaxExemption(user_id=user.id)
    row.organization = (organization or '').strip()[:200] or None
    row.certificate_number = (certificate_number or '').strip()[:80] or None
    if certificate_url:
        row.certificate_url = certificate_url
    row.expires_on = expires_on
    row.note = (note or '').strip() or None
    row.active = True
    db.session.add(row)
    db.session.commit()
    return row


def set_active(exemption_id, active):
    row = db.session.get(TaxExemption, int(exemption_id))
    if row is None:
        raise ValueError('That exemption was not found.')
    row.active = bool(active)
    db.session.commit()
    return row


def status(row, today=None):
    today = today or L.kc_today()
    if not row.active:
        return 'off'
    if row.expires_on and row.expires_on < today:
        return 'expired'
    if row.expires_on and row.expires_on <= today + timedelta(days=45):
        return 'soon'
    return 'ok'


def needing_attention(today=None):
    """Active exemptions that have expired or expire within 45 days."""
    today = today or L.kc_today()
    return [r for r in TaxExemption.query.filter_by(active=True).all() if status(r, today) in ('expired', 'soon')]


# ---- the filing reminder ---------------------------------------------------------------------------

def save_filing(frequency, due_day):
    if frequency not in dict(FREQUENCIES):
        raise ValueError('Choose how often you file.')
    day = int(due_day or 0)
    if frequency and not (1 <= day <= 28):
        raise ValueError('Enter the day of the month the return is due (1 to 28). Your Kansas account shows it.')
    set_setting(FREQUENCY_KEY, frequency, 'How often the sales tax return is filed')
    set_setting(DUE_DAY_KEY, str(day or ''), 'Day of the month the sales tax return is due')


def filing_settings():
    day = (get_setting(DUE_DAY_KEY, '') or '').strip()
    return {'frequency': get_setting(FREQUENCY_KEY, '') or '', 'due_day': int(day) if day.isdigit() else None}


def filing_line(today=None):
    """A sentence for the monthly close when a return covering last month is due, else None."""
    cfg = filing_settings()
    if not cfg['frequency'] or not cfg['due_day']:
        return None
    today = today or L.kc_today()
    last = today.replace(day=1) - timedelta(days=1)                       # the month that just ended
    if cfg['frequency'] == 'quarterly' and last.month % 3 != 0:
        return None
    if cfg['frequency'] == 'annual' and last.month != 12:
        return None
    first = {'monthly': last.replace(day=1), 'quarterly': date(last.year, last.month - 2, 1), 'annual': date(last.year, 1, 1)}[cfg['frequency']]
    tax = L.pnl(first, last)['tax_collected']
    due = date(today.year, today.month, cfg['due_day'])
    return (f"Your sales tax return for {first.strftime('%B %Y') if first.month == last.month else first.strftime('%B') + ' to ' + last.strftime('%B %Y')} "
            f"is due {due.strftime('%B')} {due.day}. You collected {L.dollars(tax)}; set it aside.")
