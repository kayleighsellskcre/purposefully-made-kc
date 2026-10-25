"""Recreate requests get an "in progress" step with an email, and the AI Design Studio logs its daily use."""
import threading
from datetime import timedelta

import pytest

from models import AiGeneration, CustomDesignRequest, User, db
from utils import ai_usage as U
from utils import ledger as L


def _in_db(app, fn):
    out = {}

    def run():
        with app.app_context():
            try:
                out['value'] = fn()
            except Exception as exc:          # pragma: no cover
                out['error'] = exc
    t = threading.Thread(target=run)
    t.start()
    t.join()
    if 'error' in out:
        raise out['error']
    return out.get('value')


def _request(app, seed, status='pending'):
    def go():
        req = CustomDesignRequest(user_id=seed['customer_id'], reference_file_path='uploads/x.png', description='Recreate my logo',
                                  status=status)
        db.session.add(req)
        db.session.commit()
        return req.id
    return _in_db(app, go)


# ---- the in progress step ----

def test_status_labels(app, seed):
    def go():
        req = CustomDesignRequest(user_id=seed['customer_id'], reference_file_path='x', description='d', status='pending')
        assert (req.status_key, req.status_label) == ('pending', 'Pending')
        from datetime import datetime
        req.started_at = datetime.utcnow()
        assert (req.status_key, req.status_label) == ('in_progress', 'In progress')
        req.status = 'completed'
        assert (req.status_key, req.status_label) == ('completed', 'Completed')
    _in_db(app, go)


def test_starting_marks_it_in_progress_once_and_emails_the_customer(admin_client, app, seed, outbox):
    rid = _request(app, seed)
    resp = admin_client.post(f'/admin/custom-design-requests/{rid}', data={'action': 'start'}, follow_redirects=True)
    assert resp.status_code == 200 and b'In progress' in resp.data
    with app.app_context():
        req = db.session.get(CustomDesignRequest, rid)
        first = req.started_at
        assert req.status == 'pending' and first is not None
    again = admin_client.post(f'/admin/custom-design-requests/{rid}', data={'action': 'start'}, follow_redirects=True)
    assert b'already underway' in again.data
    with app.app_context():
        assert db.session.get(CustomDesignRequest, rid).started_at == first
    started = [m for m in outbox if 'started on your design' in (m.subject or '')]
    assert len(started) == 1 and '1 to 2 business days' in started[0].body       # emailed once, not again


def test_the_start_button_only_shows_for_new_requests(admin_client, app, seed):
    rid = _request(app, seed)
    assert b"I've started on this" in admin_client.get(f'/admin/custom-design-requests/{rid}').data
    admin_client.post(f'/admin/custom-design-requests/{rid}', data={'action': 'start'})
    assert b"I've started on this" not in admin_client.get(f'/admin/custom-design-requests/{rid}').data


# ---- AI studio use ----

def test_runs_are_counted_by_day_and_failures_noted(app, seed):
    def go():
        U.log_start('job1', had_reference=True)
        U.log_start('job2')
        U.log_finish('job1', True)
        U.log_finish('job2', False)
        counts = U.daily_counts(7)
        assert len(counts) == 7 and counts[0] == (L.kc_today(), 2, 1) and counts[1][1:] == (0, 0)
        assert U.today_count() == 2
        assert AiGeneration.query.filter_by(job_id='job1').one().had_reference is True
    _in_db(app, go)


def test_threshold_is_validated_and_defaults(app, seed):
    def go():
        assert U.threshold() == U.DEFAULT_THRESHOLD
        assert U.save_threshold('12') == 12 and U.threshold() == 12
        for bad in ('0', 'abc', '99999', ''):
            with pytest.raises(ValueError):
                U.save_threshold(bad)
    _in_db(app, go)


def test_the_alert_goes_once_on_the_day_the_limit_is_reached(app, seed, monkeypatch):
    sent = []
    monkeypatch.setattr('utils.sponsor_emails._send', lambda to, subject, heading, paragraphs, **kw: sent.append(subject) or True)

    def go():
        U.save_threshold('3')
        U.log_start('a')
        U.log_start('b')
        assert sent == []
        U.log_start('c')
        assert len(sent) == 1 and '3 designs today' in sent[0]
        U.log_start('d')
        assert len(sent) == 1                                          # not again the same day
    _in_db(app, go)


def test_a_failed_alert_email_is_tried_again(app, seed, monkeypatch):
    monkeypatch.setattr('utils.sponsor_emails._send', lambda *a, **k: False)

    def go():
        U.save_threshold('1')
        U.log_start('a')
        monkeypatch.setattr('utils.sponsor_emails._send', lambda *a, **k: True)
        assert U.maybe_alert(L.kc_today()) is True
    _in_db(app, go)


def test_the_page_for_admin_and_not_for_guests(admin_client):
    resp = admin_client.get('/admin/operations/ai-usage')
    assert resp.status_code == 200 and b'AI Studio Use' in resp.data
    saved = admin_client.post('/admin/operations/ai-usage', data={'threshold': '15'}, follow_redirects=True)
    assert b'Saved' in saved.data and b'value="15"' in saved.data


def test_the_page_is_closed_to_guests(guest):
    assert guest.get('/admin/operations/ai-usage').status_code in (301, 302, 303, 401, 403, 404)
