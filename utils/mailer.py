"""One way out for every email the site sends.

Sending strategy (tried in order):
  1. Brevo HTTP API  — when BREVO_API_KEY is set.
     Uses HTTPS on port 443, which Railway never blocks.
  2. Flask-Mail SMTP — fallback for local dev / other hosts.
     Railway blocks port 587, so this path only works outside Railway.

To enable email on Railway, set ONE new variable:
  BREVO_API_KEY   — Brevo dashboard → SMTP & API → API Keys → Create key
"""
import socket

SENDER_NAME = 'Purposefully Made KC'
BUSINESS_EMAIL = 'purposefullymadekc@gmail.com'
BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'


def _brevo_api_key(app):
    return (app.config.get('BREVO_API_KEY') or '').strip()


def _brevo_configured(app):
    return bool(_brevo_api_key(app))


def mail_configured(app):
    """True when at least one sending path is available."""
    if _brevo_configured(app):
        return True
    return bool(
        app.extensions.get('mail')
        and app.config.get('MAIL_SERVER')
        and app.config.get('MAIL_USERNAME')
        and app.config.get('MAIL_PASSWORD')
    )


def _send_via_brevo_api(app, msg):
    """Send via Brevo HTTP API. Returns True on success, never raises."""
    import requests

    api_key = _brevo_api_key(app)
    from_addr = app.config.get('MAIL_DEFAULT_SENDER') or BUSINESS_EMAIL
    if isinstance(from_addr, (tuple, list)):
        from_name, from_email = (from_addr[0], from_addr[1]) if len(from_addr) >= 2 else (SENDER_NAME, from_addr[0])
    else:
        from_name, from_email = SENDER_NAME, from_addr

    payload = {
        'sender': {'name': from_name, 'email': from_email},
        'to': [{'email': r} for r in msg.recipients],
        'subject': msg.subject,
    }
    if msg.html:
        payload['htmlContent'] = msg.html
    if msg.body:
        payload['textContent'] = msg.body
    if msg.reply_to:
        rt = msg.reply_to
        payload['replyTo'] = {'email': rt} if isinstance(rt, str) else {'email': rt[1], 'name': rt[0]}

    try:
        resp = requests.post(
            BREVO_API_URL,
            json=payload,
            headers={'api-key': api_key, 'Content-Type': 'application/json'},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return True
        app.logger.error('Brevo API error %s: %s', resp.status_code, resp.text[:300])
        return False
    except Exception:
        app.logger.exception('Brevo API request failed')
        return False


def sender(app):
    """(display name, address) tuple, or None when no address is configured."""
    address = app.config.get('MAIL_DEFAULT_SENDER') or app.config.get('MAIL_USERNAME')
    if isinstance(address, (tuple, list)):
        return tuple(address)
    if not address:
        return None
    return (SENDER_NAME, address)


def reply_to(app):
    return app.config.get('ADMIN_EMAIL') or BUSINESS_EMAIL


def admin_recipient(app):
    return app.config.get('ADMIN_EMAIL') or BUSINESS_EMAIL


def admin_base_url(app):
    """Absolute site root for links inside emails.

    Defaults to the live domain rather than localhost, because an unset
    ADMIN_BASE_URL used to put http://localhost:5000 links in real emails.
    """
    return (app.config.get('ADMIN_BASE_URL') or 'https://purposefullymadekc.com').rstrip('/')


def _apply_test_guard(app, msg):
    """Redirect outbound mail when MAIL_TEST_REDIRECT is set.

    Set MAIL_TEST_REDIRECT to your own address in any non-production
    environment and no customer can ever receive mail from it, whatever the
    code tries to do. Unset (the production case) changes nothing.
    """
    redirect_to = (app.config.get('MAIL_TEST_REDIRECT') or '').strip()
    if not redirect_to:
        return msg
    original = ', '.join(msg.recipients or [])
    msg.recipients = [redirect_to]
    msg.subject = f'[TEST → {original}] {msg.subject}'
    app.logger.info('mail redirected to %s (was %s)', redirect_to, original)
    return msg


def send(app, msg, description='email'):
    """Send one message. Returns True on success. Never raises.

    Tries Brevo HTTP API first (works on Railway), then falls back to
    Flask-Mail SMTP (works on local dev / other hosts).

    A mail failure must never roll back a paid order or break a page render,
    so every error is logged and swallowed here.
    """
    if not mail_configured(app):
        app.logger.error(
            '%s not sent — no mail transport configured '
            '(set BREVO_API_KEY on Railway, or MAIL_SERVER+USERNAME+PASSWORD for SMTP)',
            description,
        )
        return False
    if not msg.recipients:
        app.logger.error('%s not sent — no recipients', description)
        return False

    if not msg.sender:
        msg.sender = sender(app)

    _apply_test_guard(app, msg)

    # ── Path 1: Brevo HTTP API (Railway-compatible) ──────────────────────────
    if _brevo_configured(app):
        ok = _send_via_brevo_api(app, msg)
        if ok:
            app.logger.info('%s sent via Brevo API to %s', description, ', '.join(msg.recipients))
        else:
            app.logger.error('%s failed via Brevo API to %s', description, ', '.join(msg.recipients))
        return ok

    # ── Path 2: Flask-Mail SMTP (local dev fallback) ─────────────────────────
    mail = app.extensions.get('mail')
    timeout = int(app.config.get('MAIL_TIMEOUT') or 20)
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        mail.send(msg)
        app.logger.info('%s sent via SMTP to %s', description, ', '.join(msg.recipients))
        return True
    except Exception:
        app.logger.exception('%s failed via SMTP to %s', description, ', '.join(msg.recipients))
        return False
    finally:
        socket.setdefaulttimeout(previous)
