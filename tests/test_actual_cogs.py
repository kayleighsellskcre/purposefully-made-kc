"""Actual supplier costs typed into an order must survive reopening the order."""
from models import db, Order


def _order(app, seed, total=28.47):
    with app.app_context():
        order = Order(
            user_id=seed['customer_id'],
            first_name='Casey',
            last_name='Customer',
            email='customer-test@example.com',
            subtotal=total,
            total=total,
            payment_status='paid',
            status='paid',
            production_stage='pressed',
            fulfillment_method='pickup',
        )
        db.session.add(order)
        db.session.commit()
        return order.id


def _details(order_id, **overrides):
    data = {'order_type': 'retail', 'due_date': '2026-10-20', 'refund_notes': ''}
    data.update(overrides)
    return data


def _load(app, order_id):
    with app.app_context():
        order = Order.query.get(order_id)
        return order.cost_of_goods, order.profit, order.cogs_is_actual


def test_typed_cost_sticks_after_reopening(admin_client, app, seed):
    order_id = _order(app, seed)
    html = admin_client.get(f'/admin/orders/{order_id}').get_data(as_text=True)
    assert 'Estimate</span>' in html
    estimate, _, actual = _load(app, order_id)
    assert not actual

    admin_client.post(f'/admin/orders/{order_id}/update-details',
                      data=_details(order_id, cost_of_goods='9.06', profit=''))
    assert _load(app, order_id) == (9.06, 19.41, True)

    # Opening the order again used to overwrite this with the estimate.
    html = admin_client.get(f'/admin/orders/{order_id}').get_data(as_text=True)
    assert _load(app, order_id) == (9.06, 19.41, True)
    assert 'Actual</span>' in html
    assert 'value="9.06"' in html


def test_saving_other_fields_keeps_estimate_unlocked(admin_client, app, seed):
    order_id = _order(app, seed)
    admin_client.get(f'/admin/orders/{order_id}')
    estimate, _, _ = _load(app, order_id)
    admin_client.post(f'/admin/orders/{order_id}/update-details',
                      data=_details(order_id, cost_of_goods=f'{estimate:.2f}', due_date='2026-11-01'))
    assert _load(app, order_id)[2] is False


def test_reset_goes_back_to_estimate(admin_client, app, seed):
    order_id = _order(app, seed)
    admin_client.get(f'/admin/orders/{order_id}')
    estimate, _, _ = _load(app, order_id)
    admin_client.post(f'/admin/orders/{order_id}/update-details',
                      data=_details(order_id, cost_of_goods='5.55'))
    assert _load(app, order_id)[2] is True

    admin_client.post(f'/admin/orders/{order_id}/update-details',
                      data=_details(order_id, cost_of_goods='5.55', cogs_reset='on'))
    admin_client.get(f'/admin/orders/{order_id}')
    cogs, _, actual = _load(app, order_id)
    assert actual is False
    assert cogs == estimate
