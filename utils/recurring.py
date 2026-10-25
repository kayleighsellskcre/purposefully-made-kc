"""Monthly bills: one real expense is made for each month a rule covers, once, and never again.

An expense you void stays on record and is not made a second time. Changing a rule only affects months not yet made.
"""
from __future__ import annotations

from datetime import date

from models import Expense, RecurringExpense, db
from utils import ledger as L

MAX_MONTHS_BACK = 24


def _month_end_day(year, month):
    return L._month_end(date(year, month, 1)).day


def _months(start, today):
    y, m = start.year, start.month
    while (y, m) <= (today.year, today.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def add_rule(*, vendor, amount_dollars, category, payment_method=None, note=None, day_of_month=1, start_date=None):
    cents = L.to_cents(amount_dollars)
    vendor = (vendor or '').strip()
    if not vendor:
        raise ValueError('Who is the bill from?')
    if cents <= 0:
        raise ValueError('The amount must be more than zero.')
    if category not in L.EXPENSE_LINE:
        raise ValueError('Choose a category.')
    day = min(28, max(1, int(day_of_month or 1)))
    start = (start_date or L.kc_today()).replace(day=1)
    rule = RecurringExpense(vendor=vendor[:120], amount_cents=cents, category=category, payment_method=payment_method,
                            note=(note or '').strip() or None, day_of_month=day, start_date=start, active=True)
    db.session.add(rule)
    db.session.commit()
    return rule


def set_active(rule_id, active):
    rule = db.session.get(RecurringExpense, int(rule_id))
    if rule is None:
        raise ValueError('That bill was not found.')
    rule.active = bool(active)
    db.session.commit()
    return rule


def make_due(today=None):
    """Make every expense that has come due and does not exist yet. Returns how many were made."""
    today = today or L.kc_today()
    earliest = date(today.year - MAX_MONTHS_BACK // 12, today.month, 1)
    made = 0
    for rule in RecurringExpense.query.filter_by(active=True).all():
        have = {(e.expense_date.year, e.expense_date.month)
                for e in Expense.query.filter(Expense.recurring_id == rule.id).all()}
        for y, m in _months(max(rule.start_date, earliest), today):
            if (y, m) in have:
                continue
            day = date(y, m, min(rule.day_of_month, _month_end_day(y, m)))
            if day > today:
                continue
            L.add_expense(when_day=day, vendor=rule.vendor, amount_dollars=rule.amount_cents / 100, category=rule.category,
                          payment_method=rule.payment_method, note=rule.note or 'Monthly bill', recurring_id=rule.id)
            made += 1
    return made
