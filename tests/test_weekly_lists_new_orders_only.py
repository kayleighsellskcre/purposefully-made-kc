"""The weekly blanks list and DTF list are only for orders still to be bought."""
from models import Order, OrderItem, Product, db

BOTH_STAGES = '?stage=order_received&stage=waiting_supplies'     # what the Order blanks page forwards


def _order(app, number, stage, product_id, design_id=None):
    with app.app_context():
        order = Order(order_number=number, email='x@example.com', first_name='X', last_name='Y',
                      subtotal=30, total=30, status='paid', payment_status='paid', production_stage=stage)
        db.session.add(order)
        db.session.flush()
        product = db.session.get(Product, product_id)
        db.session.add(OrderItem(order_id=order.id, product_id=product_id, design_id=design_id,
                                 product_name=product.name, style_number=product.style_number,
                                 size='M', color='Black', quantity=1, unit_price=30, subtotal=30,
                                 placement='center_chest'))
        db.session.commit()
        return product.name


def test_the_blanks_list_skips_orders_already_waiting_on_supplies(admin_client, app, seed):
    new_name = _order(app, 'NEW-1', 'order_received', seed['tee_id'])
    ordered_name = _order(app, 'WAIT-1', 'waiting_supplies', seed['hoodie_id'])
    assert new_name != ordered_name
    for url in ('/admin/production/blank-apparel-list', '/admin/production/blank-apparel-list' + BOTH_STAGES):
        html = admin_client.get(url).get_data(as_text=True)
        assert new_name in html and ordered_name not in html, url
    csv = admin_client.get('/admin/production/blank-apparel-list' + BOTH_STAGES + '&format=csv').get_data(as_text=True)
    assert new_name in csv and ordered_name not in csv


def test_the_dtf_list_skips_orders_already_waiting_on_supplies(admin_client, app, seed):
    _order(app, 'NEW-2', 'order_received', seed['tee_id'], seed['free_design_id'])
    _order(app, 'WAIT-2', 'waiting_supplies', seed['hoodie_id'], seed['paid_design_id'] if 'paid_design_id' in seed else seed['free_design_id'])
    from utils.dtf_orders import build_dtf_shopping_list
    from utils.ops_flow import ops_order_query_for
    with app.test_request_context('/admin/production/dtf-batch-sheets' + BOTH_STAGES):
        query, stages, _ = ops_order_query_for(['order_received'])
        assert stages == ['order_received']
        assert [o.order_number for o in query.all()] == ['NEW-2']
    html = admin_client.get('/admin/production/dtf-batch-sheets' + BOTH_STAGES).get_data(as_text=True)
    assert 'New orders only' in html


def test_the_lists_say_they_are_for_new_orders_only(admin_client):
    for url in ('/admin/production/blank-apparel-list', '/admin/production/dtf-batch-sheets'):
        assert 'New orders only (Order received)' in admin_client.get(url).get_data(as_text=True)
