"""True profit = customer paid - sales tax - Stripe/PayPal fee - cost of goods."""
from types import SimpleNamespace
from unittest import mock

from models import db, Order
from utils import payment_fees
from utils.payment_fees import estimate_fee, true_profit, refresh_processing_fee


def _ns(**kw):
    base = dict(payment_method='stripe', total=30.66, amount_paid=30.66, tax=2.66,
                cost_of_goods=9.48, processing_fee=None, processing_fee_is_actual=False,
                payment_intent_id='pi_1', paypal_order_id=None, id=1)
    base.update(kw)
    return SimpleNamespace(**base)


def test_estimates_use_standard_rates():
    assert estimate_fee(_ns()) == round(30.66 * 0.029 + 0.30, 2)
    assert estimate_fee(_ns(payment_method='paypal')) == round(30.66 * 0.0349 + 0.49, 2)
    assert estimate_fee(_ns(payment_method='cash')) == 0.0


def test_true_profit_takes_out_tax_fee_and_goods():
    order = _ns(processing_fee=1.19)
    assert true_profit(order) == round(30.66 - 2.66 - 1.19 - 9.48, 2)


def test_cash_orders_have_no_fee(app):
    order = _ns(payment_method='cash')
    with app.app_context():
        refresh_processing_fee(order)
    assert order.processing_fee == 0.0 and order.processing_fee_is_actual is True


def test_actual_stripe_fee_replaces_estimate(app):
    order = _ns()
    intent = SimpleNamespace(latest_charge=SimpleNamespace(
        balance_transaction=SimpleNamespace(fee=119)))
    with app.app_context():
        app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
        with mock.patch('stripe.PaymentIntent.retrieve', return_value=intent):
            assert refresh_processing_fee(order) is True
    assert order.processing_fee == 1.19 and order.processing_fee_is_actual is True
    # Once actual, it is never fetched again.
    with app.app_context(), mock.patch.object(payment_fees, 'fetch_actual_fee') as fetch:
        assert refresh_processing_fee(order) is False
        fetch.assert_not_called()


def test_actual_paypal_fee(app):
    order = _ns(payment_method='paypal', payment_intent_id=None, paypal_order_id='EC-1')
    body = {'purchase_units': [{'payments': {'captures': [
        {'seller_receivable_breakdown': {'paypal_fee': {'value': '1.56'}}}]}}]}
    with app.app_context():
        with mock.patch('routes.checkout._get_paypal_access_token', return_value='tok'), \
             mock.patch('requests.get', return_value=SimpleNamespace(status_code=200, json=lambda: body)):
            refresh_processing_fee(order)
    assert order.processing_fee == 1.56 and order.processing_fee_is_actual is True


def test_lookup_failure_falls_back_to_estimate(app):
    order = _ns()
    with app.app_context():
        app.config['STRIPE_SECRET_KEY'] = 'sk_test_fake'
        with mock.patch('stripe.PaymentIntent.retrieve', side_effect=RuntimeError('down')):
            refresh_processing_fee(order)
    assert order.processing_fee == estimate_fee(order)
    assert order.processing_fee_is_actual is False


def _order(app, seed, **kw):
    values = dict(user_id=seed['customer_id'], first_name='Casey', last_name='Customer',
                  email='customer-test@example.com', subtotal=28.00, tax=2.66, total=30.66,
                  amount_paid=30.66, payment_status='paid', status='paid',
                  production_stage='pressed', fulfillment_method='pickup',
                  payment_method='paypal', paypal_order_id=None)
    values.update(kw)
    with app.app_context():
        order = Order(**values)
        db.session.add(order)
        db.session.commit()
        return order.id


def test_order_page_shows_where_the_money_went(admin_client, app, seed):
    order_id = _order(app, seed)
    admin_client.post(f'/admin/orders/{order_id}/update-details',
                      data={'order_type': 'retail', 'due_date': '2026-10-20', 'cost_of_goods': '9.48'})
    html = admin_client.get(f'/admin/orders/{order_id}').get_data(as_text=True)
    fee = round(30.66 * 0.0349 + 0.49, 2)
    expected = round(30.66 - 2.66 - fee - 9.48, 2)
    assert 'Where the Money Went' in html
    assert 'PayPal fee' in html
    assert f'${expected:.2f}' in html
    with app.app_context():
        order = Order.query.get(order_id)
        assert order.profit == expected
        assert order.processing_fee == fee


def test_financial_page_separates_tax_fees_and_profit(admin_client, app, seed):
    _order(app, seed, payment_method='cash', amount_paid=30.66)
    html = admin_client.get('/admin/operations/financial').get_data(as_text=True)
    assert 'Sales Tax Collected' in html
    assert 'Stripe &amp; PayPal Fees' in html
    assert 'True Profit' in html
    assert '$2.66' in html
