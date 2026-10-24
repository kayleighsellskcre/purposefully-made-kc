"""Kansas sales tax, light version: adjustable rate, no Kansas tax on out-of-state shipments, labels and the report."""
import threading
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models import Order, OrderItem, db
from tests.test_checkout import _cash_payload, _fill_cart, _stripe_intent
from utils import ledger as L
from utils import sales_tax as T


def _in_db(app, fn):
    out = {}

    def run():
        with app.app_context():
            try:
                out['value'] = fn()
            except Exception as exc:          # pragma: no cover
                out['error'] = exc
    t = threading.Thread(target=run)
    t.start()
    t.join()
    if 'error' in out:
        raise out['error']
    return out.get('value')


@pytest.fixture(autouse=True)
def _fresh():
    T.clear_cache()
    L._LAST_SYNC['at'] = 0.0
    yield
    T.clear_cache()
    L._LAST_SYNC['at'] = 0.0


# ---- the rules ----

def test_kansas_is_recognized_even_when_typed_badly():
    for state in ('KS', 'ks', 'Kansas', ' kansas ', 'Kans.', 'Kansa', 'K.S.'):
        assert T.is_kansas(state), state
    assert not T.is_kansas('MO') and not T.is_kansas('Missouri') and not T.is_kansas('') and not T.is_kansas(None)
    assert T.is_kansas('Missouri-ish', '66218') is True          # a Kansas ZIP counts, so a typo never turns tax off
    assert T.is_kansas('MO', '64105') is False


def test_who_is_charged_tax():
    assert T.charges_tax('pickup') and T.charges_tax('pickup', 'MO')           # pickup is always taxed
    assert T.charges_tax('shipping') and T.charges_tax('shipping', '')         # unknown state: tax stays on
    assert T.charges_tax('shipping', 'KS', '66218') and T.charges_tax('shipping', 'Kansas')
    assert not T.charges_tax('shipping', 'MO', '64105') and not T.charges_tax('shipping', 'Texas', '75001')
    assert (T.jurisdiction_key('pickup'), T.jurisdiction_key('shipping', 'KS'), T.jurisdiction_key('shipping', 'MO')) == \
        (T.LOCAL, T.KS_SHIPPED, T.OUT_OF_STATE)


# ---- the rate ----

def test_the_rate_defaults_and_can_be_changed(app, seed):
    def go():
        first = T.rate_percent()
        T.save_rate_percent('9.6')
        second = (T.rate_percent(), T.rate_fraction())
        problems = []
        for bad in ('0', '20', 'abc', ''):
            try:
                T.save_rate_percent(bad)
            except ValueError as exc:
                problems.append(str(exc))
        return first, second, len(problems), T.rate_percent()
    first, second, problems, still = _in_db(app, go)
    assert first == 9.5 and second == (9.6, 0.096) and problems == 4 and still == 9.6


def test_settings_page_saves_the_rate(admin_client, app, seed):
    page = admin_client.get('/admin/operations/site-settings').get_data(as_text=True)
    assert 'Kansas sales tax rate' in page and 'name="rate"' in page
    admin_client.post('/admin/operations/site-settings', data={'section': 'tax', 'rate': '9.725'})
    assert _in_db(app, lambda: T.rate_percent()) == 9.725
    bad = admin_client.post('/admin/operations/site-settings', data={'section': 'tax', 'rate': '99'}, follow_redirects=True)
    assert 'between' in bad.get_data(as_text=True) and _in_db(app, lambda: T.rate_percent()) == 9.725


# ---- checkout totals ----

def _totals(app, method, state=None, zip_code=None, price=50.0, qty=2):
    from routes.checkout import calculate_totals

    def go():
        return calculate_totals([{'quantity': qty, 'unit_price': price}], method, ship_state=state, ship_zip=zip_code)
    return _in_db(app, go)


def test_totals_follow_where_the_order_goes(app, seed):
    pickup = _totals(app, 'pickup')
    in_kansas = _totals(app, 'shipping', 'KS', '66218')
    missouri = _totals(app, 'shipping', 'MO', '64105')
    assert (pickup['tax'], pickup['total'], pickup['tax_jurisdiction']) == (9.5, 109.5, 'local')
    assert (in_kansas['tax'], in_kansas['total'], in_kansas['tax_jurisdiction']) == (9.5, 120.5, 'ks_shipped')
    assert (missouri['tax'], missouri['total'], missouri['tax_jurisdiction'], missouri['tax_rate_percent']) == (0.0, 111.0, 'out_of_state', 0.0)


def test_totals_use_the_rate_from_settings(app, seed):
    _in_db(app, lambda: T.save_rate_percent('9.6'))
    assert _totals(app, 'pickup')['tax'] == 9.6 and _totals(app, 'shipping', 'MO')['tax'] == 0.0


def test_card_payment_amount_matches_the_destination(client, seed, app):
    _fill_cart(client, seed)
    seen = []

    def fake_create(**kw):
        seen.append(kw['amount'])
        return SimpleNamespace(id='pi_x', client_secret='secret')
    with patch('stripe.PaymentIntent.create', side_effect=fake_create):
        for body in ({'shipping_method': 'pickup'},
                     {'shipping_method': 'shipping', 'ship_state': 'KS', 'ship_zip': '66218'},
                     {'shipping_method': 'shipping', 'ship_state': 'MO', 'ship_zip': '64105'}):
            assert client.post('/checkout/create-payment-intent', json=body).status_code == 200
    assert seen == [3285, 4385, 4100]            # $30 + 9.5% tax; plus $11 shipping; plus $11 shipping and no tax


def _ship(state, zip_code):
    return {'recipient': 'Casey Customer', 'street': '1 Main St', 'city': 'Somewhere', 'state': state, 'zip': zip_code}


def test_out_of_state_order_is_saved_without_tax_and_labelled(client, seed, app):
    _fill_cart(client, seed)
    with patch('stripe.PaymentIntent.retrieve', return_value=_stripe_intent(4100)):
        body = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_mo', shipping_method='shipping', shipping_info=_ship('MO', '64105'))).get_json()
    assert body['success'] is True
    with app.app_context():
        o = Order.query.filter_by(order_number=body['order_number']).one()
        assert (o.tax, o.total, o.tax_jurisdiction, o.tax_rate_percent, o.shipping_state) == (0.0, 41.0, 'out_of_state', 0.0, 'MO')


def test_kansas_shipment_is_taxed_and_labelled(client, seed, app):
    _fill_cart(client, seed)
    with patch('stripe.PaymentIntent.retrieve', return_value=_stripe_intent(4385)):
        body = client.post('/checkout/complete', json=_cash_payload(
            payment_method='stripe', payment_id='pi_ks', shipping_method='shipping', shipping_info=_ship('KS', '66218'))).get_json()
    assert body['success'] is True
    with app.app_context():
        o = Order.query.filter_by(order_number=body['order_number']).one()
        assert (o.tax, o.tax_jurisdiction, o.tax_rate_percent) == (2.85, 'ks_shipped', 9.5)


def test_pickup_order_is_labelled_local(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    body = client.post('/checkout/complete', json=_cash_payload()).get_json()
    with app.app_context():
        o = Order.query.filter_by(order_number=body['order_number']).one()
        assert (o.tax_jurisdiction, o.tax_rate_percent) == ('local', 9.5)


def test_checkout_page_has_a_state_dropdown_and_the_tax_logic(client, seed, app):
    _fill_cart(client, seed)
    html = client.get('/checkout/').get_data(as_text=True)
    assert '<select id="ship_state"' in html and '<option value="MO">Missouri</option>' in html and '<option value="KS">Kansas</option>' in html
    assert 'refreshTaxForAddress' in html and 'No Kansas sales tax on orders shipped out of state.' in html
    assert 'const taxRate = 0.095;' in html


# ---- the report ----

def _paid(number, **kw):
    defaults = dict(email='a@example.com', subtotal=100.0, shipping_cost=11.0, tax=9.5, total=120.5, payment_status='paid',
                    status='paid', payment_method='stripe', fulfillment_method='pickup',
                    paid_at=datetime(2026, 10, 15, 18, 0))
    defaults.update(kw)
    o = Order(order_number=number, **defaults)
    db.session.add(o)
    db.session.flush()
    return o


def test_report_groups_by_where_taxed_and_flags_old_out_of_state_tax(admin_client, app, seed):
    def make():
        _paid('PMKC-T1')                                                                         # pickup, taxed
        _paid('PMKC-T2', fulfillment_method='shipping', shipping_state='KS', shipping_zip='66218')
        _paid('PMKC-T3', fulfillment_method='shipping', shipping_state='MO', shipping_zip='64105', tax=0.0, total=111.0)
        _paid('PMKC-T4', fulfillment_method='shipping', shipping_state='MO', shipping_zip='64105')   # taxed before the change
        db.session.commit()
        L.sync_all(force=True)
        return L.sales_tax_report(date(2026, 10, 1), date(2026, 10, 31))
    report = _in_db(app, make)
    rows = {r['key']: r for r in report['rows']}
    assert rows['local']['tax'] == 950 and rows['local']['taxable'] == 10000 and rows['local']['orders'] == 1
    assert rows['ks_shipped']['tax'] == 950
    assert rows['out_of_state']['orders'] == 2 and rows['out_of_state']['tax'] == 950      # only the old one was taxed
    assert rows['out_of_state']['not_taxed'] == 10000 and rows['out_of_state']['taxable'] == 10000
    assert report['out_of_state_tax'] == 950
    assert report['totals']['tax'] == 2850 and report['totals']['shipping'] == 4400
    page = admin_client.get('/admin/operations/sales-tax?period=custom&from=2026-10-01&to=2026-10-31').get_data(as_text=True)
    assert 'Shipped out of state' in page and 'collected on orders shipped out of state' in page and '$28.50' in page


def test_refunds_come_off_the_tax_report_on_their_own_day(app, seed):
    def make():
        o = _paid('PMKC-T5')
        o.refunded_cents, o.refunded_at = 12050, datetime(2026, 11, 4, 18, 0)
        db.session.commit()
        L.sync_all(force=True)
        return (L.sales_tax_report(date(2026, 10, 1), date(2026, 10, 31))['totals']['tax'],
                L.sales_tax_report(date(2026, 11, 1), date(2026, 11, 30))['totals']['tax'])
    assert _in_db(app, make) == (950, -950)


def test_older_entries_get_labels_without_changing_amounts(app, seed):
    def make():
        o = _paid('PMKC-T6')
        db.session.commit()
        L.sync_all(force=True)
        before = [(e.id, e.amount_cents) for e in L.LedgerEntry.query.order_by(L.LedgerEntry.id).all()]
        L.LedgerEntry.query.update({'jurisdiction': None, 'taxable': None, 'tax_rate_percent': None})     # as they were before labels
        db.session.commit()
        L.sync_all(force=True)
        after = [(e.id, e.amount_cents) for e in L.LedgerEntry.query.order_by(L.LedgerEntry.id).all()]
        return before == after, {e.jurisdiction for e in L.LedgerEntry.query.all()}
    same, labels = _in_db(app, make)
    assert same and labels == {'local'}


def test_report_downloads(admin_client, app, seed):
    _in_db(app, lambda: (_paid('PMKC-T7'), db.session.commit()))
    csv_resp = admin_client.get('/admin/operations/sales-tax?format=csv&period=custom&from=2026-10-01&to=2026-10-31')
    assert csv_resp.mimetype == 'text/csv' and 'Pickup or hand-off in Kansas' in csv_resp.get_data(as_text=True)
    pdf = admin_client.get('/admin/operations/sales-tax?format=pdf&period=custom&from=2026-10-01&to=2026-10-31')
    assert pdf.mimetype == 'application/pdf' and pdf.data.startswith(b'%PDF')


def test_report_is_admin_only(guest, seed):
    assert guest.get('/admin/operations/sales-tax').status_code in (302, 401, 403, 404)
