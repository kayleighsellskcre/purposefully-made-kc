"""The Orders list carries what the board view shows: due dates, group, send-home, counts, quick move."""
from datetime import datetime, timedelta

from models import db, Order


def _order(seed, **over):
    values = dict(
        user_id=seed['customer_id'], first_name='Casey', last_name='Customer',
        email='customer-test@example.com', subtotal=30, total=30,
        payment_status='paid', status='paid', production_stage='order_received',
        fulfillment_method='pickup',
    )
    values.update(over)
    order = Order(**values)
    db.session.add(order)
    db.session.commit()
    return order.id, order.order_number


def _three(app, seed):
    with app.app_context():
        late = _order(seed, first_name='Late', due_date=datetime.utcnow() - timedelta(days=2),
                      collection_id=seed['collection_id'], send_home_with_child=True,
                      child_name='Mia', teacher_name='Ms. Park')
        soon = _order(seed, first_name='Soon', due_date=datetime.utcnow() + timedelta(days=5),
                      production_stage='waiting_supplies')
        none = _order(seed, first_name='Nodue')
        return late, soon, none


def test_list_shows_due_date_group_send_home_and_counts(admin_client, app, seed):
    _three(app, seed)
    html = admin_client.get('/admin/orders?stage=all').get_data(as_text=True)
    assert 'ord-due--overdue' in html                       # the late one is flagged
    assert 'Send home: Mia' in html and 'Ms. Park' in html
    assert 'Test Elementary Spirit Wear' in html            # which group it belongs to
    assert '<span class="ord-chip-count">3</span>' in html  # All Open
    assert 'Move to' in html                                # quick mover on each row


def test_sort_by_due_date_puts_the_soonest_first_and_undated_last(admin_client, app, seed):
    _three(app, seed)
    html = admin_client.get('/admin/orders?stage=all&sort=due').get_data(as_text=True)
    assert html.index('Late') < html.index('Soon') < html.index('Nodue')


def test_quick_move_changes_the_stage_and_comes_back_to_the_list(admin_client, app, seed):
    (late_id, _), _, _ = _three(app, seed)
    resp = admin_client.post(
        f'/admin/orders/{late_id}/update-stage', data={'stage': 'ready_to_press'},
        headers={'Referer': 'http://localhost/admin/orders?stage=all'},
    )
    assert resp.status_code == 302 and '/admin/orders' in resp.headers['Location']
    with app.app_context():
        assert db.session.get(Order, late_id).production_stage == 'ready_to_press'
