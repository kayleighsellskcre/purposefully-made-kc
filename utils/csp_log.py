"""Keep the content security policy reports from flooding the log.

The policy is report-only, so every inline script or style on a page sends one report, and a single page view can send
dozens. Each kind of report is logged once an hour, with how many of that kind arrived since, so the log still shows what
trips the policy without burying real warnings.
"""
import threading
import time

_WINDOW_SECONDS = 3600
_MAX_KINDS = 300
_seen = {}
_lock = threading.Lock()


def _kind(report):
    """What makes two reports 'the same': which rule, what was blocked, and on which page or file (not the exact text)."""
    if not isinstance(report, dict):
        return ('other',)
    where = str(report.get('document-uri') or report.get('documentURL') or '').split('?', 1)[0]
    return (str(report.get('violated-directive') or report.get('effectiveDirective') or ''),
            str(report.get('blocked-uri') or report.get('blockedURL') or ''), where)


def should_log(report, now=None):
    """(log it?, how many of this kind were skipped since the last one that was logged)."""
    now = time.time() if now is None else now
    key = _kind(report)
    with _lock:
        row = _seen.get(key)
        if row is None:
            if len(_seen) >= _MAX_KINDS:
                _seen.clear()                       # bounded memory: start counting kinds again
            _seen[key] = [now, 0]
            return True, 0
        if now - row[0] >= _WINDOW_SECONDS:
            skipped = row[1]
            row[0], row[1] = now, 0
            return True, skipped
        row[1] += 1
        return False, 0


def reset():
    with _lock:
        _seen.clear()
