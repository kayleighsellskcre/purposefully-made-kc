"""What a customer sees when the AI picture maker cannot make a picture, and the one email that tells the owner why.

OpenAI's own wording ("You have no credits remaining ... platform.openai.com/settings/...") must never reach a
customer: it is confusing, it names our account, and it looks like the shop is broken. The customer gets a calm
sentence and a way forward, and the owner gets one email (at most one every 12 hours) saying what to fix.
"""
from __future__ import annotations

from datetime import datetime, timedelta

ALERT_KEY = 'ai_alert_sent_at'
ALERT_GAP = timedelta(hours=12)

BUSY = ('Our AI designer is taking a short break. You can still get your design: browse the Design Gallery, '
        'or send us your idea with Custom Design and we will make it for you.')
TRY_LATER = 'Lots of people are making designs right now. Please try again in a minute.'
REWORD = 'We could not make that one. Try describing it a little differently, with simpler words.'
GENERIC = 'Something went wrong making your design. Please try again.'


MODEL_WORDS = ('model_not_found', 'does not exist', 'deprecated', 'has been shut down', 'no longer available',
               'not supported', 'invalid model', 'unknown model', 'retired')


def is_model_problem(status, message='', code=''):
    """OpenAI turned the picture model off or does not know it (so a newer model should be tried)."""
    text = f'{message} {code}'.lower()
    return status in (400, 404) and 'model' in text and any(w in text for w in MODEL_WORDS)


def classify(status, message='', code=''):
    """'credits' (we ran out or the key is bad), 'model' (the picture model was retired), 'busy', 'reword' or 'other'."""
    text = f'{message} {code}'.lower()
    if is_model_problem(status, message, code):
        return 'model'
    if status in (401, 402, 403) or any(w in text for w in ('no credits', 'insufficient_quota', 'billing', 'quota', 'incorrect api key', 'invalid_api_key')):
        return 'credits'
    if status == 429 or 'rate limit' in text or 'rate_limit' in text:
        return 'busy'
    if any(w in text for w in ('safety', 'moderation', 'content_policy', 'content policy', 'not allowed')):
        return 'reword'
    return 'other'


def customer_message(kind):
    return {'credits': BUSY, 'model': BUSY, 'busy': TRY_LATER, 'reword': REWORD}.get(kind, GENERIC)


def alert_owner(app, kind, status, message):
    """Email the owner when the picture maker is down for a reason only they can fix. Never raises."""
    if kind not in ('credits', 'model'):
        return False
    try:
        from utils.site_settings import get_setting, set_setting
        last = get_setting(ALERT_KEY, '')
        if last:
            try:
                if datetime.utcnow() - datetime.fromisoformat(last) < ALERT_GAP:
                    return False
            except ValueError:
                pass
        set_setting(ALERT_KEY, datetime.utcnow().isoformat(), 'When the owner was last told the AI picture maker is down')
        from flask_mail import Message

        from utils import mailer
        if kind == 'model':
            reason = ('OpenAI no longer offers the picture model the site uses (they retire older models every few months).\n'
                      'Fix: set OPENAI_IMAGE_MODEL in Railway to OpenAI\'s current image model, or ask Claude to update it.\n\n')
            subject = 'AI Design Studio is paused: OpenAI picture model needs updating'
        else:
            reason = ('The most likely reason is that the OpenAI account is out of credits.\n'
                      'Fix: sign in at https://platform.openai.com/settings/organization/billing/ and add credits '
                      '(turning on auto-recharge there keeps this from happening again).\n\n')
            subject = 'AI Design Studio is paused: check OpenAI credits'
        body = ('The AI Design Studio could not make a picture, so customers are being told it is taking a short break.\n\n'
                + reason + f'OpenAI said ({status}): {str(message)[:300]}\n\n'
                'You will get at most one of these emails every 12 hours.')
        return bool(mailer.send(app, Message(subject=subject,
                                             recipients=[mailer.admin_recipient(app)], body=body), 'ai credits alert'))
    except Exception:
        app.logger.exception('could not send the AI credits alert')
        return False
