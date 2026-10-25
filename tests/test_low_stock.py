"""Running low: reorder numbers, the digest line (once per item), the Monday list, and the inventory update fix."""
import threading
from datetime import datetime

import pytest

from models import ApparelInventory, Supply, TransferInventory, db
from utils import daily_digest as D
from utils import ledger as L
from utils import low_stock as LS


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


def _stock():
    a = ApparelInventory(brand='Bella+Canvas 3001', color='Black', size='M', quantity=3, cost_per_unit=4.0, reorder_threshold=5)
    ok = ApparelInventory(brand='Bella+Canvas 3001', color='White', size='M', quantity=20, reorder_threshold=5)
    off = ApparelInventory(brand='Comfort Colors', color='Sand', size='L', quantity=0, reorder_threshold=0)     # not tracked
    s = Supply(category='heat_tape', name='Heat tape', quantity=1, reorder_threshold=2)
    t = TransferInventory(design_name='Team Logo', size='adult', quantity=0, reorder_threshold=10)
    db.session.add_all([a, ok, off, s, t])
    db.session.commit()
    return a, ok, off, s, t


@pytest.fixture()
def clean_stock(app, seed):
    def wipe():
        for model in (ApparelInventory, Supply, TransferInventory):
            model.query.delete()
        db.session.commit()
    _in_db(app, wipe)


def test_only_tracked_items_at_or_under_their_number_are_low(app, seed, clean_stock):
    def go():
        _stock()
        items = LS.low_items()
        assert [i['name'] for i in items] == ['Team Logo adult', 'Bella+Canvas 3001 Black M', 'Heat tape']       # furthest under its reorder number first
        assert {i['kind'] for i in items} == {'Transfer', 'Heat Tape', 'Blank'}
        assert 'Comfort Colors Sand L' not in [i['name'] for i in items]
    _in_db(app, go)


def test_an_item_is_news_once_until_it_is_restocked(app, seed, clean_stock):
    def go():
        a, *_ = _stock()
        assert len(LS.newly_low()) == 3
        LS.mark_seen()
        assert LS.newly_low() == []
        a.quantity = 30                                              # restocked
        db.session.commit()
        LS.mark_seen()
        a.quantity = 2                                               # runs low again
        db.session.commit()
        assert [i['name'] for i in LS.newly_low()] == ['Bella+Canvas 3001 Black M']
    _in_db(app, go)


NOW = datetime(2026, 10, 26, 7, 0, tzinfo=L.CENTRAL)


def test_the_morning_digest_reports_new_lows_then_stays_quiet(app, seed, clean_stock, outbox):
    def go():
        _stock()
        assert any(s['key'] == 'lowstock' and s['count'] == 3 for s in D.daily_sections(NOW))
        assert D.send_daily(NOW) is True
        assert not any(s['key'] == 'lowstock' for s in D.daily_sections(NOW))          # already reported
        assert D.send_daily(NOW + __import__('datetime').timedelta(days=1)) is False   # nothing else, so no email
    _in_db(app, go)
    assert len(outbox) == 1 and 'Heat tape' in outbox[0].body and '/admin/operations/low-stock' in outbox[0].body


def test_the_monday_summary_lists_everything_still_low(app, seed, clean_stock, outbox):
    def go():
        _stock()
        LS.mark_seen()
        assert D.send_weekly(NOW) is True
    _in_db(app, go)
    assert 'Still running low' in outbox[0].body and 'Team Logo' in outbox[0].body


def test_a_quantity_update_no_longer_wipes_cost_or_reorder_number(admin_client, app, seed, clean_stock):
    ids = _in_db(app, lambda: [r.id for r in _stock()])
    admin_client.post(f'/admin/operations/inventory/apparel/{ids[0]}/update', data={'quantity': '9'})
    admin_client.post(f'/admin/operations/inventory/supply/{ids[3]}/update', data={'quantity': '7'})
    admin_client.post(f'/admin/operations/inventory/transfer/{ids[4]}/update', data={'quantity': '12'})

    def check():
        a, s, t = db.session.get(ApparelInventory, ids[0]), db.session.get(Supply, ids[3]), db.session.get(TransferInventory, ids[4])
        return (a.quantity, a.cost_per_unit, a.reorder_threshold, s.quantity, s.reorder_threshold, t.quantity, t.reorder_threshold)
    assert _in_db(app, check) == (9, 4.0, 5, 7, 2, 12, 10)


def test_pages_for_admin(admin_client, app, seed, clean_stock):
    _in_db(app, _stock)
    low = admin_client.get('/admin/operations/low-stock')
    assert low.status_code == 200 and b'Heat tape' in low.data and b'Out' in low.data
    inv = admin_client.get('/admin/operations/inventory')
    assert inv.status_code == 200 and b'3 items running low' in inv.data


def test_low_stock_page_is_closed_to_guests(guest):
    assert guest.get('/admin/operations/low-stock').status_code in (301, 302, 303, 401, 403, 404)
