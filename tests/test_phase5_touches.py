"""Estimated ready date, occasion note, confirmation page and care lines."""
from datetime import date

from models import Order, SystemSettings, db
from tests.test_checkout import _cash_payload, _fill_cart
from utils import ready_date


def test_business_days_skip_weekends():
    friday = date(2026, 10, 23)
    assert ready_date.add_business_days(friday, 1) == date(2026, 10, 26)
    assert ready_date.add_business_days(friday, 5) == date(2026, 10, 30)
    assert ready_date.format_day(date(2026, 11, 13)) == 'Friday, November 13'


def test_ready_note_and_care_lines_show_on_the_product_page(guest, seed):
    note = ready_date.ready_note()
    assert note.startswith('Estimated ready by ')
    html = guest.get(f"/shop/product/{seed['tee_slug']}").get_data(as_text=True)
    assert note in html and 'printing error' in html


def test_admin_can_change_the_ready_days(admin_client, app):
    resp = admin_client.post('/admin/operations/site-settings', data={'section': 'ready', 'ready_business_days': '20'})
    assert resp.status_code == 302
    with app.app_context():
        assert SystemSettings.query.filter_by(key='ready_business_days').first().value == '20'
    ready_date._CACHE['at'] = 0.0
    assert ready_date.get_business_days() == 20
    admin_client.post('/admin/operations/site-settings', data={'section': 'ready', 'ready_business_days': '2'})   # too low: ignored
    with app.app_context():
        assert SystemSettings.query.filter_by(key='ready_business_days').first().value == '20'


def test_occasion_note_is_saved_and_shown(client, seed, app):
    _fill_cart(client, seed, app=app, allow_cash=True)
    payload = _cash_payload()
    payload['occasion_note'] = 'Maya\'s 10th birthday'
    body = client.post('/checkout/complete', json=payload).get_json()
    html = client.get(f"/checkout/confirmation/{body['order_number']}").get_data(as_text=True)
    assert 'Made for:' in html and '10th birthday' in html and 'Estimated ready by' in html
    with app.app_context():
        assert Order.query.filter_by(order_number=body['order_number']).first().occasion_note == "Maya's 10th birthday"
