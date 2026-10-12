"""Group order audit, part 2: pay-for-everyone stores, checkout safety and order emails."""
import json
from datetime import datetime, timedelta

from models import db, Collection, GroupRosterEntry, Order
from tests.test_group_order_audit import _set, _slug_of
from tests.test_org_fan_wear import _build, _org_slug, _store


# ── Pay-for-everyone stores stay untouched by shared Fan Wear ────────────────

def _roster_state(app, name):
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        return (coll.team_store_config, coll.allowed_colors, sorted(p.id for p in coll.products))


def test_shared_fan_wear_leaves_a_pay_for_everyone_store_alone(admin_client, app, seed):
    from utils.group_roster import ORGANIZER_PAYS
    a, b, c = _build(admin_client, app, seed)
    name = 'Basketball: Rainbow Cheetahs'
    _set(app, name, payment_mode=ORGANIZER_PAYS)
    before = _roster_state(app, name)
    soccer_before = _roster_state(app, 'Soccer: Rainbow Cheetahs')
    resp = admin_client.post(f'/org/{_org_slug(app)}/fan-wear', data={
        'products': [str(seed['hoodie_id'])],
        'allowed_colors': [f"p:{seed['hoodie_id']}||Black"], 'color_picker_present': '1',
        'design_ids': [str(a), str(b), str(c)], 'fan_designs': [str(c)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert _roster_state(app, name) == before                             # untouched
    assert _roster_state(app, 'Soccer: Rainbow Cheetahs') != soccer_before  # the others updated


def test_fan_wear_page_does_not_list_a_pay_for_everyone_team(admin_client, app, seed):
    from utils.group_roster import ORGANIZER_PAYS
    _build(admin_client, app, seed)
    _set(app, 'Basketball: Rainbow Cheetahs', payment_mode=ORGANIZER_PAYS)
    html = admin_client.get(f'/org/{_org_slug(app)}/fan-wear').get_data(as_text=True)
    note = html.split('Changes here apply to')[1].split('</p>')[0]
    assert 'Soccer' in note and 'Basketball' not in note


def test_a_pay_for_everyone_stores_edit_page_does_not_sync_fan_wear(admin_client, app, seed):
    from utils.group_roster import ORGANIZER_PAYS
    _build(admin_client, app, seed)
    name = 'Basketball: Rainbow Cheetahs'
    _set(app, name, payment_mode=ORGANIZER_PAYS)
    html = admin_client.get(f'/admin/collections/{_store(app, name)[0]}/edit').get_data(as_text=True)
    assert 'name="sync_fan_to_org"' not in html


# ── Checkout safety for group orders ─────────────────────────────────────────

def _cart_a_group_item(client, seed, app):
    from tests.test_checkout import _fill_cart
    _fill_cart(client, seed, app=app, allow_cash=True)


def _try_cash_checkout(client, token):
    return client.post('/checkout/complete', json={
        'payment_method': 'cash', 'shipping_method': 'pickup', 'email': 'buyer@example.com',
        'first_name': 'Casey', 'last_name': 'Customer', 'phone': '816-555-0100',
        'checkout_token': token,
    })


def test_checkout_is_refused_if_the_deadline_passes_while_the_cart_is_open(client, seed, app):
    _cart_a_group_item(client, seed, app)
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.order_deadline = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
    resp = _try_cash_checkout(client, 'tok-audit-late')
    assert not (resp.get_json() or {}).get('success')
    with app.app_context():
        assert Order.query.count() == 0


def test_checkout_is_refused_if_the_store_is_switched_off_while_the_cart_is_open(client, seed, app):
    _cart_a_group_item(client, seed, app)
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.is_active = False
        db.session.commit()
    resp = _try_cash_checkout(client, 'tok-audit-off')
    assert not (resp.get_json() or {}).get('success')
    with app.app_context():
        assert Order.query.count() == 0


# ── Order emails name the group ──────────────────────────────────────────────

def test_order_emails_say_which_group_the_order_is_for(client, seed, outbox, app):
    from tests.test_emails import _place_cash_order
    _place_cash_order(client, seed, app)
    with app.app_context():
        group = db.session.get(Collection, seed['collection_id']).name
    alert = next(m for m in outbox if 'new order' in m.subject.lower())
    receipt = next(m for m in outbox if 'receipt' in m.subject.lower())
    assert group in alert.subject and group in alert.body and group in alert.html
    assert group in receipt.body and group in receipt.html


def test_a_regular_shop_order_email_has_no_group_line(client, seed, outbox, app):
    from tests.test_checkout import _cash_payload
    client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
        'placement': 'center_chest', 'design_id': seed['free_design_id'],
    })
    resp = client.post('/checkout/complete', json=_cash_payload(payment_method='card'))
    # whichever way a plain order ends, no email may mention a group order
    for msg in outbox:
        assert 'Group order' not in (msg.body or '')


# ── Size form: a double tap counts once ──────────────────────────────────────

def test_a_double_submitted_size_is_counted_once(guest, seed, app):
    from tests.test_group_order_roster import _in_db, _make_roster_store, _submit
    slug = _make_roster_store(app, seed)
    _submit(guest, slug, 'Ava', 'Lopez', 'M')
    _submit(guest, slug, 'ava', 'LOPEZ', 'M')          # same person, same size, a moment later
    _submit(guest, slug, 'Ava', 'Lopez', 'L')          # a different size is a different line

    def check():
        rows = GroupRosterEntry.query.filter_by(collection_id=seed['collection_id']).all()
        assert sorted((r.first_name, r.size) for r in rows) == [('Ava', 'L'), ('Ava', 'M')]
    _in_db(app, check)
