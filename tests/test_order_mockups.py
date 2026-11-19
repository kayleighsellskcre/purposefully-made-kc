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
