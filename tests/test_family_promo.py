"""Family at-cost promo (AIRMATTRESS): pricing + cash-only checkout."""
import json

from models import Order
from routes.checkout import calculate_totals
from utils.family_promo import (
    is_family_promo_code,
    family_promo_totals,
    apply_family_at_cost_prices,
)


def test_family_promo_code_matches_config(app):
    with app.app_context():
        assert is_family_promo_code('AIRMATTRESS')
        assert is_family_promo_code('airmattress')
        assert not is_family_promo_code('WRONG')
        assert not is_family_promo_code('')


def test_family_totals_use_wholesale_plus_flat_fee(app, seed):
    cart = [{
        'product_id': seed['tee_id'],
        'quantity': 2,
        'unit_price': 30.00,
        'print_width': 10,
        'print_height': 10,
    }]
    with app.test_request_context():
        totals = calculate_totals(cart, 'shipping', family_promo=True)
    # wholesale $6 + DTF (10*10*0.05=$5) = $11/unit → $22 + $5 fee
    assert totals['shipping_cost'] == 0
    assert totals['tax'] == 0
    assert totals['flat_fee'] == 5.0
    assert totals['subtotal'] == 22.0
    assert totals['total'] == 27.0
    assert cart[0]['unit_price'] == 11.0


def test_family_totals_without_print_dims_are_wholesale_only(app, seed):
    cart = [{
        'product_id': seed['tee_id'],
        'quantity': 1,
        'unit_price': 30.00,
    }]
    with app.app_context():
        apply_family_at_cost_prices(cart)
        totals = family_promo_totals(cart)
    assert cart[0]['unit_price'] == 6.0
    assert totals['total'] == 11.0  # 6 + 5


def test_apply_promo_endpoint(client, seed, app):
    client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black',
        'quantity': 1, 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    })
    resp = client.post(
        '/checkout/apply-promo',
        data=json.dumps({'code': 'AIRMATTRESS'}),
        content_type='application/json',
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['success'] is True
    assert payload['family_promo'] is True
    assert payload['totals']['tax'] == 0
    assert payload['totals']['shipping_cost'] == 0
    assert payload['totals']['flat_fee'] == 5.0

    bad = client.post(
        '/checkout/apply-promo',
        data=json.dumps({'code': 'NOPE'}),
        content_type='application/json',
    )
    assert bad.status_code == 400


def test_family_cash_checkout_creates_pending_order(client, seed, app):
    client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black',
        'quantity': 1, 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
        'print_width': 10, 'print_height': 10,
    })
    with client.session_transaction() as sess:
        sess['family_promo_code'] = 'AIRMATTRESS'

    resp = client.post(
        '/checkout/complete',
        data=json.dumps({
            'payment_method': 'cash',
            'shipping_method': 'pickup',
            'email': 'family@example.com',
            'first_name': 'Fam',
            'last_name': 'Member',
            'phone': '8165550100',
            'promo_code': 'AIRMATTRESS',
            'checkout_token': 'family-promo-token-1',
        }),
        content_type='application/json',
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True

    with app.app_context():
        order = Order.query.filter_by(order_number=data['order_number']).first()
        assert order is not None
        assert order.payment_method == 'cash'
        assert order.payment_status == 'pending'
        assert order.amount_paid == 0.0
        assert order.promo_code == 'AIRMATTRESS'
        assert order.tax == 0
        assert order.shipping_cost == 0
        assert order.total == order.subtotal + 5.0


def test_family_promo_rejects_card(client, seed, app):
    client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black',
        'quantity': 1, 'placement': 'center_chest',
        'design_id': seed['free_design_id'],
    })
    with client.session_transaction() as sess:
        sess['family_promo_code'] = 'AIRMATTRESS'

    resp = client.post(
        '/checkout/complete',
        data=json.dumps({
            'payment_method': 'stripe',
            'payment_id': 'pi_fake',
            'shipping_method': 'pickup',
            'email': 'family@example.com',
            'first_name': 'Fam',
            'last_name': 'Member',
            'promo_code': 'AIRMATTRESS',
            'checkout_token': 'family-promo-token-2',
        }),
        content_type='application/json',
    )
    assert resp.status_code == 400
    assert resp.get_json()['error_code'] == 'FAMILY_PROMO_CASH_ONLY'
