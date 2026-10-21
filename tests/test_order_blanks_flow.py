"""Order blanks is for NEW orders only; Orders and Workflow are one step (list or board)."""
from models import Order, OrderItem, db
from utils.ops_flow import FLOW_STEPS


def _order(app, seed, number, stage, color='Black', design=True):
    with app.app_context():
        order = Order(order_number=number, email='x@example.com', first_name='Pat', last_name=number, subtotal=30, total=30,
                      status='paid', payment_status='paid', production_stage=stage)
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', style_number='3001', size='M',
                                 color=color, quantity=1, unit_price=30, subtotal=30, placement='center_chest',
                                 design_id=seed['free_design_id'] if design else None))
        db.session.commit()
        return order.id


def _stage(app, oid):
    with app.app_context():
        return db.session.get(Order, oid).production_stage


def test_order_blanks_only_lists_new_orders_even_if_the_link_asks_for_more(app, seed, admin_client):
    _order(app, seed, 'NEW-1', 'order_received', color='Black')
    _order(app, seed, 'WAIT-1', 'waiting_supplies', color='Crimson')
    for url in ('/admin/production/master', '/admin/production/master?stage=order_received&stage=waiting_supplies',
                '/admin/production/master?stage=waiting_supplies'):
        page = admin_client.get(url).get_data(as_text=True)
        assert 'Black' in page and 'Crimson' not in page, url
    page = admin_client.get('/admin/production/master').get_data(as_text=True)
    assert '1</strong> order(s) are waiting on supplies' in page
    assert 'Supplies are in: Ready to Press' in page and "I've ordered these: Waiting on Supplies" in page


def test_ordered_moves_new_orders_to_waiting_and_leaves_the_rest_alone(app, seed, admin_client):
    new = _order(app, seed, 'NEW-2', 'order_received')
    waiting = _order(app, seed, 'WAIT-2', 'waiting_supplies')
    ready = _order(app, seed, 'READY-2', 'ready_to_press')
    r = admin_client.post('/admin/production/master/move-to-production', data={'which': 'ordered'}, follow_redirects=True)
    assert 'Moved 1 order(s) to Waiting on Supplies' in r.get_data(as_text=True)
    assert (_stage(app, new), _stage(app, waiting), _stage(app, ready)) == ('waiting_supplies', 'waiting_supplies', 'ready_to_press')
    page = admin_client.get('/admin/production/master').get_data(as_text=True)
    assert 'all caught up' in page.lower()


def test_arrived_moves_only_the_waiting_orders_to_ready_to_press(app, seed, admin_client):
    new = _order(app, seed, 'NEW-3', 'order_received')
    waiting = _order(app, seed, 'WAIT-3', 'waiting_supplies')
    r = admin_client.post('/admin/production/master/move-to-production', data={'which': 'arrived'}, follow_redirects=True)
    assert 'Moved 1 order(s) to Ready to Press' in r.get_data(as_text=True)
    assert (_stage(app, new), _stage(app, waiting)) == ('order_received', 'ready_to_press')       # new orders are untouched


def test_the_download_all_zip_also_skips_orders_already_waiting(app, seed, admin_client):
    _order(app, seed, 'WAIT-4', 'waiting_supplies')
    r = admin_client.get('/admin/production/master/images.zip', follow_redirects=True)
    assert 'no print pictures' in r.get_data(as_text=True).lower()


def test_orders_and_workflow_are_one_step(app, seed, admin_client):
    assert [s['id'] for s in FLOW_STEPS] == ['orders', 'blanks', 'press', 'pack']
    assert [s['num'] for s in FLOW_STEPS] == ['1', '2', '3', '4']
    orders = admin_client.get('/admin/orders?stage=order_received').get_data(as_text=True)
    assert 'Board view' in orders and 'Next: Order blanks' in orders and 'Next: Workflow' not in orders
    board = admin_client.get('/admin/operations/workflow').get_data(as_text=True)
    assert 'board view' in board.lower() and 'List view' in board
    dash = admin_client.get('/admin/').get_data(as_text=True)
    assert '2. Workflow' not in dash and '2. Order blanks' in dash and '4. Pack' in dash


def test_the_board_still_works_for_moving_orders(app, seed, admin_client):
    oid = _order(app, seed, 'BOARD-1', 'order_received')
    r = admin_client.post('/admin/orders/bulk-update-stage', data={'stage': 'waiting_supplies', 'order_ids': [oid]})
    assert r.status_code in (200, 302)
    assert _stage(app, oid) == 'waiting_supplies'
