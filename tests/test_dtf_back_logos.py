"""The weekly DTF list must include pictures printed on the back, not only front logos and names."""
from models import Order, OrderItem, db
from utils.dtf_orders import build_dtf_shopping_list


def _order(app, seed, number, *, items):
    with app.app_context():
        order = Order(order_number=number, email='x@example.com', first_name='X', last_name='Y', subtotal=30, total=30,
                      status='paid', payment_status='paid', production_stage='order_received')
        db.session.add(order)
        db.session.flush()
        for extra in items:
            fields = dict(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', style_number='3001',
                          size='M', color='Black', quantity=1, unit_price=30, subtotal=30, placement='center_chest')
            fields.update(extra)
            db.session.add(OrderItem(**fields))
        db.session.commit()
        return order.id


def _list(app, ids):
    with app.app_context():
        orders = Order.query.filter(Order.id.in_(ids)).all()
        return build_dtf_shopping_list(orders)


def test_a_back_picture_is_on_the_dtf_list_next_to_the_front_logo(app, seed):
    oid = _order(app, seed, 'DTF-1', items=[dict(
        design_id=seed['free_design_id'], quantity=2,
        back_design_file_name='uploads/designs/cart_back_amys-honkers-3fa9c2e1.png')])
    data = _list(app, [oid])
    placements = sorted(r['placement'] for r in data['logos'])
    assert 'Center Back' in placements and len(data['logos']) == 2            # front logo + back picture
    back = next(r for r in data['logos'] if r['placement'] == 'Center Back')
    assert back['quantity'] == 2 and back['width'] and back['preview_url']
    assert 'amys honkers' in back['design_name'].lower()
    assert any(row['kind'] == 'logo' and row['placement'] == 'Center Back' for row in data['csv_rows'])
    assert 'Center Back' in data['logo_copy']


def test_a_back_only_picture_order_is_listed(app, seed):
    oid = _order(app, seed, 'DTF-2', items=[dict(
        back_design_file_name='uploads/designs/cart_back_team-crest.png')])
    data = _list(app, [oid])
    assert [r['placement'] for r in data['logos']] == ['Center Back'] and data['has_items']


def test_the_same_back_picture_ordered_twice_is_one_row_with_both_counts(app, seed):
    ids = [_order(app, seed, f'DTF-3{n}', items=[dict(
        back_design_file_name='uploads/designs/cart_back_team-crest.png', quantity=q)]) for n, q in ((1, 2), (2, 3))]
    data = _list(app, ids)
    assert len(data['logos']) == 1 and data['logos'][0]['quantity'] == 5


def test_names_and_numbers_still_come_out_as_their_own_uploads(app, seed):
    oid = _order(app, seed, 'DTF-4', items=[dict(
        placement='center_back', back_design_meta='{"name": "SMITH", "number": "12"}')])
    data = _list(app, [oid])
    assert len(data['personal']) == 1 and data['personal'][0]['name'] == 'SMITH'
    assert not data['logos']


def test_the_page_shows_the_back_picture(admin_client, app, seed):
    _order(app, seed, 'DTF-5', items=[dict(back_design_file_name='uploads/designs/cart_back_team-crest.png')])
    html = admin_client.get('/admin/production/dtf-batch-sheets').get_data(as_text=True)
    assert 'Center Back' in html and 'team crest' in html.lower()
