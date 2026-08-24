"""Record customer-facing 500s and notify admin with a correlation ID."""
import secrets
import socket
import traceback
from datetime import datetime

from flask import has_request_context, request
from flask_login import current_user


def new_error_id():
    return secrets.token_hex(8)


def _request_context():
    if not has_request_context():
        return {
            'path': '?',
            'method': '?',
            'query': '',
            'referrer': '',
            'user_agent': '',
            'user_id': None,
            'user_email': '',
        }
    user_id = None
    user_email = ''
    try:
        if current_user.is_authenticated:
            user_id = getattr(current_user, 'id', None)
            user_email = getattr(current_user, 'email', '') or ''
    except Exception:
        pass
    return {
        'path': request.path or '?',
        'method': request.method or '?',
        'query': request.query_string.decode('utf-8', errors='replace') if request.query_string else '',
        'referrer': (request.referrer or '')[:500],
        'user_agent': (request.headers.get('User-Agent') or '')[:500],
        'user_id': user_id,
        'user_email': user_email,
    }


def _exception_text(error):
    original = getattr(error, 'original_exception', None) or error
    return f'{type(original).__name__}: {original}'


# Query/path keys that must never appear in the admin Errors UI.
_SENSITIVE_QUERY_KEYS = (
    'token', 'reset', 'password', 'passwd', 'secret', 'key', 'session',
    'code', 'auth', 'email', 'api_key', 'apikey', 'access_token', 'refresh',
)


def redact_query_string(query):
    """Mask sensitive query values for display (and safer DB storage)."""
    if not query:
        return ''
    from urllib.parse import parse_qsl, urlencode
    try:
        pairs = parse_qsl(query, keep_blank_values=True)
    except Exception:
        return '[redacted]'
    safe = []
    for k, v in pairs:
        key_l = (k or '').lower()
        if any(s in key_l for s in _SENSITIVE_QUERY_KEYS):
            safe.append((k, '***'))
        else:
            safe.append((k, v[:80] if isinstance(v, str) else v))
    return urlencode(safe)[:400]


def safe_error_message(message, limit=180):
    """Short, single-line message for the Errors UI — no stack / path dumps."""
    text = (message or '').replace('\r', ' ').replace('\n', ' ').strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + '…'
    return text


def safe_referrer_display(referrer):
    """Show origin + path only — strip query/fragment that may hold tokens."""
    if not referrer:
        return ''
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(referrer)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))[:300]
    except Exception:
        return ''


def record_and_notify(app, error, error_id=None):
    """Log, persist, and email/SMS the admin. Never raises. Returns (error_id, notified)."""
    error_id = error_id or new_error_id()
    ctx = _request_context()
    message = _exception_text(error)
    stack = traceback.format_exc()
    if stack.strip() == 'NoneType: None':
        original = getattr(error, 'original_exception', None) or error
        stack = ''.join(traceback.format_exception(type(original), original, original.__traceback__))

    app.logger.error(
        'server_error id=%s %s %s%s user=%s ua=%s :: %s\n%s',
        error_id,
        ctx['method'],
        ctx['path'],
        f'?{ctx["query"]}' if ctx['query'] else '',
        ctx['user_id'] or 'anon',
        ctx['user_agent'][:120],
        message,
        stack,
    )

    saved = _save_error(app, error_id, ctx, message, stack)
    notified = False
    if saved:
        notified = _notify_admin(app, error_id, ctx, message, stack)
        if notified:
            try:
                saved.notified = True
                from models import db
                db.session.commit()
            except Exception:
                try:
                    from models import db
                    db.session.rollback()
                except Exception:
                    pass
    else:
        notified = _notify_admin(app, error_id, ctx, message, stack)

    return error_id, notified


def _save_error(app, error_id, ctx, message, stack):
    try:
        from models import SiteError, db
        row = SiteError(
            error_id=error_id,
            path=ctx['path'][:500],
            method=ctx['method'][:10],
            query_string=redact_query_string(ctx['query'] or '')[:500],
            referrer=safe_referrer_display(ctx['referrer']) or (ctx['referrer'] or '')[:300],
            user_agent=ctx['user_agent'],
            user_id=ctx['user_id'],
            message=message[:2000],
            traceback=stack[:20000],
            notified=False,
            created_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        return row
    except Exception as exc:
        app.logger.exception('Could not persist SiteError %s: %s', error_id, exc)
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass
        return None


def _notify_admin(app, error_id, ctx, message, stack):
    emailed = _email_admin(app, error_id, ctx, message, stack)
    texted = _sms_admin(app, error_id, ctx, message)
    return bool(emailed or texted)


def _email_admin(app, error_id, ctx, message, stack):
    admin_email = (app.config.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip()
    mail = app.extensions.get('mail')
    if not mail or not app.config.get('MAIL_SERVER') or not app.config.get('MAIL_PASSWORD') or not admin_email:
        return False
    sender = (
        app.config.get('MAIL_DEFAULT_SENDER')
        or app.config.get('MAIL_USERNAME')
        or 'noreply@purposefullymadekc.com'
    )
    url = f"{ctx['path']}"
    if ctx['query']:
        url += f"?{ctx['query']}"
    body = (
        f"A customer hit a 500 on purposefullymadekc.com.\n\n"
        f"Reference ID: {error_id}\n"
        f"When: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"Request: {ctx['method']} {url}\n"
        f"Referrer: {ctx['referrer'] or '(none)'}\n"
        f"Customer: {ctx['user_email'] or 'signed out'} (id={ctx['user_id'] or 'anon'})\n"
        f"Device: {ctx['user_agent']}\n\n"
        f"{message}\n\n"
        f"{stack}\n"
    )
    timeout = min(int(app.config.get('MAIL_TIMEOUT') or 20), 12)
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        from flask_mail import Message
        mail.send(Message(
            subject=f"PMKC 500 — {error_id} — {ctx['path']}",
            recipients=[admin_email],
            body=body,
            sender=sender,
        ))
        return True
    except Exception as exc:
        app.logger.exception('Admin 500 email failed for %s: %s', error_id, exc)
        return False
    finally:
        socket.setdefaulttimeout(previous)


def _sms_admin(app, error_id, ctx, message):
    try:
        from utils.sms import send_server_error_alert
        return bool(send_server_error_alert(app, error_id, ctx['path'], message))
    except Exception:
        return False
