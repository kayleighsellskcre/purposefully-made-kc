"""Review links Kayleigh can send herself: one general link, one per invoice, one per order."""
from models import ManualInvoice, Order, Review, db
from tests.test_reviews_and_emails import _in_db, _order


def _invoice(app, token='inv_' + 'y' * 24):
    def go():
        inv = ManualInvoice(number=f'INV-T{ManualInvoice.query.count() + 1}', customer_name='Jamie Rhodes',
                            email='jamie@example.com', phone='9135551234', items_json='[]', review_token=token)
        db.session.add(inv)
        db.session.commit()
        return inv.id
    return _in_db(app, go)


def test_general_link_takes_a_review_with_an_optional_email(guest, app, seed):
    html = guest.get('/review').get_data(as_text=True)
    assert 'How Did It Turn Out?' in html and 'name="email"' in html and 'Purposefully Made KC' in html
    resp = guest.post('/review', data={'name': 'Tara M.', 'body': 'So soft, love them!', 'email': ''})
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/review/thanks')
    row = _in_db(app, lambda: (lambda r: (r.source, r.order_id, r.status, r.body))(Review.query.first()))
    assert row == ('general', None, 'pending', 'So soft, love them!')
    assert 'Thank You' in guest.get('/review/thanks').get_data(as_text=True)


def test_general_link_ignores_robots_and_checks_the_email(guest, app, seed):
    guest.post('/review', data={'name': 'Bot', 'body': 'spam', 'website': 'http://spam.example'})
    assert _in_db(app, lambda: Review.query.count()) == 0
    resp = guest.post('/review', data={'name': 'Tara', 'body': 'Great', 'email': 'nope'})
    assert resp.status_code == 200 and 'does not look quite right' in resp.get_data(as_text=True)
    assert _in_db(app, lambda: Review.query.count()) == 0


def test_invoice_link_fills_the_name_and_takes_one_review(guest, app, seed):
    inv_id = _invoice(app)
    token = 'inv_' + 'y' * 24
    html = guest.get(f'/review/i/{token}').get_data(as_text=True)
    assert 'value="Jamie R."' in html and 'name="email"' not in html
    resp = guest.post(f'/review/i/{token}', data={'name': 'Jamie R.', 'body': 'Perfect for our team!'})
    assert resp.status_code == 302
    row = _in_db(app, lambda: (lambda r: (r.source, r.invoice_id))(Review.query.first()))
    assert row == ('invoice', inv_id)
    assert 'already have your review' in guest.get(f'/review/i/{token}').get_data(as_text=True)
    assert guest.get('/review/i/not-a-real-token-at-all').status_code == 404


def test_admin_pages_show_copyable_review_links(admin_client, app, seed):
    page = admin_client.get('/admin/operations/reviews').get_data(as_text=True)
    assert 'Your review link' in page and '/review"' in page and 'Copy link' in page

    inv_id = _invoice(app, token=None)
    page = admin_client.get(f'/admin/invoices/{inv_id}').get_data(as_text=True)
    token = _in_db(app, lambda: db.session.get(ManualInvoice, inv_id).review_token)
    assert token and f'/review/i/{token}' in page and 'Ask for a review' in page and 'Copy review link' in page

    def finished_order():
        oid = _order()
        db.session.get(Order, oid).status = 'picked_up'
        db.session.commit()
        return oid
    oid = _in_db(app, finished_order)
    page = admin_client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    token = _in_db(app, lambda: db.session.get(Order, oid).review_token)
    assert token and f'/review/{token}' in page and 'Ask for a review' in page
    # making the link sends nothing
    assert _in_db(app, lambda: db.session.get(Order, oid).review_email_sent_at) is None


def test_orders_in_progress_do_not_ask_and_reviewed_ones_say_so(admin_client, app, seed):
    oid = _in_db(app, _order)                                   # still in progress
    page = admin_client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert 'Ask for a review' not in page
    assert _in_db(app, lambda: db.session.get(Order, oid).review_token) is None

    def reviewed():
        db.session.add(Review(order_id=oid, name='Amy K.', body='Love it', status='pending'))
        db.session.get(Order, oid).status = 'picked_up'
        db.session.commit()
    _in_db(app, reviewed)
    page = admin_client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert 'Ask for a review' not in page and 'This customer left a review' in page

    inv_id = _invoice(app)
    _in_db(app, lambda: (db.session.add(Review(invoice_id=inv_id, source='invoice', name='Jamie R.', status='pending')),
                         db.session.commit()))
    page = admin_client.get(f'/admin/invoices/{inv_id}').get_data(as_text=True)
    assert 'Ask for a review' not in page and 'Jamie left a review' in page


def test_customers_can_find_the_review_page_on_their_own(guest, app, seed):
    assert '/review">Leave a Review' in guest.get('/').get_data(as_text=True)


def test_finished_orders_offer_a_review_in_the_customer_account(app, seed):
    from tests.test_cancel_order import _order as cust_order, _shopper
    cust_order(app, status='paid', number='PMKC-RV1')
    shopper = _shopper(app)
    assert 'Leave a review' not in shopper.get('/account/orders/PMKC-RV1').get_data(as_text=True)
    cust_order(app, status='picked_up', stage='completed', number='PMKC-RV2')
    page = shopper.get('/account/orders/PMKC-RV2').get_data(as_text=True)
    token = _in_db(app, lambda: Order.query.filter_by(order_number='PMKC-RV2').first().review_token)
    assert 'Leave a review' in page and f'/review/{token}' in page


def test_finished_admin_orders_hide_cancel_and_proof(admin_client, app, seed):
    def make(status):
        oid = _order()
        db.session.get(Order, oid).status = status
        db.session.commit()
        return oid
    live = _in_db(app, lambda: make('paid'))
    page = admin_client.get(f'/admin/orders/{live}').get_data(as_text=True)
    assert 'Cancel this order' in page and 'od-proof-card' in page
    done = _in_db(app, lambda: make('picked_up'))
    page = admin_client.get(f'/admin/orders/{done}').get_data(as_text=True)
    assert 'Cancel this order' not in page and 'od-proof-card' not in page
