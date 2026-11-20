"""Tell admin about a small problem the page can live without.

Some steps (a price refresh, a count on a page) are allowed to fail without breaking the page. They used to fail
in silence. Call `report_quiet('what was being done')` inside the `except` and the problem is written to the Site
Errors list (the dashboard then shows it) and to the log. It never raises, never emails, and never touches the
caller's own database work: it saves through its own connection.
"""
from __future__ import annotations

import secrets
import traceback
from datetime import datetime, timedelta


def report_quiet(what: str) -> None:
    try:
        from flask import current_app, has_request_context, request
        from models import SiteError, db
        stack = traceback.format_exc()
        last = stack.strip().splitlines()[-1] if stack.strip() else 'unknown problem'
        message = f'Small problem (the page still worked) while {what}: {last}'[:2000]
        current_app.logger.warning('quiet problem: %s', message)
        path = request.path if has_request_context() else '?'
        method = request.method if has_request_context() else '?'
        with db.engine.begin() as conn:                         # its own connection, so the page's work is untouched
            recent = conn.execute(SiteError.__table__.select().where(
                SiteError.__table__.c.message == message,
                SiteError.__table__.c.created_at >= datetime.utcnow() - timedelta(hours=6)).limit(1)).first()
            if recent:                                          # the same problem was already listed: do not pile up copies
                return
            conn.execute(SiteError.__table__.insert().values(
                error_id=secrets.token_hex(8), path=(path or '?')[:500], method=(method or '?')[:10], message=message,
                traceback=stack[:20000], notified=False, created_at=datetime.utcnow()))
    except Exception:
        pass
