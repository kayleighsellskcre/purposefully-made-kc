"""Display UTC datetimes in Kansas City time."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo('America/Chicago')


def to_central(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CENTRAL)


def format_central(dt, fmt='%B %d, %Y at %I:%M %p'):
    local = to_central(dt)
    if not local:
        return ''
    return local.strftime(fmt).lstrip('0').replace(' 0', ' ')
