"""Quiet spam protection for public forms (contact, recreate requests).

Layers, none of which a real person ever notices:
  1. A hidden "website" box that people leave empty and bots fill in.
  2. A signed start time: a form sent back in under a few seconds, or after half a day, is a bot.
  3. Links: a message with more than one web address is nearly always link-buying spam.
  4. Cloudflare Turnstile (free, usually invisible), switched on by setting TURNSTILE_SITE_KEY and
     TURNSTILE_SECRET_KEY. Without those two variables the first three layers still work.

A bot that trips layers 1 to 3 is told "thank you" and nothing is stored, so it does not learn what to avoid.
"""
from __future__ import annotations

import re
import time

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer
from markupsafe import Markup

MIN_SECONDS = 3
MAX_SECONDS = 12 * 3600
VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
_LINK = re.compile(r'(https?://|www\.)', re.IGNORECASE)


def _signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='form-started')


def turnstile_enabled():
    return bool(current_app.config.get('TURNSTILE_SITE_KEY') and current_app.config.get('TURNSTILE_SECRET_KEY'))


def spam_fields(honeypot=True):
    """The hidden inputs (and the Turnstile box, when it is switched on) to drop inside a form."""
    parts = [f'<input type="hidden" name="form_started" value="{_signer().dumps(int(time.time()))}">']
    if honeypot:
        parts.append('<div class="cf-hp" aria-hidden="true"><label for="hp-website">Leave this field blank</label>'
                     '<input type="text" id="hp-website" name="website" tabindex="-1" autocomplete="off"></div>')
    if turnstile_enabled():
        key = current_app.config['TURNSTILE_SITE_KEY']
        parts.append(f'<div class="cf-turnstile" data-sitekey="{key}" data-theme="light"></div>'
                     '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>')
    return Markup(''.join(parts))


def _verify_turnstile(req):
    """True when Turnstile accepts the visitor. If Cloudflare itself cannot be reached, let the visitor through."""
    token = (req.form.get('cf-turnstile-response') or '').strip()
    if not token:
        return False
    try:
        import requests
        resp = requests.post(VERIFY_URL, data={
            'secret': current_app.config['TURNSTILE_SECRET_KEY'], 'response': token,
            'remoteip': req.headers.get('CF-Connecting-IP') or req.remote_addr or '',
        }, timeout=6)
        return bool(resp.json().get('success'))
    except Exception:
        current_app.logger.exception('Turnstile check could not reach Cloudflare; letting the visitor through')
        return True


def check(req, *, max_links=None, text_field='message'):
    """Judge a form post. Returns (verdict, reason): 'ok', 'spam' (pretend success), or 'retry' (show an error)."""
    if (req.form.get('website') or '').strip():
        return 'spam', 'honeypot'
    strict = current_app.config.get('SPAM_GUARD_STRICT', True)
    token = req.form.get('form_started') or ''
    if token or strict:
        try:
            started = _signer().loads(token, max_age=MAX_SECONDS)
        except BadSignature:
            return 'spam', 'no or old form token'
        if time.time() - int(started) < MIN_SECONDS:
            return 'spam', 'sent too fast'
    if max_links is not None and len(_LINK.findall(req.form.get(text_field) or '')) > max_links:
        return 'spam', 'links'
    if turnstile_enabled() and not _verify_turnstile(req):
        return 'retry', 'turnstile'
    return 'ok', ''
