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
    assert token and f'/review/i/{token}' in page and 'Ask for a review' in page

    oid = _in_db(app, _order)
    page = admin_client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    token = _in_db(app, lambda: db.session.get(Order, oid).review_token)
    assert token and f'/review/{token}' in page and 'Ask for a review' in page
    # making the link sends nothing
    assert _in_db(app, lambda: db.session.get(Order, oid).review_email_sent_at) is None
