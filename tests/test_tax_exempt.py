"""Tax-exempt customers: no tax at checkout while signed in, labelled for the report, expiry, and the filing reminder."""
import threading
from datetime import date, timedelta

import pytest

from conftest import CUSTOMER_EMAIL
from models import TaxExemption, User
from utils import ledger as L
from utils import sales_tax, tax_exempt as TE


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


def _totals_for(app, email=None, method='pickup'):
    from flask_login import login_user
    from routes.checkout import calculate_totals

    def go():
        with app.test_request_context('/'):
            if email:
                login_user(User.query.filter_by(email=email).first())
            return calculate_totals([{'quantity': 2, 'unit_price': 50.0}], method)
    return _in_db(app, go)


def test_an_exempt_customer_pays_no_tax_and_is_labelled(app, seed):
    _in_db(app, lambda: TE.add_exemption(email=CUSTOMER_EMAIL, organization='Lincoln PTA', certificate_number='ST-28B-1'))
    normal, exempt = _totals_for(app), _totals_for(app, CUSTOMER_EMAIL)
    assert normal['tax'] > 0 and normal['tax_jurisdiction'] == sales_tax.LOCAL
    assert exempt['tax'] == 0 and exempt['total'] == 100.0
    assert exempt['tax_jurisdiction'] == sales_tax.EXEMPT and exempt['tax_rate_percent'] == 0.0


def test_other_signed_in_customers_and_guests_still_pay(app, seed):
    _in_db(app, lambda: TE.add_exemption(email=CUSTOMER_EMAIL))
    other = _in_db(app, lambda: User.query.filter(User.email != CUSTOMER_EMAIL, User.is_admin.is_(False)).first().email)
    assert _totals_for(app, other)['tax'] > 0 and _totals_for(app)['tax'] > 0


def test_expired_or_switched_off_charges_tax_again(app, seed):
    def setup():
        row = TE.add_exemption(email=CUSTOMER_EMAIL, expires_on=date(2020, 1, 1))
        return row.id
    row_id = _in_db(app, setup)
    assert _totals_for(app, CUSTOMER_EMAIL)['tax'] > 0                           # expired
    _in_db(app, lambda: TE.add_exemption(email=CUSTOMER_EMAIL))                  # renewed with no end date
    assert _totals_for(app, CUSTOMER_EMAIL)['tax'] == 0
    _in_db(app, lambda: TE.set_active(row_id, False))
    assert _totals_for(app, CUSTOMER_EMAIL)['tax'] > 0


def test_out_of_state_shipping_keeps_its_own_label_for_an_exempt_customer(app, seed):
    _in_db(app, lambda: TE.add_exemption(email=CUSTOMER_EMAIL))
    from flask_login import login_user
    from routes.checkout import calculate_totals

    def go():
        with app.test_request_context('/'):
            login_user(User.query.filter_by(email=CUSTOMER_EMAIL).first())
            return calculate_totals([{'quantity': 1, 'unit_price': 50.0}], 'shipping', ship_state='MO', ship_zip='64105')
    assert _in_db(app, go)['tax_jurisdiction'] == sales_tax.OUT_OF_STATE


def test_an_account_must_exist(app, seed):
    with pytest.raises(ValueError):
        _in_db(app, lambda: TE.add_exemption(email='nobody@example.com'))


def test_attention_list_and_status(app, seed):
    def go():
        today = date(2026, 10, 2)
        TE.add_exemption(email=CUSTOMER_EMAIL, expires_on=today + timedelta(days=20))
        row = TaxExemption.query.first()
        assert TE.status(row, today) == 'soon' and TE.needing_attention(today) == [row]
        assert TE.status(row, today + timedelta(days=30)) == 'expired'
        row.expires_on = None
        assert TE.status(row, today) == 'ok' and TE.needing_attention(today) == []
    _in_db(app, go)


def test_filing_reminder_lines(app, seed):
    def go():
        assert TE.filing_line(date(2026, 10, 2)) is None                         # off until set
        TE.save_filing('monthly', 25)
        assert 'September 2026 is due October 25' in TE.filing_line(date(2026, 10, 2)).replace('return for ', '')
        TE.save_filing('quarterly', 25)
        assert TE.filing_line(date(2026, 11, 2)) is None                         # October is not a quarter end
        assert 'July to September 2026' in TE.filing_line(date(2026, 10, 2))
        TE.save_filing('annual', 25)
        assert TE.filing_line(date(2026, 10, 2)) is None and TE.filing_line(date(2027, 1, 2)) is not None
        for bad in (('weekly', 5), ('monthly', 0), ('monthly', 31)):
            with pytest.raises(ValueError):
                TE.save_filing(*bad)
    _in_db(app, go)


def test_the_page_for_admin(admin_client):
    resp = admin_client.get('/admin/operations/tax-exempt')
    assert resp.status_code == 200 and b'Tax-Exempt Customers' in resp.data
    resp = admin_client.post('/admin/operations/tax-exempt', data={'action': 'filing', 'frequency': 'monthly', 'due_day': '25'},
                             follow_redirects=True)
    assert b'Filing reminder saved' in resp.data


def test_the_page_is_closed_to_guests(guest):
    assert guest.get('/admin/operations/tax-exempt').status_code in (301, 302, 303, 401, 403, 404)
