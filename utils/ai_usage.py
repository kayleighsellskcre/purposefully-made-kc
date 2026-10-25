"""AI Design Studio use per day, so the cost can be watched. An email goes to the owner if one day runs unusually high."""
from __future__ import annotations

from datetime import timedelta

from flask import current_app
from sqlalchemy import func

from models import AiGeneration, db
from utils import ledger as L
from utils.site_settings import get_setting, set_setting

THRESHOLD_KEY, ALERT_DAY_KEY = 'ai_daily_alert', 'ai_alert_day'
DEFAULT_THRESHOLD = 30


def threshold():
    raw = (get_setting(THRESHOLD_KEY, '') or '').strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_THRESHOLD


def save_threshold(value):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError('Enter a whole number, like 30.')
    if not 1 <= number <= 10000:
        raise ValueError('Enter a number between 1 and 10,000.')
    set_setting(THRESHOLD_KEY, str(number), 'Email me when the AI Design Studio is used this many times in one day')
    return number


def today_count(day=None):
    return AiGeneration.query.filter(AiGeneration.kc_date == (day or L.kc_today())).count()


def daily_counts(days=30, today=None):
    """[(day, started, failed)] for the last N days, newest first, including quiet days."""
    today = today or L.kc_today()
    first = today - timedelta(days=days - 1)
    rows = (db.session.query(AiGeneration.kc_date, func.count(AiGeneration.id),
                             func.sum(db.case((AiGeneration.ok.is_(False), 1), else_=0)))
            .filter(AiGeneration.kc_date >= first).group_by(AiGeneration.kc_date).all())
    by_day = {d: (int(n), int(f or 0)) for d, n, f in rows}
    return [(today - timedelta(days=i), *by_day.get(today - timedelta(days=i), (0, 0))) for i in range(days)]


def log_start(job_id, had_reference=False):
    """Record a run when it starts. Never lets logging break the studio."""
    try:
        day = L.kc_today()
        db.session.add(AiGeneration(job_id=job_id, kc_date=day, had_reference=bool(had_reference)))
        db.session.commit()
        maybe_alert(day)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('AI usage could not be logged')


def log_finish(job_id, ok):
    try:
        row = AiGeneration.query.filter_by(job_id=job_id).first()
        if row is not None:
            row.ok = bool(ok)
            db.session.commit()
    except Exception:
        db.session.rollback()


def maybe_alert(day):
    """Email the owner once on a day the count reaches the limit. Returns True if an email was sent."""
    count = today_count(day)
    if count < threshold() or get_setting(ALERT_DAY_KEY, '') == day.isoformat():
        return False
    from utils.mailer import admin_base_url, admin_recipient
    from utils.sponsor_emails import _safe, _send
    app = current_app._get_current_object()
    sent = _safe(_send, admin_recipient(app), f'AI Design Studio: {count} designs today', 'The AI studio is busy today',
                 [f'The AI Design Studio has been used {count} times today, which is at or above your limit of {threshold()}. '
                  'Each design costs a little, so this is worth a look in case it is being used more than you expect.'],
                 button={'label': 'See the daily use', 'url': f'{admin_base_url(app)}/admin/operations/ai-usage'})
    if sent:
        set_setting(ALERT_DAY_KEY, day.isoformat(), 'The last day the AI studio alert was sent')
    return bool(sent)
