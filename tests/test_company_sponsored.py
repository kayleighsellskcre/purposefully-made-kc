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


def test_extra_items_are_shown_as_the_employees_to_pay(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed, items=1)
    _fill_cart(guest, seed, qty=2)
    html = guest.get(f'/c/{slug}/sponsored/checkout').get_data(as_text=True)
    assert 'Covered by your company' in html
    assert 'You pay $18.00' in html
    assert 'Continue to payment' in html


def test_price_cap_makes_the_employee_pay_the_difference(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed, budget=10.0)
    _fill_cart(guest, seed)
    html = guest.get(f'/c/{slug}/sponsored/checkout').get_data(as_text=True)
    assert 'Company covers $10.00' in html and 'you pay $8.00' in html


def test_split_cart_rules(seed, app):
    from utils.group_sponsor import split_cart

    def go():
        c = db.session.get(Collection, seed['collection_id'])
        c.sponsor_items_per_person = 2
        c.sponsor_budget_per_person = 15.0
        cart = [{'unit_price': 18.0, 'quantity': 3}, {'unit_price': 12.0, 'quantity': 1}]
        lines, company, employee = split_cart(c, cart)
        assert len(lines) == 4
        assert (company, employee) == (30.0, 36.0)
        assert [l['company_part'] for l in lines] == [15.0, 15.0, 0.0, 0.0]
        assert [l['employee_part'] for l in lines] == [3.0, 3.0, 18.0, 12.0]
    _in_db(app, go)


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_stripe(monkeypatch, *, charge_cents, refunds=None):
    import stripe
    monkeypatch.setattr(stripe, 'api_key', 'sk_test_fake')
    monkeypatch.setattr(stripe.PaymentIntent, 'create',
                        lambda **kw: _Obj(id='pi_emp_1', client_secret='cs_1', amount=kw['amount']))
    monkeypatch.setattr(stripe.PaymentIntent, 'retrieve',
                        lambda pid: _Obj(id=pid, status='succeeded', amount=charge_cents))
    if refunds is not None:
        monkeypatch.setattr(stripe.Refund, 'create', lambda **kw: refunds.append(kw) or _Obj(id='re_1'))


def _status_of(app, email):
    return _in_db(app, lambda: SponsorSubmission.query.filter_by(email=email).first().status)


def test_employee_pays_for_extras_before_the_request_is_sent(seed, app, monkeypatch):
    guest = _guest(app)
    slug = _setup(app, seed, items=1)
    _fake_stripe(monkeypatch, charge_cents=1971)          # $18 extra + $1.71 tax
    _fill_cart(guest, seed, qty=2)
    resp = _request(guest, slug)
    assert resp.status_code == 200 and 'Pay for your extra items' in resp.get_data(as_text=True)
    assert _status_of(app, 'ava@example.com') == 'awaiting_payment'

    # Not on the organizer's list and not invoiceable until paid.
    organizer = _login_as(app, CUSTOMER_EMAIL)
    assert 'Ava Lopez' not in organizer.get(f'/c/{slug}/manage-sponsored').get_data(as_text=True)
    with guest.session_transaction() as sess:
        assert sess.get('cart')                             # cart kept until paid

    back = guest.get(f'/c/{slug}/sponsored/paid')
    assert back.status_code == 302 and back.headers['Location'].endswith('/sponsored/confirm')
    assert _status_of(app, 'ava@example.com') == 'approved'          # counted automatically
    assert 'Ava Lopez' in organizer.get(f'/c/{slug}/manage-sponsored').get_data(as_text=True)

    def check():                                           # only the employee's own paid item is made
        order = Order.query.one()
        assert order.payment_method == 'stripe' and order.payment_status == 'paid'
        assert order.items.count() == 1 and order.total == 19.71
        assert order.production_stage == 'order_received'
    _in_db(app, check)
    html = guest.get(f'/c/{slug}/sponsored/confirm').get_data(as_text=True)
    assert 'payment of $19.71' in html


def test_unpaid_extras_never_reach_the_organizer(seed, app, monkeypatch):
    import stripe
    guest = _guest(app)
    slug = _setup(app, seed, items=1)
    _fake_stripe(monkeypatch, charge_cents=1971)
    monkeypatch.setattr(stripe.PaymentIntent, 'retrieve',
                        lambda pid: _Obj(id=pid, status='requires_payment_method', amount=1971))
    _fill_cart(guest, seed, qty=2)
    _request(guest, slug)
    resp = guest.get(f'/c/{slug}/sponsored/paid', follow_redirects=True)
    assert 'did not go through' in resp.get_data(as_text=True)
    assert _status_of(app, 'ava@example.com') == 'awaiting_payment'


def test_webhook_finishes_an_employee_payment_if_they_closed_the_tab(seed, app, monkeypatch):
    import stripe
    guest = _guest(app)
    slug = _setup(app, seed, items=1)
    _fake_stripe(monkeypatch, charge_cents=1971)
    _fill_cart(guest, seed, qty=2)
    _request(guest, slug)
    monkeypatch.setattr(stripe.Webhook, 'construct_event', lambda *a, **k: {
        'type': 'payment_intent.succeeded', 'data': {'object': {'id': 'pi_emp_1', 'amount': 1971}}})
    hook = app.test_client()
    for _ in range(2):                                      # Stripe retries
        resp = hook.post('/checkout/stripe-webhook', data=b'{}', headers={'Stripe-Signature': 'x'})
        assert resp.get_json()['sponsor_request']
    assert _status_of(app, 'ava@example.com') == 'approved'


def test_removing_a_paid_request_refunds_the_employee(seed, app, monkeypatch):
    guest = _guest(app)
    slug = _setup(app, seed, items=1, budget=10.0)
    refunds = []
    _fake_stripe(monkeypatch, charge_cents=876, refunds=refunds)
    _fill_cart(guest, seed, qty=1)
    _request(guest, slug)
    guest.get(f'/c/{slug}/sponsored/paid')
    sub_id = _in_db(app, lambda: SponsorSubmission.query.first().id)
    organizer = _login_as(app, CUSTOMER_EMAIL)
    organizer.post(f'/c/{slug}/manage-sponsored/review',
                   data={'submission_id': sub_id, 'action': 'reject', 'reason': 'Not on staff'})
    assert len(refunds) == 1 and refunds[0]['payment_intent'] == 'pi_emp_1'
    assert _status_of(app, 'ava@example.com') == 'rejected'
    # A refunded request cannot be quietly put back.
    organizer.post(f'/c/{slug}/manage-sponsored/review', data={'submission_id': sub_id, 'action': 'approve'})
    assert _status_of(app, 'ava@example.com') == 'rejected'
    # Declining twice does not refund twice.
    organizer.post(f'/c/{slug}/manage-sponsored/review', data={'submission_id': sub_id, 'action': 'reject'})
    assert len(refunds) == 1


def test_paid_items_start_now_and_covered_items_wait_for_the_invoice(seed, app, monkeypatch):
    guest = _guest(app)
    slug = _setup(app, seed, items=1)
    _fake_stripe(monkeypatch, charge_cents=3071)            # $18 + $1.71 tax + $11 shipping
    _fill_cart(guest, seed, qty=2)
    _request(guest, slug, fulfillment_method='shipping', street='1 Main St', city='Olathe',
             state='KS', zip='66061')
    guest.get(f'/c/{slug}/sponsored/paid')

    def now_order():
        order = Order.query.one()                           # made at payment: just the paid item
        assert order.items.count() == 1 and order.subtotal == 18.0
        assert order.shipping_cost == 11.0 and order.tax == 1.71 and order.total == 30.71
        assert order.fulfillment_method == 'shipping' and order.first_name == 'Ava'
        assert SponsorSubmission.query.first().immediate_order_id == order.id
    _in_db(app, now_order)

    organizer = _login_as(app, CUSTOMER_EMAIL)
    organizer.post(f'/c/{slug}/manage-sponsored/invoice')
    inv = _the_invoice(app)
    assert inv['subtotal'] == 18.0 and inv['total'] == 19.71        # company pays only its one item
    page = organizer.get(f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}').get_data(as_text=True)
    assert 'Ava Lopez' in page and page.count('$18.00') >= 2        # name on the invoice, one line
    assert _submission_count(app)[1] == 1                           # still only the paid item

    _owner_client(app).post(f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}/mark-paid',
                            data={'method': 'check'})

    def both_orders():
        orders = Order.query.order_by(Order.id).all()
        assert len(orders) == 2
        later = orders[1]                                   # the covered item, now released
        assert later.items.count() == 1 and later.first_name == 'Ava'
        assert later.shipping_cost == 0 and later.total == 19.71
        assert later.payment_method == 'company_invoice'
    _in_db(app, both_orders)


def test_paid_items_already_in_production_cannot_be_cancelled_or_removed(seed, app, monkeypatch):
    guest = _guest(app)
    slug = _setup(app, seed, items=1)
    refunds = []
    _fake_stripe(monkeypatch, charge_cents=1971, refunds=refunds)
    _fill_cart(guest, seed, qty=2)
    _request(guest, slug)
    guest.get(f'/c/{slug}/sponsored/paid')
    path = _my_request_path(app)
    page = guest.post(path + '/cancel', follow_redirects=True).get_data(as_text=True)
    assert 'being made' in page or 'can no longer' in page
    sub_id = _in_db(app, lambda: SponsorSubmission.query.first().id)
    resp = _login_as(app, CUSTOMER_EMAIL).post(
        f'/c/{slug}/manage-sponsored/review', data={'submission_id': sub_id, 'action': 'reject'},
        follow_redirects=True)
    assert 'already being made' in resp.get_data(as_text=True)
    assert _status_of(app, 'ava@example.com') == 'approved' and refunds == []

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

    # No approval step: the request is already counted, so the organizer just invoices.
    assert _status_of(app, 'ava@example.com') == 'approved'
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


def test_removed_request_is_not_invoiced(app, seed):
    guest = _guest(app)
    customer_client = _login_as(app, CUSTOMER_EMAIL)
    slug = _setup(app, seed)
    keep = _make_pending(guest, seed, app, slug, email='keep@example.com')
    other = app.test_client()
    skip = _make_pending(other, seed, app, slug, email='skip@example.com')
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
    assert 'A Set Amount Is Covered' in html
    assert 'name="sponsor_items_per_person"' in html


# ── Emails ───────────────────────────────────────────────────────────────────

def _subjects(outbox):
    return [(m.subject, list(m.recipients)) for m in outbox]


def test_emails_follow_a_request_from_start_to_production(seed, app, outbox):
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    _request(guest, slug, email='ava@example.com')
    assert any("You're in" in s and r == ['ava@example.com'] for s, r in _subjects(outbox))

    sub_id = _in_db(app, lambda: SponsorSubmission.query.first().id)
    organizer = _login_as(app, CUSTOMER_EMAIL)
    organizer.post(f'/c/{slug}/manage-sponsored/invoice')
    before = len(outbox)
    inv = _the_invoice(app)
    _owner_client(app).post(f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}/mark-paid', data={'method': 'check'})
    sent = _subjects(outbox)[before:]
    assert any('going into production' in s and r == ['ava@example.com'] for s, r in sent)
    assert any('Company invoice paid' in s and app.config['ADMIN_EMAIL'] in r for s, r in sent)


def test_declined_email_mentions_the_refund(seed, app, outbox, monkeypatch):
    guest = _guest(app)
    slug = _setup(app, seed, items=1, budget=10.0)
    _fake_stripe(monkeypatch, charge_cents=876, refunds=[])
    _fill_cart(guest, seed, qty=1)
    _request(guest, slug)
    guest.get(f'/c/{slug}/sponsored/paid')
    sub_id = _in_db(app, lambda: SponsorSubmission.query.first().id)
    _login_as(app, CUSTOMER_EMAIL).post(
        f'/c/{slug}/manage-sponsored/review',
        data={'submission_id': sub_id, 'action': 'reject', 'reason': 'Not on staff'})
    declined = [m for m in outbox if m.subject.startswith('Update on your request')]
    assert len(declined) == 1
    assert 'refunded' in declined[0].body and 'Not on staff' in declined[0].body


# ── Employee changes a size or cancels ──────────────────────────────────────

def _my_request_path(app):
    from utils.group_sponsor import edit_url
    url = _in_db(app, lambda: edit_url(SponsorSubmission.query.first()))
    return url[url.index('/c/'):]


def _line_size(app):
    return _in_db(app, lambda: SponsorSubmission.query.first().items[0]['size'])


def test_email_carries_the_private_link_and_bad_links_404(seed, app, outbox):
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    _request(guest, slug)
    mail = [m for m in outbox if "You're in" in m.subject][0]
    assert '/sponsored/my-request/' in mail.body
    path = _my_request_path(app)
    assert guest.get(path).status_code == 200
    assert guest.get(path[:-3] + 'abc').status_code == 404


def test_employee_can_change_a_size_that_costs_the_same(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    _request(guest, slug)
    path = _my_request_path(app)
    guest.post(path + '/sizes', data={'size_0': 'L'})
    assert _line_size(app) == 'L'
    prod = _in_db(app, lambda: SponsorSubmission.query.first().items[0].get('transfer_production'))
    assert prod is None or prod.get('size') == 'L'          # print info follows the size


def test_a_size_with_a_different_price_is_refused(seed, app, monkeypatch):
    import utils.pricing as pricing
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    _request(guest, slug)
    path = _my_request_path(app)
    real = pricing.price_cart_item
    monkeypatch.setattr(pricing, 'price_cart_item',
                        lambda item, product, design=None: 25.0 if item.get('size') == '4XL' else real(item, product, design=design))
    resp = guest.post(path + '/sizes', data={'size_0': '4XL'}, follow_redirects=True)
    assert 'priced differently' in resp.get_data(as_text=True)
    assert _line_size(app) == 'M'                              # nothing was saved


def test_no_changes_once_the_invoice_exists(seed, app):
    guest = _guest(app)
    slug = _setup(app, seed)
    _fill_cart(guest, seed)
    _request(guest, slug)
    path = _my_request_path(app)
    _login_as(app, CUSTOMER_EMAIL).post(f'/c/{slug}/manage-sponsored/invoice')
    resp = guest.post(path + '/sizes', data={'size_0': 'L'}, follow_redirects=True)
    assert 'can no longer be changed' in resp.get_data(as_text=True)
    assert _line_size(app) == 'M'
    assert guest.post(path + '/cancel').status_code == 302
    assert _status_of(app, 'ava@example.com') == 'invoiced'


def test_employee_can_cancel_and_is_refunded(seed, app, outbox, monkeypatch):
    guest = _guest(app)
    slug = _setup(app, seed, items=1, budget=10.0)
    refunds = []
    _fake_stripe(monkeypatch, charge_cents=876, refunds=refunds)
    _fill_cart(guest, seed, qty=1)
    _request(guest, slug)
    guest.get(f'/c/{slug}/sponsored/paid')
    path = _my_request_path(app)
    guest.post(path + '/cancel')
    guest.post(path + '/cancel')                              # a second tap does nothing
    assert _status_of(app, 'ava@example.com') == 'rejected'
    assert len(refunds) == 1
    assert sum(m.subject.startswith('Request cancelled') for m in outbox) == 1


# ── Batches, spending totals, CSV, company page ─────────────────────────────

def test_invoice_in_batches_keeps_the_link_open(seed, app):
    slug = _setup(app, seed)
    organizer = _login_as(app, CUSTOMER_EMAIL)
    first = _guest(app)
    _make_pending(first, seed, app, slug, email='one@example.com')
    organizer.post(f'/c/{slug}/manage-sponsored/invoice', data={'close': '0'})
    assert not _in_db(app, lambda: db.session.get(Collection, seed['collection_id']).sponsor_submissions_locked)

    second = _guest(app)                                   # link still open: a new person can join
    _make_pending(second, seed, app, slug, email='two@example.com')
    organizer.post(f'/c/{slug}/manage-sponsored/invoice')  # final batch, closes the link

    def check():
        invoices = CompanyInvoice.query.order_by(CompanyInvoice.id).all()
        assert len(invoices) == 2
        assert invoices[0].submission_ids != invoices[1].submission_ids
        assert [i.total for i in invoices] == [19.71, 19.71]
        assert db.session.get(Collection, seed['collection_id']).sponsor_submissions_locked
    _in_db(app, check)


def test_dashboard_shows_what_everyone_owes(seed, app):
    slug = _setup(app, seed)
    _make_pending(_guest(app), seed, app, slug)
    html = _login_as(app, CUSTOMER_EMAIL).get(f'/c/{slug}/manage-sponsored').get_data(as_text=True)
    assert 'The company will be billed' in html and '$18.00' in html
    assert 'Download list' in html


def test_csv_lists_every_item_and_is_safe_in_excel(seed, app):
    slug = _setup(app, seed)
    guest = _guest(app)
    _fill_cart(guest, seed)
    _request(guest, slug, first_name='=HYPERLINK("x")')
    resp = _login_as(app, CUSTOMER_EMAIL).get(f'/c/{slug}/manage-sponsored/requests.csv')
    assert resp.status_code == 200 and resp.mimetype == 'text/csv'
    text = resp.get_data(as_text=True)
    assert 'Company pays' in text and '18.00' in text and 'Counted' in text
    assert "'=HYPERLINK" in text                           # a formula is made harmless
    assert _guest(app).get(f'/c/{slug}/manage-sponsored/requests.csv').status_code in (302, 401, 403)


def test_company_page_and_signup_flow(seed, app):
    page = _guest(app).get('/shop/company-apparel')
    assert page.status_code == 200 and 'Company Apparel' in page.get_data(as_text=True)
    form = _login_as(app, CUSTOMER_EMAIL).get('/shop/group-orders/create?mode=company').get_data(as_text=True)
    assert 'value="company_sponsored" checked' in form
    plain = _login_as(app, CUSTOMER_EMAIL).get('/shop/group-orders/create').get_data(as_text=True)
    assert 'value="each_pays" checked' in plain
