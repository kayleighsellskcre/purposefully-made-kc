"""Company-sponsored group orders: requests, approval, one invoice, then production."""
import json

from models import db, Collection, CompanyInvoice, Order, SponsorSubmission
from tests.conftest import CUSTOMER_EMAIL


def _in_db(app, fn):
    """Run fn() against the database on its own thread (see test_group_order_roster)."""
    import threading
    out = {}

    def run():
        with app.app_context():
            try:
                out['value'] = fn()
            except BaseException as exc:
                out['error'] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if 'error' in out:
        raise out['error']
    return out.get('value')


def _guest(app):
    return app.test_client()


def _login_as(app, email):
    c = app.test_client()
    c.post('/auth/login', data={'email': email, 'password': 'TestPassw0rd!23'})
    return c


def _setup(app, seed, *, items=1, budget=None, organizer='customer'):
    def go():
        c = db.session.get(Collection, seed['collection_id'])
        c.payment_mode = 'company_sponsored'
        c.sponsor_items_per_person = items
        c.sponsor_budget_per_person = budget
        if organizer == 'customer':
            from models import User
            c.created_by_user_id = User.query.filter_by(email=CUSTOMER_EMAIL).first().id
        db.session.commit()
    _in_db(app, go)
    return seed['collection_slug']


def _fill_cart(client, seed, qty=1):
    with client.session_transaction() as sess:
        sess['cart'] = [{
            'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': qty,
            'unit_price': 18.00, 'collection_id': seed['collection_id'],
            'catalog_section': 'fan',
        }]


def _request(client, slug, email='ava@example.com', **extra):
    data = {'first_name': 'Ava', 'last_name': 'Lopez', 'email': email, 'fulfillment_method': 'pickup'}
    data.update(extra)
    return client.post(f'/c/{slug}/sponsored/checkout', data=data)


def _submission_count(app):
    return _in_db(app, lambda: (SponsorSubmission.query.count(), Order.query.count()))


def test_checkout_redirects_to_request_page(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    resp = guest.get('/checkout/')
    assert resp.status_code == 302 and f'/c/{slug}/sponsored/checkout' in resp.headers['Location']
    html = guest.get(f'/c/{slug}/sponsored/checkout').get_data(as_text=True)
    assert 'Send my request' in html


def test_cart_over_the_allowance_is_bounced(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed, items=1)
    _fill_cart(guest, seed, qty=2)
    resp = guest.get(f'/c/{slug}/sponsored/checkout', follow_redirects=True)
    assert 'covers 1 item per person' in resp.get_data(as_text=True)
    assert _request(guest, slug).status_code == 302  # still bounced, never saved
    assert _submission_count(app) == (0, 0)


def test_price_cap_blocks_an_item_that_costs_more(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed, budget=10.0)
    _fill_cart(guest, seed)
    resp = guest.get(f'/c/{slug}/sponsored/checkout', follow_redirects=True)
    assert 'covers up to $10.00 per item' in resp.get_data(as_text=True)


def test_request_is_saved_without_making_an_order(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    resp = _request(guest, slug)
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/sponsored/confirm')
    assert _submission_count(app) == (1, 0)          # a request, but NO order
    with guest.session_transaction() as sess:
        assert not sess.get('cart')
    assert "You're all set" in guest.get(f'/c/{slug}/sponsored/confirm').get_data(as_text=True)


def test_same_email_cannot_send_two_requests(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    _request(guest, slug)
    _fill_cart(guest, seed)
    resp = _request(guest, slug)
    assert resp.status_code == 400
    assert _submission_count(app)[0] == 1


def test_only_the_organizer_sees_the_dashboard(seed, app):
    guest = _guest(app)
    customer_client = _login_as(app, CUSTOMER_EMAIL)
    slug = _setup(app, seed, organizer='other')
    assert guest.get(f'/c/{slug}/manage-sponsored').status_code in (302, 401, 403)
    assert customer_client.get(f'/c/{slug}/manage-sponsored').status_code == 403


def _make_pending(guest, seed, app, slug, email='ava@example.com'):
    _fill_cart(guest, seed)
    _request(guest, slug, email=email)
    return _in_db(app, lambda: SponsorSubmission.query.filter_by(email=email).first().id)


def _owner_client(app):
    return _login_as(app, 'admin-test@example.com')


def _the_invoice(app):
    def go():
        inv = CompanyInvoice.query.one()
        return dict(id=inv.id, subtotal=inv.subtotal, tax=inv.tax, total=inv.total,
                    status=inv.payment_status, ids=inv.submission_ids)
    return _in_db(app, go)


def test_full_flow_nothing_is_made_until_the_invoice_is_paid(app, seed):
    guest = _guest(app)
    customer_client = _login_as(app, CUSTOMER_EMAIL)
    slug = _setup(app, seed)
    sub_id = _make_pending(guest, seed, app, slug)

    # Organizer: cannot invoice while a request is waiting, then approves.
    resp = customer_client.post(f'/c/{slug}/manage-sponsored/invoice', follow_redirects=True)
    assert 'still waiting' in resp.get_data(as_text=True)
    customer_client.post(f'/c/{slug}/manage-sponsored/review',
                         data={'submission_id': sub_id, 'action': 'approve'})
    customer_client.post(f'/c/{slug}/manage-sponsored/invoice')

    inv = _the_invoice(app)
    assert (inv['subtotal'], inv['tax'], inv['total'], inv['status']) == (18.0, 1.71, 19.71, 'unpaid')
    assert _in_db(app, lambda: db.session.get(Collection, seed['collection_id']).sponsor_submissions_locked)
    assert _submission_count(app)[1] == 0            # still no order

    # The request link is closed once invoiced.
    _fill_cart(guest, seed)
    assert guest.get(f'/c/{slug}/sponsored/checkout').status_code == 302

    # The organizer cannot mark their own invoice paid.
    assert customer_client.post(
        f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}/mark-paid', data={'method': 'cash'}
    ).status_code == 403
    assert _submission_count(app)[1] == 0

    # The shop owner can, and a repeat does nothing.
    owner = _owner_client(app)
    for _ in range(2):
        owner.post(f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}/mark-paid', data={'method': 'check'})

    def check():
        order = Order.query.one()
        assert order.payment_status == 'paid' and order.status == 'paid'
        assert order.payment_method == 'company_invoice'
        assert order.collection_id == seed['collection_id']
        assert order.total == 19.71
        item = order.items.one()
        assert (item.size, item.color, item.quantity) == ('M', 'Black', 1)
        sub = db.session.get(SponsorSubmission, sub_id)
        assert sub.status == 'converted' and sub.order_id == order.id
    _in_db(app, check)


def test_declined_request_is_not_invoiced(app, seed):
    guest = _guest(app)
    customer_client = _login_as(app, CUSTOMER_EMAIL)
    slug = _setup(app, seed)
    keep = _make_pending(guest, seed, app, slug, email='keep@example.com')
    other = app.test_client()
    skip = _make_pending(other, seed, app, slug, email='skip@example.com')
    customer_client.post(f'/c/{slug}/manage-sponsored/review', data={'submission_id': keep, 'action': 'approve'})
    customer_client.post(f'/c/{slug}/manage-sponsored/review',
                         data={'submission_id': skip, 'action': 'reject', 'reason': 'Not on staff'})
    customer_client.post(f'/c/{slug}/manage-sponsored/invoice')
    inv = _the_invoice(app)
    assert inv['ids'] == [keep] and inv['total'] == 19.71


def test_stripe_webhook_pays_the_invoice(app, seed, monkeypatch):
    guest = _guest(app)
    customer_client = _login_as(app, CUSTOMER_EMAIL)
    import stripe
    slug = _setup(app, seed)
    sub_id = _make_pending(guest, seed, app, slug)
    customer_client.post(f'/c/{slug}/manage-sponsored/review', data={'submission_id': sub_id, 'action': 'approve'})
    customer_client.post(f'/c/{slug}/manage-sponsored/invoice')

    def tag():
        CompanyInvoice.query.one().payment_intent_id = 'pi_test_invoice'
        db.session.commit()
    _in_db(app, tag)

    def fake_event(amount):
        return {'type': 'payment_intent.succeeded',
                'data': {'object': {'id': 'pi_test_invoice', 'amount': amount}}}

    hook = app.test_client()
    headers = {'Stripe-Signature': 'x'}
    # Wrong amount: nothing happens.
    monkeypatch.setattr(stripe.Webhook, 'construct_event', lambda *a, **k: fake_event(100))
    hook.post('/checkout/stripe-webhook', data=b'{}', headers=headers)
    assert _submission_count(app)[1] == 0

    monkeypatch.setattr(stripe.Webhook, 'construct_event', lambda *a, **k: fake_event(1971))
    resp = hook.post('/checkout/stripe-webhook', data=b'{}', headers=headers)
    assert resp.get_json()['invoice']
    hook.post('/checkout/stripe-webhook', data=b'{}', headers=headers)  # Stripe retries
    assert _submission_count(app)[1] == 1
    assert _the_invoice(app)['status'] == 'paid'


def test_edit_form_offers_the_company_option(seed, app):
    admin_client = _login_as(app, 'admin-test@example.com')
    html = admin_client.get(f'/admin/collections/{seed["collection_id"]}/edit').get_data(as_text=True)
    assert 'A company is covering it' in html
    assert 'name="sponsor_items_per_person"' in html
