"""Donations: shirts given away. A winner picks from a private link, the free order is made, and its cost is booked as a donation."""
import json
import re

import pytest

from models import Collection, Donation, LedgerEntry, Order, db
from tests.conftest import ADMIN_EMAIL, _login
from utils import ledger as L


@pytest.fixture()
def admin(app, seed):
    c = app.test_client()
    assert _login(c, ADMIN_EMAIL).status_code == 200
    return c


def _donation(app, seed, admin):
    with app.app_context():
        group = db.session.get(Collection, seed['collection_id'])
        group.allowed_design_ids = json.dumps([seed['free_design_id']])
        db.session.commit()
    resp = admin.post('/admin/donations', data={
        'recipient': 'Riverview Elementary PTA', 'occasion': 'December silent auction', 'donated_on': '2026-12-05',
        'winners': '4', 'collection_id': seed['collection_id'], 'product_id': [seed['tee_id']], 'note': ''})
    assert resp.status_code == 302
    return int(resp.headers['Location'].rstrip('/').split('/')[-1])


def _links(app, did):
    with app.app_context():
        return [c.token for c in db.session.get(Donation, did).claims]


def test_a_donation_makes_one_private_link_per_winner(app, seed, admin):
    did = _donation(app, seed, admin)
    tokens = _links(app, did)
    assert len(tokens) == 4 and len(set(tokens)) == 4
    page = admin.get(f'/admin/donations/{did}').get_data(as_text=True)
    assert all(t in page for t in tokens)
    assert 'Donations' in admin.get('/admin/collections').get_data(as_text=True)


def test_the_winner_page_asks_for_design_color_and_size(app, seed, admin):
    did = _donation(app, seed, admin)
    html = app.test_client().get(f'/gift/{_links(app, did)[0]}').get_data(as_text=True)
    assert 'Choose your shirt' in html and 'name="design_id"' in html and 'name="color"' in html and 'name="size"' in html
    assert app.test_client().get('/gift/not-a-real-link').status_code == 404


def test_a_chosen_shirt_is_a_free_order_and_a_donation_write_off(app, seed, admin):
    did = _donation(app, seed, admin)
    token = _links(app, did)[0]
    voter = app.test_client()
    bad = voter.post(f'/gift/{token}', data={'design_id': seed['free_design_id'], 'color': 'Black', 'size': 'M'})
    assert bad.status_code == 400                                              # no name or email yet
    ok = voter.post(f'/gift/{token}', data={
        'product_id': seed['tee_id'], 'design_id': seed['free_design_id'], 'color': 'Black', 'size': 'M',
        'first_name': 'Pat', 'last_name': 'Winner', 'email': 'pat@example.com', 'fulfillment': 'pickup'})
    assert ok.status_code == 302
    again = voter.post(f'/gift/{token}', data={'product_id': seed['tee_id'], 'design_id': seed['free_design_id'], 'color': 'White',
                                               'size': 'L', 'first_name': 'Pat', 'email': 'pat@example.com'})
    assert again.status_code == 200 or again.status_code == 400
    with app.app_context():
        orders = Order.query.filter_by(payment_method='donation').all()
        assert len(orders) == 1                                                # one chosen shirt per link
        order = orders[0]
        assert order.total == 0 and order.payment_status == 'paid' and order.production_stage == 'order_received'
        assert order.cost_of_goods and order.cost_of_goods > 0
        L.sync_all(force=True)
        rows = LedgerEntry.query.filter_by(order_id=order.id).all()
        assert [(r.entry_type, r.category) for r in rows] == [(L.EXPENSE, L.DONATION_CATEGORY)]
        assert rows[0].amount_cents == -L.to_cents(order.cost_of_goods)
        day = rows[0].kc_date
        p = L.pnl(day, day)
        assert p['cogs'] == 0 and (L.DONATION_CATEGORY, L.to_cents(order.cost_of_goods)) in p['expenses']
    page = admin.get(f'/admin/donations/{did}').get_data(as_text=True)
    assert '1 of 4' in page and 'Chosen' in page


def test_only_listed_designs_and_shirts_can_be_picked(app, seed, admin):
    did = _donation(app, seed, admin)
    token = _links(app, did)[0]
    resp = app.test_client().post(f'/gift/{token}', data={
        'product_id': seed['hoodie_id'], 'design_id': seed['free_design_id'], 'color': 'Black', 'size': 'M',
        'first_name': 'Pat', 'email': 'pat@example.com'})
    assert resp.status_code == 400
    with app.app_context():
        assert Order.query.filter_by(payment_method='donation').count() == 0
