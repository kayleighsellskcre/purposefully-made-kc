"""The one-page PDF receipt: its layout, the email attachment and the download links."""
import json
import re
import threading

from models import ManualInvoice, db
from utils import invoice_emails
from utils.business_info import BUSINESS
from utils.receipt_pdf import build_receipt_pdf


def _pages(pdf):
    return len(re.findall(rb'/Type\s*/Page(?!s)', pdf))


def _doc(n=4, paid=True):
    lines = [{'name': f'Custom tee {i} with a longer description of the item', 'qty': 2, 'unit': 25.0, 'total': 50.0}
             for i in range(1, n + 1)]
    sub = 50.0 * n
    return {'kind': 'receipt', 'number': 'INV-2026-0001', 'date': 'October 23, 2026', 'name': 'Amy Kline',
            'email': 'amy@example.com', 'phone': '', 'company': '', 'attn': '', 'po': '', 'address': '', 'note': '',
            'ship_to': '', 'group': '', 'lines': lines, 'subtotal': sub, 'discount': 0, 'shipping': 0, 'tax': 0,
            'tax_label': 'Tax', 'total': sub, 'paid': sub if paid else 0, 'balance': 0 if paid else sub, 'method': 'Card'}


def test_receipts_stay_on_one_page_even_when_long():
    for n in (1, 8, 25, 40):
        pdf = build_receipt_pdf(_doc(n), BUSINESS, paid_on='October 23, 2026')
        assert pdf.startswith(b'%PDF') and _pages(pdf) == 1, n


def test_the_pdf_says_what_it_is():
    from reportlab.lib.utils import ImageReader  # noqa: F401  (reportlab is installed)
    receipt = build_receipt_pdf(_doc(2), BUSINESS)
    invoice = build_receipt_pdf(_doc(2, paid=False), BUSINESS)
    assert receipt != invoice and _pages(receipt) == _pages(invoice) == 1


def _make_invoice(app, paid=True, email='amy@example.com'):
    out = {}

    def run():
        with app.app_context():
            inv = ManualInvoice(number='INV-2026-0099', customer_name='Amy Kline', email=email,
                                items_json=json.dumps([{'description': 'Custom tee', 'qty': 2, 'unit': 25.0}]),
                                tax_rate=0, amount_paid=50.0 if paid else 0, payment_method='Card', pay_token='t' * 30)
            db.session.add(inv)
            db.session.commit()
            out['id'] = inv.id
    t = threading.Thread(target=run)
    t.start()
    t.join()
    return out['id']


def test_payment_email_carries_the_pdf(app, seed, monkeypatch):
    box = []
    monkeypatch.setattr(invoice_emails, '_send', lambda *a, **kw: box.append((a, kw)) or True)

    def run():
        with app.app_context():
            inv = db.session.get(ManualInvoice, _make_invoice(app))
            invoice_emails.paid(inv, 50.0)
    t = threading.Thread(target=run)
    t.start()
    t.join()
    customer = next(kw for a, kw in box if a[0] == 'amy@example.com')
    (name, ctype, data), = customer['attachments']
    assert name == 'Receipt-INV-2026-0099.pdf' and ctype == 'application/pdf' and data.startswith(b'%PDF')
    # the shop's own heads-up needs no attachment
    assert all(not kw.get('attachments') for a, kw in box if a[0] != 'amy@example.com')


def test_brevo_payload_includes_the_attachment(app, monkeypatch):
    import base64
    import requests
    from flask_mail import Message
    from utils import mailer
    sent = {}

    class Resp:
        status_code = 201
        text = ''
    monkeypatch.setattr(requests, 'post', lambda url, json=None, **kw: sent.update(json or {}) or Resp())
    app.config['BREVO_API_KEY'] = 'test-key'
    with app.app_context():
        msg = Message(subject='Hi', recipients=['a@example.com'], body='x')
        msg.attach('Receipt.pdf', 'application/pdf', b'%PDF-1.4 fake')
        assert mailer._send_via_brevo_api(app, msg) is True
    app.config['BREVO_API_KEY'] = ''
    assert sent['attachment'][0]['name'] == 'Receipt.pdf'
    assert base64.b64decode(sent['attachment'][0]['content']) == b'%PDF-1.4 fake'


def test_customer_download_only_after_a_payment(guest, app, seed):
    paid = _make_invoice(app, paid=True)
    resp = guest.get('/pay/' + 't' * 30 + '/receipt.pdf')
    assert resp.status_code == 200 and resp.mimetype == 'application/pdf' and resp.data.startswith(b'%PDF')
    assert guest.get('/pay/wrong-token-0000000000000000/receipt.pdf').status_code == 404
    page = guest.get('/pay/' + 't' * 30).get_data(as_text=True)
    assert 'Download your receipt (PDF)' in page
    assert paid


def test_unpaid_invoice_has_no_customer_receipt(guest, app, seed):
    _make_invoice(app, paid=False)
    assert guest.get('/pay/' + 't' * 30 + '/receipt.pdf').status_code == 404


def test_admin_gets_a_one_page_pdf(admin_client, app, seed):
    inv_id = _make_invoice(app, paid=True)
    resp = admin_client.get(f'/admin/invoices/{inv_id}/pdf')
    assert resp.status_code == 200 and resp.mimetype == 'application/pdf' and _pages(resp.data) == 1
    page = admin_client.get(f'/admin/invoices/{inv_id}').get_data(as_text=True)
    assert 'One-page PDF' in page


def test_admin_pdf_is_closed_to_visitors(guest, app, seed):
    inv_id = _make_invoice(app, paid=True)
    assert guest.get(f'/admin/invoices/{inv_id}/pdf').status_code in (302, 401, 403, 404)


def test_printed_checkout_receipt_is_compact():
    src = open('templates/checkout/confirmation.html', encoding='utf-8').read()
    printed = src.split('@media print')[1]
    for rule in ('.next-steps', '#email-status', '.confirmation-page { min-height: 0; }'):
        assert rule in printed, rule


# ---- company-sponsored invoices ----

def _company_invoice(app, seed):
    out = {}

    def run():
        with app.app_context():
            from models import Collection, CompanyInvoice, SponsorSubmission, User
            from tests.conftest import CUSTOMER_EMAIL
            coll = db.session.get(Collection, seed['collection_id'])
            coll.payment_mode = 'company_sponsored'
            coll.created_by_user_id = User.query.filter_by(email=CUSTOMER_EMAIL).first().id
            items = [{'product_name': 'Tee', 'color': 'Black', 'size': 'M', 'quantity': 1, 'unit_price': 20.0, 'company_part': 20.0}]
            sub = SponsorSubmission(collection_id=coll.id, first_name='Ava', last_name='Lopez', email='ava@example.com',
                                    items_json=json.dumps(items), sponsored_total=20.0, status='invoiced')
            db.session.add(sub)
            db.session.flush()
            inv = CompanyInvoice(invoice_number='INV-20261023-ABC123', collection_id=coll.id,
                                 submission_ids_json=json.dumps([sub.id]), subtotal=20.0, tax=1.8, total=21.8)
            db.session.add(inv)
            db.session.commit()
            out['id'], out['slug'] = inv.id, coll.slug
    t = threading.Thread(target=run)
    t.start()
    t.join()
    return out


def test_company_invoice_document_and_pdf(app, seed):
    out = _company_invoice(app, seed)

    def run():
        with app.app_context():
            from models import CompanyInvoice
            from utils.receipts import doc_from_company_invoice
            inv = db.session.get(CompanyInvoice, out['id'])
            doc = doc_from_company_invoice(inv)
            assert doc['kind'] == 'invoice' and doc['balance'] == 21.8 and doc['lines'][0]['name'].startswith('Ava Lopez')
            inv.payment_status, inv.payment_method = 'paid', 'stripe'
            paid = doc_from_company_invoice(inv)
            assert paid['kind'] == 'receipt' and paid['balance'] == 0 and paid['method'] == 'Card'
            assert _pages(build_receipt_pdf(paid, BUSINESS)) == 1
    t = threading.Thread(target=run)
    t.start()
    t.join()


def test_organizer_gets_a_receipt_email_with_the_pdf_when_the_invoice_is_paid(app, seed, monkeypatch):
    from utils import sponsor_emails
    out = _company_invoice(app, seed)
    box = []
    monkeypatch.setattr(sponsor_emails, '_send', lambda *a, **kw: box.append((a, kw)) or True)

    def run():
        with app.app_context():
            from models import CompanyInvoice
            from utils.group_sponsor import mark_invoice_paid
            inv = db.session.get(CompanyInvoice, out['id'])
            mark_invoice_paid(inv, 'check')
            mark_invoice_paid(inv, 'check')                       # a second call must not send a second email
    t = threading.Thread(target=run)
    t.start()
    t.join()
    mine = [(a, kw) for a, kw in box if a[0] == 'customer-test@example.com']
    assert len(mine) == 1
    (name, ctype, data), = mine[0][1]['attachments']
    assert name == 'Receipt-INV-20261023-ABC123.pdf' and data.startswith(b'%PDF')


def test_organizer_can_download_the_company_invoice_pdf(app, seed):
    from tests.test_company_sponsored import _login_as
    out = _company_invoice(app, seed)
    client = _login_as(app, 'customer-test@example.com')
    resp = client.get(f"/c/{out['slug']}/manage-sponsored/invoice/{out['id']}/pdf")
    assert resp.status_code == 200 and resp.mimetype == 'application/pdf' and _pages(resp.data) == 1
    page = client.get(f"/c/{out['slug']}/manage-sponsored/invoice/{out['id']}").get_data(as_text=True)
    assert 'Download invoice (PDF)' in page
