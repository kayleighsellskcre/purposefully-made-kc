"""Moving finished orders off the workflow and onto All Completed."""
from datetime import datetime
from types import SimpleNamespace

from models import db, Order
from utils.production_stages import apply_stage, complete_status_for, orders_for_stage


def test_complete_status_follows_pickup_or_shipping():
    assert complete_status_for(SimpleNamespace(fulfillment_method='pickup')) == 'picked_up'
    assert complete_status_for(SimpleNamespace(fulfillment_method='shipping')) == 'shipped'
    assert complete_status_for(SimpleNamespace(fulfillment_method=None)) == 'completed'


def test_apply_stage_completed_leaves_the_open_workflow():
    order = SimpleNamespace(
        fulfillment_method='pickup',
        status='ready',
        production_stage='packaged_ready',
        updated_at=None,
    )
    assert apply_stage(order, 'completed') is True
    assert order.status == 'picked_up'
    assert order.production_stage == 'completed'
    assert order.updated_at is not None


def _packaged_order(app, seed, **kwargs):
    values = dict(
        user_id=seed['customer_id'],
        first_name='Casey',
        last_name='Customer',
        email='customer-test@example.com',
        subtotal=30,
        total=30,
        payment_status='paid',
        status='ready',
        production_stage='packaged_ready',
        fulfillment_method='pickup',
    )
    values.update(kwargs)
    with app.app_context():
        order = Order(**values)
        db.session.add(order)
        db.session.commit()
        return order.id, order.order_number


def test_admin_can_move_a_packaged_order_to_all_completed(admin_client, app, seed):
    order_id, number = _packaged_order(app, seed)

    resp = admin_client.post(
        f'/admin/orders/{order_id}/update-stage',
        data={'stage': 'completed'},
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302)
    assert '/admin/orders/completed' in (resp.headers.get('Location') or '')

    html = admin_client.get('/admin/orders/completed').get_data(as_text=True)
    assert number in html
    assert datetime.utcnow().strftime('%B %Y') in html
    assert 'Move to All Completed' not in html

    with app.app_context():
        order = Order.query.get(order_id)
        assert order.status == 'picked_up'
        assert order.production_stage == 'completed'
        assert order.id not in [row.id for row in orders_for_stage('packaged_ready').all()]


def test_workflow_offers_move_to_all_completed_on_packaged_cards(admin_client, app, seed):
    _packaged_order(app, seed)
    html = admin_client.get('/admin/operations/workflow').get_data(as_text=True)
    assert 'Move to All Completed' in html
    assert 'value="completed"' in html


def test_order_detail_can_move_to_all_completed(admin_client, app, seed):
    order_id, number = _packaged_order(app, seed, fulfillment_method='shipping')
    html = admin_client.get(f'/admin/orders/{order_id}').get_data(as_text=True)
    assert 'All Completed' in html

    resp = admin_client.post(
        f'/admin/orders/{order_id}/update-status',
        data={'status': 'completed'},
        follow_redirects=False,
    )
    assert '/admin/orders/completed' in (resp.headers.get('Location') or '')
    with app.app_context():
        order = Order.query.get(order_id)
        assert order.status == 'shipped'
        assert number == order.order_number


def test_bulk_move_sends_orders_to_all_completed(admin_client, app, seed):
    order_id, number = _packaged_order(app, seed)
    resp = admin_client.post(
        '/admin/orders/bulk-update-stage',
        json={'stage': 'completed', 'order_ids': [order_id]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['stage'] == 'completed'

    html = admin_client.get('/admin/orders/completed').get_data(as_text=True)
    assert number in html


def test_completed_orders_are_grouped_by_month_and_year(admin_client, app, seed):
    with app.app_context():
        january = Order(
            user_id=seed['customer_id'],
            first_name='Jan',
            last_name='Done',
            email='jan@example.com',
            subtotal=20,
            total=20,
            payment_status='paid',
            status='picked_up',
            production_stage='completed',
            created_at=datetime(2026, 1, 8),
            updated_at=datetime(2026, 1, 12),
        )
        february = Order(
            user_id=seed['customer_id'],
            first_name='Feb',
            last_name='Shipped',
            email='feb@example.com',
            subtotal=20,
            total=20,
            payment_status='paid',
            status='shipped',
            production_stage='completed',
            created_at=datetime(2026, 2, 1),
            updated_at=datetime(2026, 2, 4),
        )
        db.session.add_all([january, february])
        db.session.commit()
        jan_number = january.order_number
        feb_number = february.order_number

    html = admin_client.get('/admin/orders/completed').get_data(as_text=True)
    assert 'January 2026' in html
    assert 'February 2026' in html
    assert jan_number in html
    assert feb_number in html
    assert html.index('February 2026') < html.index('January 2026')
