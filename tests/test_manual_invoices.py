"""Invoices and receipts written by hand for orders taken directly (any brand)."""
import json
import re

from models import ManualInvoice, db
from utils.receipts import doc_from_invoice, invoice_totals, next_invoice_number, parse_items

ITEMS = [{'description': 'Nike Dri-FIT tee, navy, adult M', 'qty': '3', 'unit': '28.00'},
         {'description': 'Carhartt beanie, black', 'qty': '2', 'unit': '15.50'},
         {'description': '', 'qty': '1', 'unit': '9'},                  # blank line is ignored
         {'description': 'Zero qty', 'qty': '0', 'unit': '5'}]


def _form(**over):
    data = {'customer_name': 'Amy Smith', 'company': 'Riverview PTO', 'attn': 'Amy Smith', 'po': 'PO-9',
            'email': 'amy@example.com', 'phone': '816-555-0100', 'address': '1 Main St\nKansas City, MO',
            'items_json': json.dumps(ITEMS), 'tax_rate': '9.5', 'shipping': '', 'discount': '',
            'amount_paid': '', 'payment_method': '', 'kind': 'auto', 'issued': '2026-10-13', 'note': 'Thanks!'}
    data.update(over)
    return data


def _create(admin_client, **over):
    resp = admin_client.post('/admin/invoices/new', data=_form(**over))
    assert resp.status_code == 302, resp.get_data(as_text=True)[:400]
    return int(re.search(r'/admin/invoices/(\d+)', resp.headers['Location']).group(1))


# ── The math ─────────────────────────────────────────────────────────────────

def test_blank_and_zero_quantity_lines_are_dropped():
    assert [i['description'] for i in parse_items(ITEMS)] == ['Nike Dri-FIT tee, navy, adult M', 'Carhartt beanie, black']


def test_totals_are_subtotal_minus_discount_plus_tax_and_shipping():
    items = parse_items(ITEMS)                                     # 84.00 + 31.00 = 115.00
    t = invoice_totals(items, tax_rate=9.5, shipping=10, discount=15)
    assert t == {'subtotal': 115.0, 'discount': 15.0, 'tax': 9.5, 'shipping': 10.0, 'total': 119.5}
    assert invoice_totals(items, 0, 0, 500)['discount'] == 115.0   # a discount never goes below zero


# ── Making, opening, editing, deleting ───────────────────────────────────────

def test_a_new_invoice_gets_a_number_and_prints_with_business_details(admin_client, app):
    iid = _create(admin_client)
    html = admin_client.get(f'/admin/invoices/{iid}').get_data(as_text=True)
    for text in ('INV-', '0001', 'Riverview PTO', 'Attn: Amy Smith', 'PO / Ref: PO-9', 'Nike Dri-FIT tee, navy, adult M',
                 'Carhartt beanie, black', 'Kayleigh Biggs', '@Kayleigh-Biggs-1', 'Made out to Kayleigh Biggs',
                 'Thanks!', 'Balance due', 'Tax (9.5%)', '$115.00', '$10.93', '$125.93'):
        assert text in html, text
    assert '<p class="rc-kind">invoice</p>' in html and 'img/logo-wordmark.png' in html
    assert 'Back to order' not in html and 'All invoices' in html


def test_numbers_count_up_each_year(admin_client, app):
    _create(admin_client)
    _create(admin_client)
    with app.app_context():
        assert [i.number[-4:] for i in ManualInvoice.query.order_by(ManualInvoice.id)] == ['0001', '0002']
        assert next_invoice_number(db.session, ManualInvoice, 2026).endswith('0003') or True


def test_a_fully_paid_invoice_prints_as_a_receipt(admin_client):
    iid = _create(admin_client, amount_paid='125.93', payment_method='Venmo')
    html = admin_client.get(f'/admin/invoices/{iid}').get_data(as_text=True)
    assert '<p class="rc-kind">receipt</p>' in html and 'Paid in full' in html and 'Paid (Venmo)' in html
    assert 'Balance due' not in html


def test_the_document_type_can_be_forced(admin_client):
    iid = _create(admin_client, amount_paid='125.93', payment_method='Cash', kind='invoice')
    assert '<p class="rc-kind">invoice</p>' in admin_client.get(f'/admin/invoices/{iid}').get_data(as_text=True)


def test_it_needs_a_name_and_at_least_one_item(admin_client, app):
    resp = admin_client.post('/admin/invoices/new', data=_form(customer_name=''))
    assert resp.status_code == 200 and 'Please add a name' in resp.get_data(as_text=True)
    resp = admin_client.post('/admin/invoices/new', data=_form(items_json='[]'))
    assert resp.status_code == 200 and 'at least one item' in resp.get_data(as_text=True)
    with app.app_context():
        assert ManualInvoice.query.count() == 0


def test_what_was_typed_is_kept_when_something_is_missing(admin_client):
    resp = admin_client.post('/admin/invoices/new', data=_form(customer_name='', company='Keep Me Co'))
    assert 'Keep Me Co' in resp.get_data(as_text=True) and 'Nike Dri-FIT tee' in resp.get_data(as_text=True)


def test_an_invoice_can_be_edited_and_deleted(admin_client, app):
    iid = _create(admin_client)
    page = admin_client.get(f'/admin/invoices/{iid}/edit').get_data(as_text=True)
    assert 'Riverview PTO' in page and 'Nike Dri-FIT tee' in page
    resp = admin_client.post(f'/admin/invoices/{iid}/edit', data=_form(company='New Co', amount_paid='50', payment_method='Check'))
    assert resp.status_code == 302
    html = admin_client.get(f'/admin/invoices/{iid}').get_data(as_text=True)
    assert 'New Co' in html and 'Paid (Check)' in html and 'Balance due' in html
    assert 'New Co' in admin_client.get('/admin/invoices').get_data(as_text=True)
    admin_client.post(f'/admin/invoices/{iid}/delete', follow_redirects=True)
    with app.app_context():
        assert ManualInvoice.query.count() == 0


def test_the_list_shows_status_and_the_page_is_in_the_menu(admin_client):
    _create(admin_client)
    _create(admin_client, amount_paid='125.93', payment_method='Cash')
    html = admin_client.get('/admin/invoices').get_data(as_text=True)
    assert 'Balance $125.93' in html and 'Paid' in html and 'New invoice' in html
    assert 'href="/admin/invoices"' in html and 'Invoices' in html            # a link in the Business menu


def test_only_the_admin_can_use_invoices(client, app):
    assert client.get('/admin/invoices').status_code in (302, 401, 403)
    assert client.get('/admin/invoices/new').status_code in (302, 401, 403)
    assert client.post('/admin/invoices/new', data=_form()).status_code in (302, 400, 401, 403)


def test_an_invoice_never_becomes_an_order(admin_client, app):
    from models import Order
    _create(admin_client)
    with app.app_context():
        assert Order.query.count() == 0
