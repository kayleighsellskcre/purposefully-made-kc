"""Promo codes and free shipping: priced on the server, taxed after the discount, counted once, never below $1."""
from datetime import datetime, timedelta

import pytest

from models import Coupon, Order, db
from routes.checkout import calculate_totals
from tests.conftest import ADMIN_EMAIL, PASSWORD
from utils import coupons as CP
from utils.site_settings import set_setting


def _code(app, code='SAVE10', **kw):
    with app.app_context():
        db.session.add(Coupon(code=code, **kw))
        db.session.commit()


CART = lambda seed: [{'product_id': seed['tee_id'], 'quantity': 2, 'unit_price': 30.00}]


def test_percent_code_lowers_the_amount_tax_is_charged_on(app, seed):
    _code(app, percent_off=10)
    with app.test_request_context():
        t = calculate_totals(CART(seed), 'pickup', coupon_code='save10')
        assert t['discount_applied'] == 6.0 and t['subtotal'] == 54.0 and t['coupon_code'] == 'SAVE10'
        assert t['tax'] == round(54.0 * 0.095, 2) and t['total'] == round(54.0 + t['tax'], 2)
        assert calculate_totals(CART(seed), 'pickup')['discount_applied'] == 0.0


def test_dollar_code_never_takes_an_order_below_one_dollar(app, seed):
    _code(app, amount_off=500)
    with app.test_request_context():
        t = calculate_totals(CART(seed), 'pickup', coupon_code='SAVE10')
        assert t['subtotal'] == 1.0 and t['discount_applied'] == 59.0


def test_bad_codes_are_refused_with_a_plain_reason(app, seed):
    with app.app_context():
        _code(app, 'OLD', percent_off=10, expires_at=datetime.utcnow() - timedelta(days=1))
        _code(app, 'USEDUP', percent_off=10, max_uses=2, uses=2)
        _code(app, 'BIG', percent_off=10, min_subtotal=200)
        _code(app, 'OFF', percent_off=10, active=False)
        for code, word in [('OLD', 'expired'), ('USEDUP', 'most times'), ('BIG', 'at least $200.00'), ('OFF', 'not valid'), ('NOPE', 'not valid')]:
            found = CP.find(code)
            why = CP.problem(found, 60.0)
            assert why and word in why, (code, why)
    with app.test_request_context():
        assert calculate_totals(CART(seed), 'pickup', coupon_code='OLD')['discount_applied'] == 0.0


def test_free_shipping_from_a_code_or_an_order_total(app, seed):
    app.config['SHIPPING_FLAT_RATE'] = 11.0
    _code(app, 'SHIPFREE', free_shipping=True)
    with app.test_request_context():
        assert calculate_totals(CART(seed), 'shipping')['shipping_cost'] == 11.0
        assert calculate_totals(CART(seed), 'shipping', coupon_code='SHIPFREE')['shipping_cost'] == 0
        set_setting(CP.FREE_SHIP_KEY, '75')
        t = calculate_totals(CART(seed), 'shipping')
        assert t['shipping_cost'] == 11.0 and t['free_ship_away'] == 15.0
        set_setting(CP.FREE_SHIP_KEY, '60')
        assert calculate_totals(CART(seed), 'shipping')['shipping_cost'] == 0
        set_setting(CP.FREE_SHIP_KEY, '')
        assert calculate_totals(CART(seed), 'shipping')['shipping_cost'] == 11.0


def test_applying_a_code_at_checkout_and_the_owner_can_make_one(app, seed):
    admin = app.test_client()
    admin.post('/auth/login', data={'email': ADMIN_EMAIL, 'password': PASSWORD})
    admin.post('/admin/operations/site-settings', data={'section': 'coupon_new', 'code': 'spring10', 'percent_off': '10'})
    admin.post('/admin/operations/site-settings', data={'section': 'coupon_new', 'code': 'spring10', 'percent_off': '10'})   # duplicate
    admin.post('/admin/operations/site-settings', data={'section': 'coupon_new', 'code': 'bad code!', 'percent_off': '10'})
    admin.post('/admin/operations/site-settings', data={'section': 'shipping', 'free_shipping_min': '75'})
    with app.app_context():
        assert [c.code for c in Coupon.query.all()] == ['SPRING10']
        assert CP.free_shipping_min() == 75.0
    page = admin.get('/admin/operations/site-settings').get_data(as_text=True)
    assert 'SPRING10' in page and 'Promo codes' in page


def test_the_code_is_counted_when_an_order_is_made(app, seed):
    _code(app, percent_off=10)
    with app.app_context():
        order = Order(order_number='PMKC-CP1', email='a@b.co', first_name='A', last_name='B', subtotal=54.0, total=59.13,
                      coupon_code='SAVE10', discount_applied=6.0, payment_status='paid', status='paid')
        db.session.add(order)
        db.session.flush()
        CP.record_use(order)
        CP.record_use(Order(order_number='x', email='x@y.co', subtotal=1, total=1))      # no code, nothing counted
        db.session.commit()
        assert CP.find('SAVE10').uses == 1


def test_a_code_applied_at_checkout_flows_into_the_card_order(client, seed, app):
    from unittest.mock import patch
    from tests.test_checkout import TAX_RATE, _cash_payload, _fill_cart, _stripe_intent
    _code(app, percent_off=10)
    _fill_cart(client, seed)
    applied = client.post('/checkout/apply-promo', json={'code': 'save10'})
    assert applied.status_code == 200 and applied.get_json()['totals']['discount_applied'] == 3.0
    assert 'SAVE10' in client.get('/checkout/').get_data(as_text=True)
    net = 27.0
    expected = round(net + round(net * TAX_RATE, 2), 2)
    with patch('stripe.PaymentIntent.retrieve', return_value=_stripe_intent(int(round(expected * 100)))):
        body = client.post('/checkout/complete', json=_cash_payload(payment_method='stripe', payment_id='pi_test_123')).get_json()
    assert body['success'] is True
    with app.app_context():
        order = Order.query.filter_by(order_number=body['order_number']).one()
        assert (order.coupon_code, order.discount_applied, order.subtotal, order.total) == ('SAVE10', 3.0, 27.0, expected)
        assert CP.find('SAVE10').uses == 1
    page = client.get(f'/checkout/confirmation/{body["order_number"]}')
    assert page.status_code == 200


def test_a_bad_code_is_refused_and_changes_nothing(client, seed, app):
    from tests.test_checkout import _fill_cart
    _fill_cart(client, seed)
    resp = client.post('/checkout/apply-promo', json={'code': 'NOPE'})
    assert resp.status_code == 400 and 'not valid' in resp.get_json()['error']
    _code(app, 'BIG', percent_off=10, min_subtotal=500)
    assert 'at least $500.00' in client.post('/checkout/apply-promo', json={'code': 'BIG'}).get_json()['error']
    with client.session_transaction() as sess:
        assert not sess.get('coupon_code')
