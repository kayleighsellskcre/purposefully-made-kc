"""Hand-made invoices: pay link, email, text, QR, and paying by card."""
import json

from models import ManualInvoice, db
from tests.conftest import CUSTOMER_EMAIL
from tests.test_company_sponsored import _Obj, _in_db, _login_as, _owner_client


def _invoice(app, **over):
    def go():
        values = dict(
            number='INV-2026-0001', customer_name='Riverview PTO', email='pto@example.com',
            phone='(816) 555-0142', tax_rate=9.5,
            items_json=json.dumps([{'description': 'Spirit shirts', 'qty': 2, 'unit': 20.0}]),
        )
        values.update(over)
        inv = ManualInvoice(**values)
        db.session.add(inv)
        db.session.commit()
        return inv.id
    return _in_db(app, go)


def _facts(app, inv_id):
    from utils.invoice_pay import balance_cents

    def go():
        inv = db.session.get(ManualInvoice, inv_id)
        return dict(token=inv.pay_token, paid=inv.amount_paid, method=inv.payment_method,
                    cents=balance_cents(inv), sent=inv.pay_link_sent_at)
    return _in_db(app, go)


def _stripe(monkeypatch, cents):
    import stripe
    created = []
    monkeypatch.setattr(stripe, 'api_key', 'sk_test_fake')
    monkeypatch.setattr(stripe.PaymentIntent, 'create',
                        lambda **kw: created.append(kw) or _Obj(id='pi_inv_1', client_secret='cs_inv', amount=kw['amount']))
    monkeypatch.setattr(stripe.PaymentIntent, 'retrieve',
                        lambda pid: _Obj(id=pid, status='succeeded', amount=cents))
    return created


def test_admin_creates_the_link_and_sees_email_text_and_qr(seed, app):
    inv_id = _invoice(app)
    owner = _owner_client(app)
    page = owner.get(f'/admin/invoices/{inv_id}').get_data(as_text=True)
    assert 'Create pay link' in page and '/qr.png' not in page
    owner.post(f'/admin/invoices/{inv_id}/pay-link')
    token = _facts(app, inv_id)['token']
    page = owner.get(f'/admin/invoices/{inv_id}').get_data(as_text=True)
    assert f'/pay/{token}' in page and 'Email invoice' in page
    assert 'Text the link' in page and 'sms:8165550142' in page
    assert f'/pay/{token}/qr.png' in page                  # QR on the printed invoice


def test_only_the_shop_owner_can_manage_links(seed, app):
    inv_id = _invoice(app)
    assert _login_as(app, CUSTOMER_EMAIL).post(f'/admin/invoices/{inv_id}/pay-link').status_code in (302, 401, 403)
    assert _facts(app, inv_id)['token'] is None


def test_pay_page_charges_exactly_the_balance(seed, app, monkeypatch):
    inv_id = _invoice(app)
    _owner_client(app).post(f'/admin/invoices/{inv_id}/pay-link')
    facts = _facts(app, inv_id)
    created = _stripe(monkeypatch, facts['cents'])
    page = app.test_client().get(f'/pay/{facts["token"]}')
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and 'Spirit shirts' in html and 'cs_inv' in html
    assert created[0]['amount'] == facts['cents'] == 4380
    assert app.test_client().get('/pay/not-a-real-token').status_code == 404


def test_card_payment_marks_the_invoice_paid_once_and_sends_receipts(seed, app, monkeypatch, outbox):
    inv_id = _invoice(app)
    _owner_client(app).post(f'/admin/invoices/{inv_id}/pay-link')
    facts = _facts(app, inv_id)
    _stripe(monkeypatch, facts['cents'])
    guest = app.test_client()
    guest.get(f'/pay/{facts["token"]}')                    # starts the payment
    for _ in range(2):                                      # a refresh or a second tap changes nothing
        resp = guest.get(f'/pay/{facts["token"]}/return')
        assert resp.status_code == 302
    after = _facts(app, inv_id)
    assert after['paid'] == 43.80 and after['method'] == 'Card' and after['cents'] == 0
    page = guest.get(f'/pay/{facts["token"]}?paid=1').get_data(as_text=True)
    assert 'Paid in full' in page and 'Pay $' not in page
    subjects = [(m.subject, list(m.recipients)) for m in outbox]
    assert sum('Payment received' in s and r == ['pto@example.com'] for s, r in subjects) == 1
    assert sum('Invoice paid by card' in s for s, _ in subjects) == 1


def test_webhook_marks_it_paid_if_the_customer_closed_the_page(seed, app, monkeypatch):
    import stripe
    inv_id = _invoice(app)
    _owner_client(app).post(f'/admin/invoices/{inv_id}/pay-link')
    facts = _facts(app, inv_id)
    _stripe(monkeypatch, facts['cents'])
    app.test_client().get(f'/pay/{facts["token"]}')
    monkeypatch.setattr(stripe.Webhook, 'construct_event', lambda *a, **k: {
        'type': 'payment_intent.succeeded', 'data': {'object': {'id': 'pi_inv_1', 'amount': facts['cents']}}})
    hook = app.test_client()
    for _ in range(2):
        resp = hook.post('/checkout/stripe-webhook', data=b'{}', headers={'Stripe-Signature': 'x'})
        assert resp.get_json()['manual_invoice'] == 'INV-2026-0001'
    assert _facts(app, inv_id)['paid'] == 43.80


def test_turning_the_link_off_stops_it_working(seed, app):
    inv_id = _invoice(app)
    owner = _owner_client(app)
    owner.post(f'/admin/invoices/{inv_id}/pay-link')
    token = _facts(app, inv_id)['token']
    owner.post(f'/admin/invoices/{inv_id}/pay-link', data={'action': 'off'})
    guest = app.test_client()
    assert guest.get(f'/pay/{token}').status_code == 404
    assert guest.get(f'/pay/{token}/qr.png').status_code == 404


def test_emailing_the_invoice_includes_the_pay_button(seed, app, outbox):
    inv_id = _invoice(app)
    owner = _owner_client(app)
    owner.post(f'/admin/invoices/{inv_id}/send')
    token = _facts(app, inv_id)['token']
    mail = [m for m in outbox if 'Your invoice from Purposefully Made KC' in m.subject][0]
    assert list(mail.recipients) == ['pto@example.com'] and f'/pay/{token}' in mail.body
    assert _facts(app, inv_id)['sent'] is not None


def test_emailing_needs_an_email_address(seed, app, outbox):
    inv_id = _invoice(app, email='')
    resp = _owner_client(app).post(f'/admin/invoices/{inv_id}/send', follow_redirects=True)
    assert 'Add the customer' in resp.get_data(as_text=True)
    assert not [m for m in outbox if 'Your invoice' in m.subject]


def test_qr_code_is_a_real_image(seed, app):
    inv_id = _invoice(app)
    _owner_client(app).post(f'/admin/invoices/{inv_id}/pay-link')
    token = _facts(app, inv_id)['token']
    resp = app.test_client().get(f'/pay/{token}/qr.png')
    assert resp.status_code == 200 and resp.mimetype == 'image/png'
    assert resp.data[:8] == b'\x89PNG\r\n\x1a\n'
