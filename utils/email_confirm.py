"""Confirm a new account's email address.

A link is emailed when someone signs up. Opening it marks the address as confirmed. Nothing is blocked while it is
waiting: the person can shop and check out right away. It simply tells us the address is real, so receipts and order
updates reach them. Resetting a password through the emailed link proves the address too.

Accounts that existed before this feature were never sent one, so they are never nagged: only an account that was
sent a link and has not opened it shows the small reminder on My Account.
"""
from __future__ import annotations

from datetime import datetime

from flask import current_app, render_template, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from models import User, db

SALT = 'confirm-email'
MAX_AGE_SECONDS = 7 * 24 * 3600


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=SALT)


def make_token(user) -> str:
    return _serializer().dumps({'uid': user.id, 'email': (user.email or '').lower()})


def user_for_token(token):
    """The user a link belongs to, or None when it is wrong, expired, or the email has since changed."""
    try:
        data = _serializer().loads(token, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, int(data.get('uid') or 0))
    if user is None or (user.email or '').lower() != data.get('email'):
        return None
    return user


def mark_confirmed(user):
    if user.email_confirmed_at is None:
        user.email_confirmed_at = datetime.utcnow()


def needs_reminder(user) -> bool:
    return bool(user is not None and getattr(user, 'email_confirm_sent_at', None) and not user.email_confirmed_at)


def send_confirmation(user_or_id):
    """Email the link. Runs in the background (app context, no request). Never raises."""
    try:
        from flask_mail import Message
        from utils.mailer import admin_base_url, reply_to, send

        app = current_app._get_current_object()
        user = db.session.get(User, user_or_id) if isinstance(user_or_id, int) else user_or_id
        if user is None or user.email_confirmed_at:
            return False
        with app.test_request_context(base_url=admin_base_url(app)):
            link = url_for('auth.confirm_email', token=make_token(user), _external=True)
            name = user.first_name or 'there'
            html = render_template('email/confirm_email.html', name=name, link=link)
        text = (f"Hi {name},\n\nWelcome to Purposefully Made KC. Please confirm your email address so your order "
                f"receipts and updates reach you:\n\n{link}\n\nThe link works for 7 days. If you did not create an "
                f"account, you can ignore this email.\n\n- Purposefully Made KC")
        ok = send(app, Message(subject='Please confirm your email - Purposefully Made KC', recipients=[user.email],
                               body=text, html=html, reply_to=reply_to(app)), description=f'email confirmation for {user.email}')
        if ok:
            user.email_confirm_sent_at = datetime.utcnow()
            db.session.commit()
        return bool(ok)
    except Exception:
        current_app.logger.exception('Email confirmation failed')
        return False
