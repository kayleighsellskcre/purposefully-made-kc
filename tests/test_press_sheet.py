"""Press sheets stay readable and match packing-label order."""
import json
from datetime import datetime, timedelta

from models import db, Order, OrderItem
from routes.admin import _collect_press_shirts, _sort_press_shirts
from utils.ops_flow import packing_sort_key
from utils.production_stages import apply_stage

FRONT = json.dumps({
    'front': {
        'design_name': 'Falcons',
        'placement': 'center_chest',
        'placement_label': 'Center Chest',
        'width_display': '10.75',
        'height_display': '3.00',
        'age_group': 'adult',
    }
})


def _add_item(order_id, product_id, **over):
    values = dict(
        order_id=order_id,
        product_id=product_id,
        product_name='Unisex Jersey Short Sleeve Tee',
        style_number='3001',
        size='M',
        color='Navy',
        quantity=1,
        unit_price=30.0,
        subtotal=30.0,
        transfer_production=FRONT,
    )
    values.update(over)
    item = OrderItem(**values)
    db.session.add(item)
    return item


def _add_order(app, seed, *, first_name, last_name, created_at, send_home=False,
               child_name=None, teacher_name=None):
    with app.app_context():
        order = Order(
            order_number=f'PM-PRESS-{first_name.upper()}',
            email=f'{first_name.lower()}@example.com',
            first_name=first_name,
            last_name=last_name,
            subtotal=30.0,
            total=30.0,
            payment_status='paid',
            send_home_with_child=send_home,
            child_name=child_name,
            teacher_name=teacher_name,
            created_at=created_at,
        )
        apply_stage(order, 'ready_to_press')
        db.session.add(order)
        db.session.commit()
        return order.id


def test_packing_sort_puts_send_home_ahead_of_later_pickup(app, seed):
    earlier = datetime(2026, 9, 1, 8, 0, 0)
    pickup_id = _add_order(app, seed, first_name='Alice', last_name='Pickup', created_at=earlier)
    send_home_id = _add_order(
        app, seed, first_name='Maya', last_name='Parent',
        created_at=earlier + timedelta(days=2),
        send_home=True, child_name='Emma', teacher_name='Mrs. Hale',
    )
    with app.app_context():
        pickup = Order.query.get(pickup_id)
        send_home = Order.query.get(send_home_id)
        ordered = sorted([pickup, send_home], key=packing_sort_key)
        assert [o.first_name for o in ordered] == ['Maya', 'Alice']


def test_press_cards_expand_qty_and_count_within_the_order(app, seed):
    order_id = _add_order(
        app, seed, first_name='Casey', last_name='Customer',
        created_at=datetime(2026, 9, 10),
    )
    with app.app_context():
        _add_item(order_id, seed['tee_id'], color='Navy', size='M', quantity=2)
        _add_item(order_id, seed['tee_id'], color='Grey', size='L', quantity=1, style_number='18500')
        db.session.commit()
        shirts = _collect_press_shirts([Order.query.get(order_id)])

    assert len(shirts) == 3
    assert [s['piece_index'] for s in shirts] == [1, 2, 3]
    assert {s['piece_total'] for s in shirts} == {3}
    assert shirts[0]['customer_name'] == 'Casey Customer'
    assert shirts[0]['color'] == 'Navy'
    assert shirts[1]['color'] == 'Navy'
    assert shirts[2]['color'] == 'Grey'


def test_press_sheet_default_sort_matches_label_order(app, seed):
    earlier = datetime(2026, 9, 1, 8, 0, 0)
    pickup_id = _add_order(app, seed, first_name='Alice', last_name='Pickup', created_at=earlier)
    send_home_id = _add_order(
        app, seed, first_name='Maya', last_name='Parent',
        created_at=earlier + timedelta(days=1),
        send_home=True, child_name='Emma', teacher_name='Mrs. Hale',
    )
    with app.app_context():
        _add_item(pickup_id, seed['tee_id'], color='Black', size='XL')
        _add_item(send_home_id, seed['tee_id'], color='Navy', size='YS')
        _add_item(send_home_id, seed['tee_id'], color='White', size='YM')
        db.session.commit()
        shirts = _sort_press_shirts(_collect_press_shirts([
            Order.query.get(pickup_id),
            Order.query.get(send_home_id),
        ]))

    names = [s['customer_name'] for s in shirts]
    assert names == ['Maya Parent', 'Maya Parent', 'Alice Pickup']
    assert [s['piece_index'] for s in shirts if s['customer_name'] == 'Maya Parent'] == [1, 2]
    assert shirts[0]['child_name'] == 'Emma'


def test_press_sheet_page_shows_orderer_name_and_counts(admin_client, app, seed):
    order_id = _add_order(
        app, seed, first_name='Maya', last_name='Parent',
        created_at=datetime(2026, 9, 12),
    )
    with app.app_context():
        _add_item(order_id, seed['tee_id'], color='Navy', quantity=2)
        _add_item(order_id, seed['tee_id'], color='Pink', size='S', quantity=1)
        db.session.commit()

    resp = admin_client.get('/admin/production/transfers?stage=ready_to_press')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Maya Parent' in body
    assert '1/3' in body
    assert '2/3' in body
    assert '3/3' in body
    assert 'Same as labels' in body
    assert 'font-size: 16pt' in body
    assert 'xfer-count' in body
    print_css = body.split('@media print')[-1]
    assert 'display: flex !important' in print_css
    assert 'flex-direction: column' in print_css
