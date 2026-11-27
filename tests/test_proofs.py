"""Design proof approval: send, approve, ask for changes, hold before pressing, one reminder, digest and tracking."""
import threading
from datetime import datetime, timedelta

import pytest

from models import Order, OrderProof, db
from utils import proofs as P


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


def _order(number='PRF1', email='amy@example.com', **kw):
    d = dict(email=email, first_name='Amy', last_name='Lee', subtotal=50.0, shipping_cost=0.0, tax=0.0, total=50.0,
             payment_status='paid', status='new', production_stage='order_received', payment_method='stripe',
             fulfillment_method='pickup')
    d.update(kw)
    o = Order(order_number=number, **d)
    db.session.add(o)
    db.session.commit()
    return o


def test_sending_emails_a_private_link_and_marks_the_order_waiting(app, seed, outbox):
    def go():
        o = _order()
        p = P.send_proof(o, 'Please check the spelling')
        assert p.status == 'waiting' and P.is_waiting(o) and o.id in P.waiting_order_ids()
        return p.token
    token = _in_db(app, go)
    assert len(outbox) == 1 and f'/proof/{token}' in outbox[0].body and 'Please check the spelling' in outbox[0].body


def test_no_email_address_means_no_proof(app, seed):
    def go():
        o = _order('PRF2', email='')
        with pytest.raises(ValueError):
            P.send_proof(o)
        assert OrderProof.query.count() == 0
    _in_db(app, go)


def test_a_waiting_proof_holds_pressing_but_not_earlier_stages(app, seed):
    def go():
        o = _order('PRF3')
        P.send_proof(o)
        assert P.blocked_reason(o, 'ready_to_press') and P.blocked_reason(o, 'pressed')
        assert P.blocked_reason(o, 'waiting_supplies') is None
        P.approve(P.latest(o.id), by='shop')
        assert P.blocked_reason(o, 'ready_to_press') is None
    _in_db(app, go)


def test_a_new_proof_replaces_the_old_one_and_old_links_cannot_answer(app, seed):
    def go():
        o = _order('PRF4')
        first = P.send_proof(o)
        second = P.send_proof(o, 'Fixed it')
        assert first.status == 'replaced' and second.status == 'waiting'
        with pytest.raises(ValueError):
            P.approve(first)
        assert [p.status for p in P.history(o.id)] == ['waiting', 'replaced']
    _in_db(app, go)


def test_changes_need_a_note_and_show_until_a_new_proof(app, seed):
    def go():
        o = _order('PRF5')
        p = P.send_proof(o)
        with pytest.raises(ValueError):
            P.request_changes(p, '   ')
        P.request_changes(p, 'Please make the name bigger')
        assert [x.id for x in P.changes_proofs()] == [p.id] and not P.is_waiting(o)
        P.send_proof(o)
        assert P.changes_proofs() == []
    _in_db(app, go)


def test_one_reminder_after_two_days_and_never_two(app, seed, outbox):
    def go():
        o = _order('PRF6')
        p = P.send_proof(o)
        assert P.run_reminders() == 0
        later = datetime.utcnow() + timedelta(days=2, hours=1)
        assert P.run_reminders(later) == 1
        assert P.run_reminders(later + timedelta(days=5)) == 0
        done = _order('PRF7', email='b@example.com')
        P.approve(P.send_proof(done))
        assert P.run_reminders(later + timedelta(days=9)) == 0
    _in_db(app, go)
    assert len(outbox) == 3 and 'reminder' in outbox[1].subject.lower()


def test_the_customer_page_approves_and_asks_for_changes(app, seed, guest):
    token = _in_db(app, lambda: P.send_proof(_order('PRF8')).token)
    page = guest.get(f'/proof/{token}')
    assert page.status_code == 200 and b'Approve my design' in page.data and page.headers['X-Robots-Tag'] == 'noindex'
    assert guest.post(f'/proof/{token}', data={'action': 'changes', 'note': ''}).status_code == 200      # shows the problem
    assert b'tell us what to change' in guest.post(f'/proof/{token}', data={'action': 'changes', 'note': ''}).data
    guest.post(f'/proof/{token}', data={'action': 'approve'})
    assert b'this is approved' in guest.get(f'/proof/{token}').data
    assert _in_db(app, lambda: P.latest(db.session.query(Order).filter_by(order_number='PRF8').one().id).status) == 'approved'


def test_an_unknown_link_is_a_404(guest):
    assert guest.get('/proof/not-a-real-token').status_code == 404


def test_admin_sends_and_the_order_cannot_be_pressed_until_approved(admin_client, app, seed):
    oid = _in_db(app, lambda: _order('PRF9').id)
    admin_client.post(f'/admin/orders/{oid}/proof', data={'action': 'send', 'message': ''}, follow_redirects=True)
    assert _in_db(app, lambda: P.is_waiting(db.session.get(Order, oid)))
    admin_client.post(f'/admin/orders/{oid}/update-status', data={'status': 'ready_to_press'})
    assert _in_db(app, lambda: db.session.get(Order, oid).production_stage) == 'order_received'
    assert b'Waiting on approval' in admin_client.get('/admin/operations/workflow').data
    admin_client.post(f'/admin/orders/{oid}/proof', data={'action': 'approve'})
    admin_client.post(f'/admin/orders/{oid}/update-status', data={'status': 'ready_to_press'})
    assert _in_db(app, lambda: db.session.get(Order, oid).production_stage) == 'ready_to_press'


def test_admin_pages_open(admin_client, app, seed):
    oid = _in_db(app, lambda: _order('PRF10').id)
    assert admin_client.get(f'/admin/orders/{oid}').status_code == 200
    assert b'Design Proofs' in admin_client.get('/admin/operations/proofs').data


def test_the_morning_digest_mentions_waiting_and_changed_proofs(app, seed):
    from utils import daily_digest as D

    def go():
        o = _order('PRF11')
        P.send_proof(o)
        keys = {s['key'] for s in D.daily_sections()}
        assert 'proofwaiting' in keys
        P.request_changes(P.latest(o.id), 'Wrong color')
        assert 'proofchanges' in {s['key'] for s in D.daily_sections()}
    _in_db(app, go)


def test_tracking_points_a_waiting_customer_to_their_proof(app, seed):
    from utils import order_tracking as T

    def go():
        o = _order('PRF12')
        assert T.summary(o)['proof_url'] is None
        p = P.send_proof(o)
        info = T.summary(o)
        assert info['proof_url'] == f'/proof/{p.token}' and 'approval' in info['headline']
    _in_db(app, go)


def test_the_proof_admin_pages_are_closed_to_guests(guest):
    assert guest.get('/admin/operations/proofs').status_code in (301, 302, 303, 401, 403, 404)
