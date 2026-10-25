"""The morning digest and Monday summary."""
import threading
from datetime import datetime, timedelta

import pytest

from models import AdminNotification, Collection, CustomDesignRequest, Order, User, db
from utils import daily_digest as D
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


NOW = datetime(2026, 10, 26, 7, 0, tzinfo=L.CENTRAL)          # a Monday morning in Kansas City


def _utc(local):
    return local.astimezone(__import__('datetime').timezone.utc).replace(tzinfo=None)


def _order(number, **kw):
    defaults = dict(email='a@example.com', first_name='Amy', last_name='Lee', subtotal=50.0, shipping_cost=0.0, tax=0.0, total=50.0,
                    payment_status='paid', status='new', production_stage='order_received', payment_method='stripe',
                    paid_at=_utc(NOW - timedelta(hours=5)))
    defaults.update(kw)
    o = Order(order_number=number, **defaults)
    db.session.add(o)
    db.session.commit()
    return o


def _titles(sections):
    return {s['key']: s for s in sections}


def test_a_quiet_morning_has_no_sections(app, seed):
    assert _in_db(app, lambda: D.daily_sections(NOW)) == []


def test_sections_find_what_needs_attention(app, seed):
    def go():
        _order('NEW1')
        _order('LATE1', paid_at=_utc(NOW - timedelta(days=9)), due_date=_utc(NOW - timedelta(days=2)))
        _order('SOON1', paid_at=_utc(NOW - timedelta(days=3)), due_date=_utc(NOW + timedelta(days=2)))
        _order('FAR1', paid_at=_utc(NOW - timedelta(days=3)), due_date=_utc(NOW + timedelta(days=20)))
        stuck = _order('STUCK1', paid_at=_utc(NOW - timedelta(days=12)), status='in_production', production_stage='ready_to_press')
        db.session.query(Order).filter(Order.id == stuck.id).update({'updated_at': _utc(NOW - timedelta(days=8))})
        db.session.add(Collection(name='Lincoln Spirit Wear', slug='lincoln', share_token='tok1', is_active=True,
                                  order_deadline=_utc(NOW + timedelta(days=3))))
        db.session.add(Collection(name='Far Away Store', slug='far', share_token='tok2', is_active=True,
                                  order_deadline=_utc(NOW + timedelta(days=30))))
        user = User.query.first()
        db.session.add(CustomDesignRequest(user_id=user.id, reference_file_path='x.png', description='make it', status='pending'))
        db.session.add(AdminNotification(kind='contact', title='Hello'))
        db.session.commit()
        return _titles(D.daily_sections(NOW))
    s = _in_db(app, go)
    assert s['new']['count'] == 1 and 'NEW1' in s['new']['lines'][0]
    assert s['overdue']['count'] == 1 and 'LATE1' in s['overdue']['lines'][0]
    assert s['due']['count'] == 1 and 'SOON1' in s['due']['lines'][0]
    assert s['stuck']['count'] >= 1 and any('Ready to Press' in line for line in s['stuck']['lines'])
    assert s['closing']['count'] == 1 and 'Lincoln' in s['closing']['lines'][0]
    assert s['requests']['count'] == 1 and s['messages']['count'] == 1
    assert all(sec['link'].startswith('/admin/') for sec in s.values())


def test_finished_orders_are_left_out(app, seed):
    def go():
        _order('DONE1', status='completed', production_stage='completed', paid_at=_utc(NOW - timedelta(days=9)),
               due_date=_utc(NOW - timedelta(days=3)))
        return _titles(D.daily_sections(NOW))
    assert 'overdue' not in _in_db(app, go)


def test_daily_email_goes_once_a_day_and_only_when_needed(app, seed, outbox):
    def go():
        assert D.send_daily(NOW) is False                           # quiet: nothing to send
        _order('NEW1')
        assert D.send_daily(NOW) is True
        assert D.send_daily(NOW) is False                           # already sent today
        assert D.send_daily(NOW, force=True) is True                # the button resends
        assert D.send_daily(NOW + timedelta(days=1)) is False       # next day: the order is no longer new
    _in_db(app, go)
    assert len(outbox) == 2
    assert 'NEW1' in outbox[0].body and '/admin/orders' in outbox[0].body and 'Good morning' in outbox[0].html


def test_weekly_email_has_the_numbers_and_blanks(app, seed, outbox):
    def go():
        _order('LASTWEEK', paid_at=_utc(NOW - timedelta(days=3)))
        L.sync_all(force=True)
        assert D.send_weekly(NOW) is True
        assert D.send_weekly(NOW) is False                          # once a week
    _in_db(app, go)
    assert len(outbox) == 1 and 'Last week' in outbox[0].body and 'Blanks to order this week' in outbox[0].body


def test_buttons_for_admin(admin_client, outbox):
    assert admin_client.post('/admin/operations/digest-now', data={'which': 'weekly'}).status_code in (302, 303)
    assert len(outbox) == 1


def test_button_closed_to_guests(guest):
    assert guest.post('/admin/operations/digest-now', data={'which': 'daily'}).status_code in (302, 303, 400, 401, 403, 404)
