"""Admin can print a receipt (or invoice) with the business details and logo."""
from models import Order, OrderItem, db


def _order(app, seed, *, paid=True, **over):
    with app.app_context():
        order = Order(order_number='PMKC-1001', email='buyer@example.com', first_name='Casey', last_name='Customer',
                      phone='816-555-0100', subtotal=60, shipping_cost=0, tax=5.7, total=65.7,
                      payment_status='paid' if paid else 'pending', payment_method='stripe' if paid else 'cash',
                      amount_paid=65.7 if paid else 0, status='paid' if paid else 'new', **over)
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, product_id=seed['tee_id'], product_name='Unisex Jersey Tee',
                                 style_number='3001', size='M', color='Black', quantity=2, unit_price=30, subtotal=60))
        db.session.commit()
        return order.id


def test_the_receipt_has_the_business_details_logo_and_payment_options(admin_client, app, seed):
    oid = _order(app, seed)
    html = admin_client.get(f'/admin/orders/{oid}/receipt').get_data(as_text=True)
    for text in ('Kayleigh Biggs', 'Purposefully Made KC LLC', 'purposefullymadekc@gmail.com', '785.249.1464',
                 'PMKC-1001', 'Unisex Jersey Tee', 'Paid in full'):
        assert text in html, text
    assert 'img/logo-wordmark.png' in html
    assert '$65.70' in html and '$60.00' in html and '$5.70' in html
    # already paid: no "how to pay" box
    for text in ('Accepted forms of payment', '@Kayleigh-Biggs-1', 'Made out to Kayleigh Biggs'):
        assert text not in html, text


def test_a_paid_order_is_a_receipt_and_an_unpaid_one_is_an_invoice_with_the_balance(admin_client, app, seed):
    paid = admin_client.get(f"/admin/orders/{_order(app, seed)}/receipt").get_data(as_text=True)
    assert '<p class="rc-kind">receipt</p>' in paid and 'Balance due' not in paid
    with app.app_context():
        Order.query.delete()
        OrderItem.query.delete()
        db.session.commit()
    unpaid = admin_client.get(f"/admin/orders/{_order(app, seed, paid=False)}/receipt").get_data(as_text=True)
    assert '<p class="rc-kind">invoice</p>' in unpaid and 'Balance due' in unpaid and '$65.70' in unpaid
    for text in ('Accepted forms of payment', '@Kayleigh-Biggs-1', 'Cash', 'Check', 'Made out to Kayleigh Biggs'):
        assert text in unpaid, text                       # an invoice tells them how to pay


def test_company_details_and_a_note_can_be_added_before_printing(admin_client, app, seed):
    oid = _order(app, seed)
    html = admin_client.get(f'/admin/orders/{oid}/receipt?company=Riverview+PTO&attn=Amy+Smith&po=PO-77'
                            '&note=Thank+you+for+supporting+our+school&kind=invoice').get_data(as_text=True)
    assert 'Riverview PTO' in html and 'Attn: Amy Smith' in html and 'PO / Ref: PO-77' in html
    assert 'Thank you for supporting our school' in html
    assert '<p class="rc-kind">invoice</p>' in html


def test_only_the_admin_can_open_a_receipt(client, app, seed):
    oid = _order(app, seed)
    resp = client.get(f'/admin/orders/{oid}/receipt')
    assert resp.status_code in (302, 401, 403)


def test_the_order_page_has_a_receipt_button(admin_client, app, seed):
    oid = _order(app, seed)
    html = admin_client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert f'/admin/orders/{oid}/receipt' in html


def test_the_orders_page_has_a_create_invoice_button(admin_client, app, seed):
    html = admin_client.get('/admin/orders?stage=order_received', follow_redirects=True).get_data(as_text=True)
    assert 'href="/admin/invoices/new"' in html and 'Create invoice' in html
