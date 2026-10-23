"""Estimated ready date: today plus a number of business days the owner can change in Site settings."""
import time
from datetime import date, datetime, timedelta

SETTING_KEY = 'ready_business_days'
DEFAULT_DAYS = 15
MIN_DAYS, MAX_DAYS = 3, 60
_TTL_SECONDS = 300
_CACHE = {'at': 0.0, 'days': DEFAULT_DAYS}


def add_business_days(start, days):
    """Skip Saturdays and Sundays."""
    current = start
    remaining = int(days)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def get_business_days():
    """The saved number of business days, cached for a few minutes."""
    now = time.time()
    if now - _CACHE['at'] < _TTL_SECONDS:
        return _CACHE['days']
    days = DEFAULT_DAYS
    try:
        from models import SystemSettings
        row = SystemSettings.query.filter_by(key=SETTING_KEY).first()
        if row and (row.value or '').strip().isdigit():
            days = max(MIN_DAYS, min(MAX_DAYS, int(row.value)))
    except Exception:
        days = DEFAULT_DAYS
    _CACHE.update(at=now, days=days)
    return days


def save_business_days(value):
    """Store a new value (clamped) and clear the cache. Returns the saved number."""
    from models import db, SystemSettings
    days = max(MIN_DAYS, min(MAX_DAYS, int(value)))
    row = SystemSettings.query.filter_by(key=SETTING_KEY).first()
    if row is None:
        row = SystemSettings(key=SETTING_KEY, description='Business days from order to ready')
        db.session.add(row)
    row.value = str(days)
    db.session.commit()
    _CACHE['at'] = 0.0
    return days


def format_day(d):
    return f'{d.strftime("%A, %B")} {d.day}'


def ready_by(start=None):
    """The estimated ready date for an order placed on `start` (default today)."""
    if isinstance(start, datetime):
        start = start.date()
    return add_business_days(start or date.today(), get_business_days())


def ready_note():
    """One calm line for product, cart and checkout pages."""
    return f'Estimated ready by {format_day(ready_by())}.'
