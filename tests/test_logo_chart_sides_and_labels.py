"""Logo chart shows front and back; Print labels defaults to Ready to Press."""
import json

from models import Collection, Order, OrderItem, db


def _order(seed, stage, first, **item_over):
    order = Order(
        user_id=seed['customer_id'], first_name=first, last_name='Tester', email=f'{first}@example.com',
        subtotal=30, total=30, payment_status='paid', status='paid', production_stage=stage,
        fulfillment_method='pickup', collection_id=seed['collection_id'],
    )
    db.session.add(order)
    db.session.flush()
    values = dict(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', style_number='3001',
                  size='M', color='Black', quantity=1, unit_price=30, subtotal=30, placement='left_chest',
                  print_type='DTF')
    values.update(item_over)
    db.session.add(OrderItem(**values))
    db.session.commit()
    return order.number if hasattr(order, 'number') else order.order_number


def _group(app, seed):
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allowed_design_ids = json.dumps([seed['free_design_id']])
        coll.back_design_id = seed['fee_4_design_id']          # the group's shared back art
        db.session.commit()
        _order(seed, 'ready_to_press', 'Front', design_id=seed['free_design_id'])
        _order(seed, 'ready_to_press', 'Named', back_design_meta=json.dumps({'name': 'LOPEZ', 'number': '7'}))
        _order(seed, 'ready_to_press', 'Backart', back_design_file_name='riverview-back.png')


def test_logo_chart_shows_front_and_back(admin_client, app, seed):
    _group(app, seed)
    html = admin_client.get('/admin/production/logo-chart').get_data(as_text=True)
    assert 'logo-side--front' in html and '>Front<' in html
    assert 'Back of the shirt' in html
    assert '>B1<' in html and '>B2<' in html                      # shared back art + the customer's back file
    assert 'Names &amp; numbers' in html and '>N<' in html            # personalised backs, counted
    assert 'Riverview Back' in html or 'riverview-back' in html


def test_a_logo_used_only_on_the_back_is_marked_back(admin_client, app, seed):
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allowed_design_ids = json.dumps([seed['free_design_id']])
        db.session.commit()
        _order(seed, 'ready_to_press', 'Backonly', design_id=seed['free_design_id'], placement='center_back')
    html = admin_client.get('/admin/production/logo-chart').get_data(as_text=True)
    assert 'logo-side--back' in html


def test_print_labels_defaults_to_ready_to_press(admin_client, app, seed):
    with app.app_context():
        _order(seed, 'ready_to_press', 'Readyone')
        _order(seed, 'pressed', 'Pressedone')
    default = admin_client.get('/admin/orders/print-labels').get_data(as_text=True)
    assert 'Readyone' in default and 'Pressedone' not in default
    picked = admin_client.get('/admin/orders/print-labels?stage=pressed').get_data(as_text=True)
    assert 'Pressedone' in picked and 'Readyone' not in picked


def test_print_labels_page_lets_you_mark_used_boxes_and_remembers_them(admin_client, app, seed):
    with app.app_context():
        _order(seed, 'ready_to_press', 'Mapone')
    html = admin_client.get('/admin/orders/print-labels').get_data(as_text=True)
    assert 'id="plMap"' in html and 'id="plNewSheet"' in html and 'pm_label_used_boxes' in html
