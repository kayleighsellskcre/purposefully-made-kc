"""One way out for every email the site sends.

Three things were inconsistent before this existed:
  - Some senders logged failures, some printed to stderr, some swallowed them.
  - The sender display name was never set, so receipts arrived as a bare
    gmail address instead of "Purposefully Made KC".
  - Nothing stopped a development run from emailing real customers.
"""
import socket

SENDER_NAME = 'Purposefully Made KC'
BUSINESS_EMAIL = 'purposefullymadekc@gmail.com'


def mail_configured(app):
    """True when Flask-Mail has everything it needs to reach the SMTP relay."""
    return bool(
        app.extensions.get('mail')
        and app.config.get('MAIL_SERVER')
        and app.config.get('MAIL_USERNAME')
        and app.config.get('MAIL_PASSWORD')
    )


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

    A mail failure must never roll back a paid order or break a page render,
    so every error is logged and swallowed here.
    """
    if not mail_configured(app):
        app.logger.error(
            '%s not sent — MAIL_SERVER, MAIL_USERNAME, or MAIL_PASSWORD is missing',
            description,
        )
        return False
    if not msg.recipients:
        app.logger.error('%s not sent — no recipients', description)
        return False

    if not msg.sender:
        msg.sender = sender(app)

    _apply_test_guard(app, msg)

    mail = app.extensions.get('mail')
    timeout = int(app.config.get('MAIL_TIMEOUT') or 20)
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        mail.send(msg)
        app.logger.info('%s sent to %s', description, ', '.join(msg.recipients))
        return True
    except Exception:
        # exception() records the traceback without exposing it to a customer.
        app.logger.exception('%s failed to %s', description, ', '.join(msg.recipients))
        return False
    finally:
        socket.setdefaulttimeout(previous)
