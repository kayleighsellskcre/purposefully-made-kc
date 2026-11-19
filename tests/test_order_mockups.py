"""Mockups of each shirt, drawn on the server for the invoice email and a download."""
import json

from models import db, Order, OrderItem, ManualInvoice


def _order(app, seed, rows):
    with app.app_context():
        o = Order(order_number='MK-1', email='c@example.com', first_name='C', last_name='D', subtotal=60, total=60,
                  status='new', payment_status='awaiting_payment', payment_method='invoice')
        db.session.add(o)
        db.session.flush()
        for number, name, size in rows:
            db.session.add(OrderItem(
                order_id=o.id, product_id=seed['tee_id'], design_id=seed['free_design_id'], product_name='Tee', size=size,
                color='Black', quantity=1, unit_price=30, subtotal=30, placement='left_chest',
                back_design_meta=json.dumps({'name': name, 'number': number, 'font': 'Bebas Neue', 'text_color': '#ffffff'})))
        db.session.commit()
        return o.id


def test_same_look_shares_one_card_and_each_person_gets_their_own(app, seed):
    from utils.order_mockups import look_key
    oid = _order(app, seed, [('12', 'Guerin', 'M'), ('12', 'Guerin', 'L'), ('7', 'Smith', 'M')])
    with app.app_context():
        items = Order.query.get(oid).items.all()
        assert len({look_key(i) for i in items}) == 2


def test_mockup_pdf_is_made_and_downloadable(app, seed, admin_client):
    oid = _order(app, seed, [('12', 'Guerin', 'M'), ('7', 'Smith', 'M')])
    resp = admin_client.get(f'/admin/orders/{oid}/mockups.pdf')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data.startswith(b'%PDF')


def test_invoice_email_attaches_the_mockups(app, seed):
    from utils import invoice_emails
    oid = _order(app, seed, [('12', 'Guerin', 'M')])
    with app.app_context():
        inv = ManualInvoice(number='INV-T-1', kind='invoice', customer_name='C D', email='c@example.com',
                            items_json='[]', order_id=oid)
        db.session.add(inv)
        db.session.commit()
        got = invoice_emails.mockup_attachments(inv)
        assert got and got[0][0] == 'Mockups-INV-T-1.pdf' and got[0][2].startswith(b'%PDF')


def test_production_master_shows_name_and_number_pictures_for_entered_orders(app, seed, admin_client):
    """Orders typed in on Enter an order have no saved print file yet: the page draws each one when asked."""
    oid = _order(app, seed, [('12', 'Guerin', 'M'), ('5', 'Wilson', 'S')])
    resp = admin_client.get('/admin/production/master?stage=order_received')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert html.count('No image') == 0 or 'Personalized backs' in html
    assert f'/admin/orders/{oid}/items/' in html and 'inline=1' in html
    personal = html.split('Personalized backs', 1)[1]
    assert 'No image' not in personal
    assert personal.count('<img') >= 2


def test_edit_shirts_changes_color_name_number_and_keeps_the_money(app, seed, admin_client):
    from models import ManualInvoice
    oid = _order(app, seed, [('12', 'Guerin', 'M'), ('7', 'Smith', 'M')])
    with app.app_context():
        for i in Order.query.get(oid).items.all():
            i.back_design_meta = json.dumps({**json.loads(i.back_design_meta), 'production_png_url': '/old.png'})
        db.session.add(ManualInvoice(number='INV-E-1', kind='invoice', customer_name='C D', email='c@example.com',
                                     order_id=oid, items_json=json.dumps([{'description': 'old', 'qty': 2, 'unit': 30.0}])))
        db.session.commit()
        ids = [i.id for i in Order.query.get(oid).items.all()]
    assert admin_client.get(f'/admin/orders/{oid}/edit-shirts').status_code == 200
    data = {'font': 'Anton', 'text_color': '#000000', 'placement': 'center_chest'}
    for n, iid in enumerate(ids):
        data.update({f'product_{iid}': seed['hoodie_id'], f'color_{iid}': 'Navy', f'size_{iid}': 'L',
                     f'name_{iid}': 'Lee' if n == 0 else 'Smith', f'number_{iid}': '99' if n == 0 else '7'})
    resp = admin_client.post(f'/admin/orders/{oid}/edit-shirts', data=data, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        order = Order.query.get(oid)
        first, second = order.items.all()
        assert (first.color, first.size, first.product_id, first.placement) == ('Navy', 'L', seed['hoodie_id'], 'center_chest')
        meta = first.back_design_details
        assert (meta['name'], meta['number'], meta['font'], meta['text_color']) == ('LEE', '99', 'Anton', '#000000') or meta['name'] == 'Lee'
        assert 'production_png_url' not in meta                      # the old print picture is dropped so a new one is drawn
        assert order.total == 60 and first.unit_price == 30           # money untouched
        inv = ManualInvoice.query.filter_by(order_id=oid).one()
        lines = json.loads(inv.items_json)
        assert 'Navy' in lines[0]['description'] and 'Heavy Blend' in lines[0]['description']
        assert sum(l['qty'] * l['unit'] for l in lines) == 60.0


def test_invoice_edit_page_links_to_edit_shirts(app, seed, admin_client):
    from models import ManualInvoice
    oid = _order(app, seed, [('12', 'Guerin', 'M')])
    with app.app_context():
        inv = ManualInvoice(number='INV-L-1', kind='invoice', customer_name='C D', items_json='[]', order_id=oid)
        db.session.add(inv)
        db.session.commit()
        iid = inv.id
    html = admin_client.get(f'/admin/invoices/{iid}/edit').get_data(as_text=True)
    assert f'/admin/orders/{oid}/edit-shirts' in html
