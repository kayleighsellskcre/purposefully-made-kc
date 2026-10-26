"""An organizer's whole job, start to finish, as a person would do it with a test account.

Create a store, change how it is paid for, collect what shoppers send in, make the invoice, download the lists.
No real payments: the shop owner marks the sponsor invoice paid by hand, exactly as in the live flow.
"""
from models import Collection, CompanyInvoice, GroupRosterEntry, Order, SponsorSubmission
from tests.conftest import CUSTOMER_EMAIL
from tests.test_company_sponsored import (
    _fill_cart, _guest, _in_db, _login_as, _owner_client, _request, _the_invoice,
)

PASSWORD = 'TestPassw0rd!23'


def _create(client, seed, name, mode, **extra):
    data = {'name': name, 'payment_mode': mode, 'products': [str(seed['tee_id'])],
            'allowed_designs': [str(seed['free_design_id'])], 'allowed_placements': ['center_chest'],
            'group_kind': 'school'}
    if mode == 'organizer_pays':
        data['allowed_colors'] = [f'p:{seed["tee_id"]}||Black']
    data.update(extra)
    return client.post('/shop/group-orders/create', data=data, content_type='multipart/form-data', follow_redirects=True)


def _slug(app, name):
    return _in_db(app, lambda: Collection.query.filter_by(name=name).first().slug)


def test_organizer_pays_from_setup_to_roster_download(app, seed):
    organizer = _login_as(app, CUSTOMER_EMAIL)
    page = _create(organizer, seed, 'Walkthrough Roster Store', 'organizer_pays', expected_count='3').get_data(as_text=True)
    assert '0 of 3' in page                                         # lands on the share page with the headcount
    slug = _slug(app, 'Walkthrough Roster Store')

    parent = _guest(app)
    form = parent.get(f'/c/{slug}').get_data(as_text=True)
    assert 'name="size"' in form or 'size' in form.lower()          # a short name-and-size form, no shopping
    for first, size in (('Ava', 'M'), ('Ben', 'L')):
        resp = parent.post(f'/c/{slug}/roster', data={'first_name': first, 'last_name': 'Lopez', 'size': size},
                           follow_redirects=True)
        assert resp.status_code == 200
    assert _in_db(app, lambda: GroupRosterEntry.query.count()) == 2

    share = organizer.get(f'/c/{slug}/share').get_data(as_text=True)
    assert '2 of 3' in share and 'Lopez' in share
    sheet = organizer.get(f'/c/{slug}/roster.xlsx')
    assert sheet.status_code == 200 and 'spreadsheet' in sheet.headers['Content-Type']
    assert sheet.data[:2] == b'PK'                                 # a real .xlsx file
    assert parent.get(f'/c/{slug}/roster.xlsx').status_code in (302, 401, 403, 404)   # strangers cannot download it

    pay = organizer.post(f'/c/{slug}/roster/pay')
    assert pay.status_code == 302 and '/checkout' in pay.headers['Location']          # one payment for everyone


def test_each_person_pays_store_can_be_changed_to_a_sponsor_and_run_to_an_invoice(app, seed):
    organizer = _login_as(app, CUSTOMER_EMAIL)
    _create(organizer, seed, 'Walkthrough Sponsor Store', 'each_pays')
    slug = _slug(app, 'Walkthrough Sponsor Store')
    assert _in_db(app, lambda: Collection.query.filter_by(slug=slug).first().payment_mode) == 'each_pays'

    # change how it is paid for: a sponsor covers one item per person
    edit = organizer.get(f'/shop/group-orders/{slug}/edit')
    assert edit.status_code == 200 and 'A Set Amount Is Covered' in edit.get_data(as_text=True)
    resp = organizer.post(f'/shop/group-orders/{slug}/edit', data={
        'name': 'Walkthrough Sponsor Store', 'is_active': 'on', 'payment_mode': 'company_sponsored', 'sponsor_items_per_person': '1',
        'sponsor_budget_per_person': '', 'sponsor_message': 'Acme is covering your shirt!',
        'products': [str(seed['tee_id'])], 'allowed_designs': [str(seed['free_design_id'])],
        'allowed_placements': ['center_chest'], 'group_kind': 'other'},
        content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert _in_db(app, lambda: Collection.query.filter_by(slug=slug).first().payment_mode) == 'company_sponsored'

    # a shopper sends in a request; nothing is made or charged yet
    shopper = _guest(app)
    _in_db(app, lambda: None)
    with shopper.session_transaction() as sess:
        sess['cart'] = [{'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1, 'unit_price': 18.0,
                         'collection_id': _in_db(app, lambda: Collection.query.filter_by(slug=slug).first().id),
                         'catalog_section': 'fan'}]
    _request(shopper, slug, email='ava@example.com')
    assert _in_db(app, lambda: (SponsorSubmission.query.count(), Order.query.count())) == (1, 0)

    # the organizer reviews the requests and makes one invoice
    manage = organizer.get(f'/c/{slug}/manage-sponsored').get_data(as_text=True)
    assert 'Lopez' in manage and 'sponsor' in manage.lower() and 'employee' not in manage.lower()
    organizer.post(f'/c/{slug}/manage-sponsored/invoice')
    inv = _the_invoice(app)
    assert inv['status'] == 'unpaid' and inv['total'] > 0
    view = organizer.get(f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}')
    assert view.status_code == 200
    pdf = organizer.get(f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}/pdf')
    assert pdf.status_code == 200 and pdf.data[:4] == b'%PDF'

    # the list of requests downloads, in sponsor and shopper words
    csv = organizer.get(f'/c/{slug}/manage-sponsored/requests.csv')
    assert csv.status_code == 200 and 'Sponsor pays' in csv.get_data(as_text=True) and 'Shopper pays' in csv.get_data(as_text=True)

    # printing starts only once the sponsor's invoice is paid (the shop owner records it)
    assert _in_db(app, lambda: Order.query.count()) == 0
    _owner_client(app).post(f'/c/{slug}/manage-sponsored/invoice/{inv["id"]}/mark-paid', data={'method': 'check'})
    assert _in_db(app, lambda: Order.query.count()) == 1
    assert _in_db(app, lambda: CompanyInvoice.query.one().payment_status) == 'paid'


def test_a_stranger_cannot_reach_another_organizers_tools(app, seed):
    organizer = _login_as(app, CUSTOMER_EMAIL)
    _create(organizer, seed, 'Walkthrough Private Store', 'each_pays')
    slug = _slug(app, 'Walkthrough Private Store')
    other = _login_as(app, 'other-test@example.com')
    assert other.get(f'/shop/group-orders/{slug}/edit').status_code in (302, 403, 404)
    assert other.get(f'/c/{slug}/manage-sponsored').status_code in (302, 403, 404)
    assert other.get(f'/c/{slug}/roster.xlsx').status_code in (302, 403, 404)
