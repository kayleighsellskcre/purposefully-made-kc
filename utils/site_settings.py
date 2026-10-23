"""Small owner-editable settings kept in the SystemSettings table (one key, one text value)."""
from models import db, SystemSettings


def get_setting(key, default=''):
    try:
        row = SystemSettings.query.filter_by(key=key).first()
    except Exception:
        return default
    return row.value if row is not None and row.value is not None else default


def set_setting(key, value, description=None):
    row = SystemSettings.query.filter_by(key=key).first()
    if row is None:
        row = SystemSettings(key=key, description=description or key)
        db.session.add(row)
    row.value = value
    db.session.commit()
    return row


def get_flag(key, default=True):
    raw = get_setting(key, None)
    if raw is None:
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
