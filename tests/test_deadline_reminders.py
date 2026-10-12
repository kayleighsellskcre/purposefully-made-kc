"""Deadline-morning reminders: the organizer and the admin are both told the last day has come."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from models import db, Collection
from tests.conftest import CUSTOMER_EMAIL
from utils.deadline_reminders import send_deadline_reminders
from utils.group_orders import parse_order_deadline

CHICAGO = ZoneInfo('America/Chicago')


def _today():
    return datetime.now(CHICAGO).date()


def _deadline_on(day):
    return parse_order_deadline(day.strftime('%Y-%m-%d'))


def _prepare(app, coll_id, *, day=None, **fields):
    with app.app_context():
        coll = db.session.get(Collection, coll_id)
        coll.order_deadline = _deadline_on(day or _today())
        coll.deadline_reminder_sent_at = None
        coll.is_active = True
        for key, value in fields.items():
            setattr(coll, key, value)
        db.session.commit()
        return coll.name, coll.slug


def _run(app):
    with app.app_context():
        return send_deadline_reminders(app)


def _admin(app):
    return app.config['ADMIN_EMAIL']


def _to(outbox, address):
    return [m for m in outbox if address.lower() in [r.lower() for r in m.recipients]]


# ── One standalone group ─────────────────────────────────────────────────────

def test_organizer_and_admin_both_get_a_reminder_on_deadline_day(app, seed, outbox):
    name, slug = _prepare(app, seed['collection_id'], created_by_user_id=seed['customer_id'])
    result = _run(app)
    assert result == {'groups': 1, 'emails': 2}

    organizer = _to(outbox, CUSTOMER_EMAIL)
    admin = _to(outbox, _admin(app))
    assert len(organizer) == 1 and len(admin) == 1

    mail = organizer[0]
    assert mail.subject == f'Last day to order: {name}'
    assert 'last day' in mail.body.lower() and 'remind your group' in mail.body.lower()
    assert f'/c/{slug}' in mail.body and f'/c/{slug}' in mail.html
    assert 'Open Your Group Link' in mail.html

    note = admin[0]
    assert note.subject.startswith(f'Deadline today: {name}')
    assert CUSTOMER_EMAIL in note.body                       # the admin sees who was reminded


def test_a_group_is_only_reminded_once(app, seed, outbox):
    _prepare(app, seed['collection_id'], created_by_user_id=seed['customer_id'])
    assert _run(app)['groups'] == 1
    sent = len(outbox)
    assert _run(app) == {'groups': 0, 'emails': 0}           # a later run the same morning does nothing
    assert len(outbox) == sent


def test_no_reminder_unless_the_deadline_is_today(app, seed, outbox):
    _prepare(app, seed['collection_id'], day=_today() + timedelta(days=1),
             created_by_user_id=seed['customer_id'])
    assert _run(app) == {'groups': 0, 'emails': 0}
    _prepare(app, seed['collection_id'], day=_today() - timedelta(days=1))
    assert _run(app) == {'groups': 0, 'emails': 0}
    assert len(outbox) == 0


def test_a_switched_off_group_is_not_reminded(app, seed, outbox):
    _prepare(app, seed['collection_id'], is_active=False, created_by_user_id=seed['customer_id'])
    assert _run(app) == {'groups': 0, 'emails': 0}
    assert len(outbox) == 0


def test_a_new_deadline_can_be_reminded_again(app, seed, outbox):
    _prepare(app, seed['collection_id'], created_by_user_id=seed['customer_id'])
    _run(app)
    with app.app_context():                                   # reminded last week, deadline moved to today
        coll = db.session.get(Collection, seed['collection_id'])
        coll.deadline_reminder_sent_at = datetime.utcnow() - timedelta(days=7)
        db.session.commit()
    assert _run(app)['groups'] == 1


# ── Who gets it ──────────────────────────────────────────────────────────────

def test_when_the_admin_is_the_organizer_there_is_one_email(app, seed, outbox):
    _prepare(app, seed['collection_id'], created_by_user_id=seed['admin_id'])
    assert _run(app) == {'groups': 1, 'emails': 1}
    mail = _to(outbox, _admin(app))
    assert len(mail) == 1
    assert 'You are the organizer' in mail[0].body


def test_a_group_with_no_organizer_email_tells_the_admin(app, seed, outbox):
    _prepare(app, seed['collection_id'], created_by_user_id=None, pending_organizer_email=None)
    assert _run(app) == {'groups': 1, 'emails': 1}
    assert 'No organizer email' in _to(outbox, _admin(app))[0].body


def test_an_organizer_without_an_account_yet_is_still_reminded(app, seed, outbox):
    _prepare(app, seed['collection_id'], created_by_user_id=None,
             pending_organizer_email='coach@example.com')
    assert _run(app) == {'groups': 1, 'emails': 2}
    assert len(_to(outbox, 'coach@example.com')) == 1


# ── A multi-team organization is ONE group ───────────────────────────────────

def test_an_organization_gets_one_email_listing_every_team(admin_client, app, seed, outbox):
    from tests.test_org_fan_wear import _build, _org_slug, _store
    _build(admin_client, app, seed)
    teams = ('Basketball', 'Soccer', 'Volleyball')
    for team in teams:
        _prepare(app, _store(app, f'{team}: Rainbow Cheetahs')[0], created_by_user_id=seed['customer_id'])
    assert _run(app) == {'groups': 1, 'emails': 2}            # not 3 groups, not 6 emails

    organizer = _to(outbox, CUSTOMER_EMAIL)
    assert len(organizer) == 1
    for team in teams:
        assert team in organizer[0].body
    assert f"/org/{_org_slug(app)}" in organizer[0].body
    assert organizer[0].subject == 'Last day to order: Rainbow Cheetahs'
    assert len(_to(outbox, _admin(app))) == 1


# ── Mail trouble must not lose the reminder ──────────────────────────────────

def test_a_mail_outage_does_not_mark_the_group_as_reminded(app, seed, monkeypatch, outbox):
    _prepare(app, seed['collection_id'], created_by_user_id=seed['customer_id'])
    monkeypatch.setattr('utils.deadline_reminders.send', lambda *a, **k: False)
    assert _run(app) == {'groups': 0, 'emails': 0}
    with app.app_context():
        assert db.session.get(Collection, seed['collection_id']).deadline_reminder_sent_at is None
    monkeypatch.undo()
    assert _run(app)['groups'] == 1                           # the next run still sends it


# ── The morning job ──────────────────────────────────────────────────────────

def test_the_morning_job_sends_and_never_raises(app, seed, outbox):
    from scheduler import deadline_reminders_job
    _prepare(app, seed['collection_id'], created_by_user_id=seed['customer_id'])
    assert deadline_reminders_job(app) is None
    assert len(_to(outbox, CUSTOMER_EMAIL)) == 1


def test_the_job_is_scheduled_for_the_morning():
    import inspect
    import scheduler
    source = inspect.getsource(scheduler.init_scheduler)
    assert "id='deadline_reminders'" in source and "hour='8-11'" in source
