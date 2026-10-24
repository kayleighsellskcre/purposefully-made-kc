"""Stripe refunds and payouts by webhook, PayPal refunds by nightly check, and how they land in the books."""
import json
import threading
from datetime import date, datetime, timezone

import pytest

from models import LedgerEntry, ManualInvoice, Order, Payout, db
from utils import ledger as L
from utils import money_events as M


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


@pytest.fixture(autouse=True)
def _unthrottled():
    L._LAST_SYNC['at'] = 0.0
    yield
    L._LAST_SYNC['at'] = 0.0


def _paid_order(number='PMKC-M1', intent='pi_1', **kw):
    defaults = dict(email='amy@example.com', subtotal=100.0, shipping_cost=11.0, tax=9.5, total=120.5,
                    payment_status='paid', status='paid', payment_method='stripe', payment_intent_id=intent,
                    paid_at=datetime(2026, 10, 15, 18, 0))
    defaults.update(kw)
    o = Order(order_number=number, **defaults)
    db.session.add(o)
    db.session.commit()
    L.sync_all(force=True)
    return o.id


def _hook(app, monkeypatch, event):
    import stripe
    monkeypatch.setattr(stripe.Webhook, 'construct_event', lambda *a, **k: event)
    return app.test_client().post('/checkout/stripe-webhook', data=b'{}', headers={'Stripe-Signature': 'x'})


def _ts(y, m, d, h=15):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())


def _refund_event(intent='pi_1', amount=12050, refunded=12050, created=None):
    return {'type': 'charge.refunded', 'created': created or _ts(2026, 11, 5),
            'data': {'object': {'id': 'ch_1', 'payment_intent': intent, 'amount': amount, 'amount_refunded': refunded}}}


def _sum(entry_type):
    return int(db.session.query(db.func.coalesce(db.func.sum(LedgerEntry.amount_cents), 0))
               .filter(LedgerEntry.entry_type == entry_type).scalar())


# ---- Stripe refunds ----

def test_a_full_refund_arrives_by_webhook_and_counts_on_its_own_day(app, seed, monkeypatch):
    oid = _in_db(app, _paid_order)
    resp = _hook(app, monkeypatch, _refund_event())
    assert resp.status_code == 200 and resp.get_json()['refund'] == 'order PMKC-M1'

    def check():
        o = db.session.get(Order, oid)
        entries = LedgerEntry.query.filter(LedgerEntry.entry_type.in_([L.REFUND, L.REFUND_TAX])).all()
        return (o.refunded_cents, o.is_refunded, sorted((e.entry_type, e.amount_cents, e.kc_date) for e in entries),
                L.pnl(date(2026, 10, 1), date(2026, 10, 31))['refunds'], L.pnl(date(2026, 11, 1), date(2026, 11, 30)))
    cents, flag, entries, october_refunds, november = _in_db(app, check)
    assert cents == 12050 and flag is True
    assert entries == [(L.REFUND, -11100, date(2026, 11, 5)), (L.REFUND_TAX, -950, date(2026, 11, 5))]
    assert october_refunds == 0                                 # the sale stays in October, the refund is November's
    assert november['refunds'] == -11100 and november['tax_collected'] == -950


def test_a_second_delivery_changes_nothing(app, seed, monkeypatch):
    _in_db(app, _paid_order)
    _hook(app, monkeypatch, _refund_event())
    before = _in_db(app, lambda: LedgerEntry.query.count())
    resp = _hook(app, monkeypatch, _refund_event())
    assert resp.status_code == 200
    assert _in_db(app, lambda: LedgerEntry.query.count()) == before


def test_partial_refunds_split_sale_and_tax_and_grow_by_adjustment(app, seed, monkeypatch):
    _in_db(app, _paid_order)
    _hook(app, monkeypatch, _refund_event(refunded=3000, created=_ts(2026, 11, 5)))
    _hook(app, monkeypatch, _refund_event(refunded=5000, created=_ts(2026, 11, 9)))

    def check():
        o = db.session.query(Order).first()
        return o.refunded_cents, o.is_refunded, _sum(L.REFUND), _sum(L.REFUND_TAX), LedgerEntry.query.filter_by(entry_type=L.REFUND).count()
    refunded, flag, sale_part, tax_part, rows = _in_db(app, check)
    assert refunded == 5000 and flag is False                   # not the whole order, so not marked refunded
    assert (sale_part, tax_part) == (-4606, -394) and sale_part + tax_part == -5000
    assert rows == 2                                            # the second refund is a new dated entry, not an edit


def test_refunds_never_exceed_what_was_paid(app, seed, monkeypatch):
    _in_db(app, _paid_order)
    _hook(app, monkeypatch, _refund_event(refunded=99999))
    assert _in_db(app, lambda: (_sum(L.REFUND), _sum(L.REFUND_TAX))) == (-11100, -950)


def test_refund_for_a_hand_made_invoice(app, seed, monkeypatch):
    def make():
        inv = ManualInvoice(number='INV-2026-0007', customer_name='Amy', email='a@example.com', tax_rate=10.0, shipping=0,
                            discount=0, items_json=json.dumps([{'description': 'Tees', 'qty': 10, 'unit': 20.0}]),
                            amount_paid=220.0, payment_method='Card', card_paid_intent_id='pi_inv', paid_at=datetime(2026, 9, 2, 18, 0))
        db.session.add(inv)
        db.session.commit()
        L.sync_all(force=True)
    _in_db(app, make)
    resp = _hook(app, monkeypatch, _refund_event(intent='pi_inv', amount=22000, refunded=11000))
    assert resp.get_json()['refund'] == 'invoice INV-2026-0007'
    assert _in_db(app, lambda: (_sum(L.REFUND), _sum(L.REFUND_TAX))) == (-10000, -1000)


def test_a_refund_with_no_matching_order_is_acknowledged(app, seed, monkeypatch):
    resp = _hook(app, monkeypatch, _refund_event(intent='pi_unknown'))
    assert resp.status_code == 200 and resp.get_json()['refund'] == 'no match'
    assert _hook(app, monkeypatch, _refund_event(refunded=0)).get_json()['refund'] == 'nothing to record'


def test_the_manual_refunded_tick_still_works_and_counts_everything(app, seed):
    def go():
        o = db.session.get(Order, _paid_order('PMKC-M2', 'pi_2'))
        o.is_refunded, o.refunded_at = True, datetime(2026, 12, 2, 18, 0)
        db.session.commit()
        L.sync_all(force=True)
        return _sum(L.REFUND), _sum(L.REFUND_TAX), LedgerEntry.query.filter_by(entry_type=L.REFUND).first().kc_date
    assert _in_db(app, go) == (-11100, -950, date(2026, 12, 2))


# ---- Stripe payouts ----

def _payout_event(kind='payout.paid', status='paid', cents=45000, pid='po_1'):
    return {'type': kind, 'data': {'object': {'id': pid, 'amount': cents, 'status': status, 'currency': 'usd',
                                              'arrival_date': _ts(2026, 10, 20, 12)}}}


def test_a_paid_payout_is_recorded_once_as_a_transfer(app, seed, monkeypatch):
    for _ in range(2):
        resp = _hook(app, monkeypatch, _payout_event())
        assert resp.status_code == 200

    def check():
        row = Payout.query.one()
        entries = LedgerEntry.query.filter_by(entry_type=L.PAYOUT).all()
        p = L.pnl(date(2026, 10, 1), date(2026, 10, 31))
        return row.amount_cents, row.status, row.arrival_date, [e.amount_cents for e in entries], p['net_profit'], p['total_expenses']
    assert _in_db(app, check) == (45000, 'paid', date(2026, 10, 20), [45000], 0, 0)      # a transfer is not income or expense


def test_a_payout_that_fails_after_being_paid_is_reversed(app, seed, monkeypatch):
    _hook(app, monkeypatch, _payout_event())
    _hook(app, monkeypatch, _payout_event(kind='payout.failed', status='failed'))
    assert _in_db(app, lambda: (Payout.query.one().status, _sum(L.PAYOUT), LedgerEntry.query.filter_by(entry_type=L.PAYOUT).count())) == ('failed', 0, 2)


def test_pending_payouts_are_listed_but_not_in_the_ledger(app, seed, monkeypatch):
    _hook(app, monkeypatch, _payout_event(kind='payout.created', status='pending'))
    assert _in_db(app, lambda: (Payout.query.count(), LedgerEntry.query.filter_by(entry_type=L.PAYOUT).count())) == (1, 0)


def test_payouts_page_lists_them(admin_client, app, seed, monkeypatch):
    _hook(app, monkeypatch, _payout_event())
    html = admin_client.get('/admin/operations/payouts').get_data(as_text=True)
    assert 'po_1' in html and '$450.00' in html and 'Oct 20, 2026' in html


# ---- PayPal ----

def test_paypal_refunds_are_picked_up_by_the_nightly_check(app, seed, monkeypatch):
    def go():
        _paid_order('PMKC-P1', 'pi_unused', payment_method='paypal', paypal_order_id='PP-1')
        _paid_order('PMKC-P2', 'pi_unused2', payment_method='paypal', paypal_order_id='PP-2')
        asked = []

        def fake(order):
            asked.append(order.paypal_order_id)
            return (3000, datetime(2026, 11, 3, 16, 0)) if order.paypal_order_id == 'PP-1' else (0, None)
        monkeypatch.setattr(M, '_paypal_refunds', fake)
        changed = M.check_paypal_refunds(limit=10)
        again = M.check_paypal_refunds(limit=10)
        L.sync_all(force=True)
        o = Order.query.filter_by(paypal_order_id='PP-1').first()
        return changed, again, sorted(set(asked)), o.refunded_cents, o.refund_checked_at is not None, _sum(L.REFUND) + _sum(L.REFUND_TAX)
    changed, again, asked, cents, checked, ledger_total = _in_db(app, go)
    assert (changed, again) == (1, 0) and asked == ['PP-1', 'PP-2'] and cents == 3000 and checked and ledger_total == -3000


def test_paypal_check_only_looks_at_paypal_orders(app, seed, monkeypatch):
    def go():
        _paid_order('PMKC-S1', 'pi_s1')                               # a Stripe order
        monkeypatch.setattr(M, '_paypal_refunds', lambda order: pytest.fail('asked PayPal about a Stripe order'))
        return M.check_paypal_refunds()
    assert _in_db(app, go) == 0


# ---- real fees on demand ----

def test_checking_for_real_fees_replaces_estimates_and_the_ledger_follows(admin_client, app, seed, monkeypatch):
    def make():
        o = _paid_order('PMKC-F1', 'pi_f1', processing_fee=3.99, processing_fee_is_actual=False)
        L.sync_all(force=True)
        return o
    oid = _in_db(app, make)
    import utils.payment_fees as pf
    monkeypatch.setattr(pf, 'fetch_actual_fee', lambda order: 3.64)
    html = admin_client.get('/admin/operations/reports?period=custom&from=2026-10-01&to=2026-10-31').get_data(as_text=True)
    assert 'Check for real fees now' in html
    assert admin_client.post('/admin/operations/reports/fees').status_code == 302

    def check():
        o = db.session.get(Order, oid)
        return o.processing_fee, o.processing_fee_is_actual, _sum(L.FEE)
    assert _in_db(app, check) == (3.64, True, -364)              # one adjustment entry carries the 35 cent difference
    again = admin_client.get('/admin/operations/reports?period=custom&from=2026-10-01&to=2026-10-31').get_data(as_text=True)
    assert 'Check for real fees now' not in again
