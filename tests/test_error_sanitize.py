"""Sanitization helpers for the admin Site Errors UI."""
from utils.error_notify import (
    redact_query_string,
    safe_error_message,
    safe_referrer_display,
)


def test_redact_query_string_masks_tokens_and_emails():
    q = 'order=12&token=supersecret&email=person%40example.com&color=navy'
    out = redact_query_string(q)
    assert 'supersecret' not in out
    assert 'person' not in out
    assert 'person%40' not in out
    # urlencode turns "***" into "%2A%2A%2A"
    assert ('***' in out) or ('%2A%2A%2A' in out)
    assert 'order=12' in out
    assert 'color=navy' in out


def test_safe_error_message_truncates_and_flattens():
    msg = 'ValueError: boom\nDETAIL: password=hunter2 path=/secret'
    out = safe_error_message(msg, limit=40)
    assert '\n' not in out
    assert out.endswith('…')
    assert len(out) <= 40


def test_safe_referrer_strips_query():
    ref = 'https://purposefullymadekc.com/reset?token=abc123'
    out = safe_referrer_display(ref)
    assert 'token' not in out
    assert out.startswith('https://purposefullymadekc.com/reset')
