"""Enter an order: a whole group's names, sizes and numbers in one table."""
import json

from models import LedgerEntry, ManualInvoice, Order, OrderItem, Product, db
from utils import bulk_orders as B


def _payload(app, **over):
    with app.app_context():
        youth = Product.query.filter_by(style_number='3001Y').first().id
    data = {
        'customer': {'name': 'Dana Coach', 'company': 'Lions', 'email': 'dana@example.com', 'phone': '555-0100'},
        'fulfillment': 'shipping',
        'ship': {'street': '1 Main St', 'city': 'Topeka', 'state': 'KS', 'zip': '66601'},
        'shipping': '12.00', 'tax_percent': '9.5', 'note': '',
        'groups': [{'product_id': youth, 'color': 'Black', 'price': '24.00', 'design_id': '', 'rows': [
            {'person': 'Sarah Jones', 'size': 'YM', 'back_name': 'JONES', 'number': '12', 'qty': 1},
            {'person': 'Emma Smith', 'size': 'YM', 'back_name': 'SMITH', 'number': '8', 'qty': 1},
            {'person': 'Mia Lee', 'size': 'YL', 'back_name': 'LEE', 'number': '3', 'qty': 2},
        ]}],
    }
    data.update(over)
    return data


def _enter(admin_client, app, **over):
    resp = admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(_payload(app, **over))})
    return resp


def test_paste_reads_a_spreadsheet_with_or_without_a_header():
    rows = B.parse_paste('Name\tSize\tName on back\tNumber\tQty\nSarah Jones\tYM\tJONES\t12\t1\nEmma\tYL\tSMITH\t8\t2\n')
    assert [r['person'] for r in rows] == ['Sarah Jones', 'Emma']
    assert rows[1]['size'] == 'YL' and rows[1]['qty'] == 2 and rows[0]['number'] == '12'
    plain = B.parse_paste('Sarah Jones\tYM\tJONES\t12\t1')
    assert plain[0]['back_name'] == 'JONES'
    swapped = B.parse_paste('Number,Name,Size\n7,Ava Ray,YS')
    assert swapped[0]['person'] == 'Ava Ray' and swapped[0]['number'] == '7' and swapped[0]['size'] == 'YS'


def test_it_makes_an_awaiting_payment_order_and_one_invoice(admin_client, app):
    resp = _enter(admin_client, app)
    assert resp.status_code == 302 and '/admin/invoices/' in resp.headers['Location']
    with app.app_context():
        order = Order.query.one()
        inv = ManualInvoice.query.one()
        assert order.status == 'new' and order.payment_status == 'awaiting_payment'
        assert inv.order_id == order.id and inv.kind == 'invoice'
        # 4 shirts at $24 = $96, tax 9.5% = $9.12, shipping $12
        assert order.subtotal == 96.0 and order.tax == 9.12 and order.shipping_cost == 12.0 and order.total == 117.12
        items = OrderItem.query.filter_by(order_id=order.id).order_by(OrderItem.id).all()
        assert [i.size for i in items] == ['YM', 'YM', 'YL']
        assert items[0].back_design_details['name'] == 'JONES' and items[0].back_design_details['number'] == '12'
        assert items[0].notes == 'For Sarah Jones' and items[2].quantity == 2
        # invoice lines are grouped, names live on the order
        assert [(l['qty'], l['unit']) for l in json.loads(inv.items_json)] == [(2, 24.0), (2, 24.0)]


def test_the_new_order_shows_in_the_workflow_marked_awaiting_payment(admin_client, app):
    _enter(admin_client, app)
    page = admin_client.get('/admin/operations/workflow')
    assert page.status_code == 200
    assert 'Awaiting payment' in page.get_data(as_text=True)


def test_order_page_points_to_the_invoice(admin_client, app):
    _enter(admin_client, app)
    with app.app_context():
        order_id = Order.query.one().id
        number = ManualInvoice.query.one().number
    html = admin_client.get(f'/admin/orders/{order_id}').get_data(as_text=True)
    assert 'Awaiting payment.' in html and number in html and 'For Sarah Jones' in html


def test_paying_the_invoice_releases_the_order_and_the_books_count_it_once(admin_client, app):
    from utils import ledger as L
    from utils import receivables
    _enter(admin_client, app)
    with app.app_context():
        inv = ManualInvoice.query.one()
        receivables.record_payment(inv.id, 50, 'Cash')
        order = Order.query.one()
        assert order.payment_status == 'awaiting_payment' and order.amount_paid == 50.0     # part paid: still waiting
        receivables.record_payment(inv.id, 67.12, 'Cash')
        order = Order.query.one()
        assert order.payment_status == 'invoice_paid' and order.status == 'paid'
        L.sync_all(force=True)
        sales = db.session.query(db.func.sum(LedgerEntry.amount_cents)).filter(LedgerEntry.entry_type == L.SALE).scalar()
        assert sales == 9600                                    # the $96 of shirts, counted one time
        assert LedgerEntry.query.filter(LedgerEntry.order_id == order.id).count() == 0


def test_card_payment_on_the_pay_link_releases_the_order(admin_client, app):
    from utils.invoice_pay import apply_card_payment
    _enter(admin_client, app)
    with app.app_context():
        inv = ManualInvoice.query.one()
        assert apply_card_payment(inv, 'pi_test_bulk', 11712)
        order = Order.query.one()
        assert order.payment_status == 'invoice_paid' and order.status == 'paid'


def test_a_missing_size_or_name_sends_the_form_back_with_what_was_typed(admin_client, app):
    bad = _payload(app)
    bad['groups'][0]['rows'][0]['size'] = ''
    resp = admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(bad)})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and 'Please pick a size for Sarah Jones' in html and 'Dana Coach' in html
    nameless = _payload(app, customer={'name': ''})
    resp = admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(nameless)})
    assert 'Please add who the order is for' in resp.get_data(as_text=True)
    with app.app_context():
        assert Order.query.count() == 0 and ManualInvoice.query.count() == 0


def test_pickup_has_no_shipping_address_needed(admin_client, app):
    _enter(admin_client, app, fulfillment='pickup', ship={}, shipping='0')
    with app.app_context():
        order = Order.query.one()
        assert order.fulfillment_method == 'pickup' and order.shipping_street is None and order.total == 105.12


def test_deleting_the_order_keeps_the_invoice(admin_client, app):
    _enter(admin_client, app)
    with app.app_context():
        order_id = Order.query.one().id
    assert admin_client.post(f'/admin/orders/{order_id}/delete').status_code == 302
    with app.app_context():
        assert Order.query.count() == 0
        assert ManualInvoice.query.one().order_id is None


def test_only_the_admin_can_enter_an_order(client):
    assert client.get('/admin/orders/enter/token').status_code in (302, 401, 403)
    assert client.get('/admin/orders/enter').status_code in (302, 401, 403)
    assert client.post('/admin/orders/enter', data={'order_json': '{}'}).status_code in (302, 400, 401, 403)


def test_the_entry_page_opens_and_the_button_is_on_the_board(admin_client):
    page = admin_client.get('/admin/orders/enter')
    assert page.status_code == 200 and 'Enter an order' in page.get_data(as_text=True)
    assert '/admin/orders/enter' in admin_client.get('/admin/operations/workflow').get_data(as_text=True)


def test_a_half_finished_order_can_be_saved_as_a_draft_and_finished_later(admin_client, app):
    from models import BulkOrderDraft
    unfinished = _payload(app, customer={'name': '', 'company': 'Lions'})
    unfinished['groups'][0]['rows'][0]['size'] = ''
    resp = admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(unfinished), 'action': 'draft'})
    assert resp.status_code == 302
    with app.app_context():
        draft = BulkOrderDraft.query.one()
        assert draft.title == 'Lions' and Order.query.count() == 0
        draft_id = draft.id
    page = admin_client.get(f'/admin/orders/enter?draft={draft_id}').get_data(as_text=True)
    assert 'Saved drafts' in page and 'Sarah Jones' in page            # reopens with what was typed
    done = _payload(app)
    resp = admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(done), 'draft_id': str(draft_id)})
    assert resp.status_code == 302 and '/admin/invoices/' in resp.headers['Location']
    with app.app_context():
        assert BulkOrderDraft.query.count() == 0 and Order.query.count() == 1


def test_a_draft_can_be_deleted(admin_client, app):
    from models import BulkOrderDraft
    admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(_payload(app)), 'action': 'draft'})
    with app.app_context():
        draft_id = BulkOrderDraft.query.one().id
    assert admin_client.post(f'/admin/orders/enter/drafts/{draft_id}/delete').status_code == 302
    with app.app_context():
        assert BulkOrderDraft.query.count() == 0


def test_individual_invoices_one_per_person_and_the_order_waits_for_all(admin_client, app):
    from utils import receivables
    payload = _payload(app, billing='individual', shipping='0')
    payload['groups'][0]['rows'] = [
        {'person': 'Sarah Jones', 'size': 'YM', 'back_name': 'JONES', 'number': '12', 'qty': 1, 'email': 'sarah@example.com'},
        {'person': 'Emma Smith', 'size': 'YL', 'back_name': 'SMITH', 'number': '8', 'qty': 2},
    ]
    resp = admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(payload)})
    assert resp.status_code == 302 and '/admin/orders/' in resp.headers['Location']
    with app.app_context():
        order = Order.query.one()
        invs = ManualInvoice.query.order_by(ManualInvoice.id).all()
        assert [i.customer_name for i in invs] == ['Sarah Jones', 'Emma Smith']
        assert invs[0].email == 'sarah@example.com' and all(i.order_id == order.id for i in invs)
        assert invs[0].number != invs[1].number
        # $24 + 9.5% = 26.28 and 2 x $24 + 9.5% = 52.56; the order is the sum of its invoices
        assert order.subtotal == 72.0 and order.tax == 6.84 and order.total == 78.84
        receivables.record_payment(invs[0].id, 26.28, 'Cash')
        order = Order.query.one()
        assert order.payment_status == 'awaiting_payment' and order.amount_paid == 26.28   # one of two paid
        receivables.record_payment(invs[1].id, 52.56, 'Cash')
        order = Order.query.one()
        assert order.payment_status == 'invoice_paid' and order.status == 'paid'
    page = admin_client.get(f'/admin/orders/{order.id}').get_data(as_text=True)
    assert 'Sarah Jones' in page and 'Emma Smith' in page


def test_paste_can_carry_an_email_column():
    rows = B.parse_paste('Name\tSize\tEmail\nSarah Jones\tYM\tsarah@example.com')
    assert rows[0]['email'] == 'sarah@example.com' and rows[0]['size'] == 'YM'


def test_the_entry_page_can_get_a_fresh_form_token(admin_client):
    got = admin_client.get('/admin/orders/enter/token')
    assert got.status_code == 200 and 'token' in got.get_json()


def test_cancelling_an_invoice_billed_order_points_at_the_open_invoice(admin_client, app):
    _enter(admin_client, app)
    with app.app_context():
        order_id = Order.query.one().id
    html = admin_client.post(f'/admin/orders/{order_id}/cancel', follow_redirects=True).get_data(as_text=True)
    assert 'billed on an invoice' in html


def test_pickup_never_charges_shipping_even_if_an_amount_was_typed(admin_client, app):
    _enter(admin_client, app, fulfillment='pickup', shipping='12.00')
    with app.app_context():
        order = Order.query.one()
        assert order.shipping_cost == 0.0 and order.total == 105.12


def test_enter_an_order_is_in_the_admin_menu(admin_client):
    html = admin_client.get('/admin/operations/workflow').get_data(as_text=True)
    menu = html[html.index('ops-dropdown-menu'):]
    assert '/admin/orders/enter' in menu[:3000] and 'Enter an order' in menu[:3000]


def test_a_typed_list_like_hash_one_dunn_size_s_is_lined_up():
    rows = B.parse_paste('#1 Dunn (size S)\n#11 Cunningham (size M)\n#42 Andrews (size L)\n12 Sarah Jones M')
    assert [(r['number'], r['back_name'], r['size']) for r in rows] == [
        ('1', 'DUNN', 'S'), ('11', 'CUNNINGHAM', 'M'), ('42', 'ANDREWS', 'L'), ('12', 'JONES', 'M')]
    assert rows[3]['person'] == 'Sarah Jones' and rows[0]['person'] == 'Dunn'
    # spreadsheet rows still work, even mixed in
    assert B.parse_paste('Name\tSize\nAva Lee\tYM')[0]['person'] == 'Ava Lee'


def test_logo_placement_font_and_color_reach_the_order(admin_client, app, seed):
    from models import OrderItem
    p = _payload(app)
    g = p['groups'][0]
    g.update({'design_id': str(seed['free_design_id']), 'placement': 'left_chest', 'font': 'Anton', 'text_color': '#b91c1c'})
    admin_client.post('/admin/orders/enter', data={'order_json': json.dumps(p)})
    with app.app_context():
        item = OrderItem.query.order_by(OrderItem.id).first()
        assert item.placement == 'left_chest' and item.design_id == seed['free_design_id']
        meta = item.back_design_details
        assert meta['name'] == 'JONES' and meta['font'] == 'Anton' and meta['text_color'] == '#b91c1c'


def test_needed_by_date_sets_the_due_date_and_prints_on_the_invoice(admin_client, app):
    _enter(admin_client, app, needed_by='2026-12-20')
    with app.app_context():
        order = Order.query.one()
        assert order.due_date.strftime('%Y-%m-%d') == '2026-12-20'
        assert 'Needed by Dec 20, 2026' in ManualInvoice.query.one().note


def test_the_form_can_fetch_shirt_photos_for_the_mockup(admin_client, seed):
    got = admin_client.get(f'/admin/orders/enter/mockup?product_id={seed["tee_id"]}&color=Black')
    assert got.status_code == 200 and set(got.get_json()) == {'front', 'back'}


def test_the_page_is_built_for_a_phone_and_has_logo_font_and_mockups(admin_client):
    html = admin_client.get('/admin/orders/enter').get_data(as_text=True)
    for needle in ('Upload logo', 'Name and number on the back', 'Paste your list here', 'Needed by',
                   'max-width: 768px', 'data-label', 'Save as draft'):
        assert needle in html
