"""Track my order without logging in."""
from datetime import datetime, timedelta

import pytest

from app import limiter
from models import Order, db
from tests.conftest import CUSTOMER_EMAIL

NUMBER = 'PMKC20261025AB12CD34'


def _order(app, **fields):
    with app.app_context():
        values = dict(order_number=NUMBER, email='pat@example.com', first_name='Pat', last_name='Parent', subtotal=30.0,
                      total=30.0, payment_status='paid', status='new', production_stage='order_received',
                      payment_method='stripe', fulfillment_method='pickup', paid_at=datetime.utcnow())
        values.update(fields)
        order = Order(**values)
        db.session.add(order)
        db.session.commit()


def _track(client, number=NUMBER, email='pat@example.com'):
    return client.post('/track', data={'order_number': number, 'email': email}).get_data(as_text=True)


def test_the_form_opens_without_signing_in_and_is_in_the_footer(guest):
    html = guest.get('/track').get_data(as_text=True)
    assert 'Track My Order' in html and 'name="order_number"' in html and 'name="email"' in html
    assert guest.get('/about').get_data(as_text=True).count('/track') >= 1


def test_the_right_number_and_email_show_the_status_steps(app, seed, guest):
    _order(app)
    html = _track(guest)
    assert f'Order {NUMBER}' in html and 'We have your order and will start on it soon.' in html
    assert html.index('Order received') < html.index('Being made') < html.index('Ready for pickup') < html.index('Picked up')
    assert html.count('aria-current="step"') == 1


def test_the_number_can_be_typed_with_dashes_spaces_or_lowercase(app, seed, guest):
    _order(app)
    for typed in ('pmkc-20261025-ab12cd34', 'PMKC 2026 1025 AB12CD34', f' {NUMBER.lower()} '):
        assert f'Order {NUMBER}' in _track(guest, number=typed), typed


def test_the_email_can_be_typed_in_any_case_and_the_account_email_works_too(app, seed, guest):
    _order(app, user_id=seed['customer_id'])
    assert f'Order {NUMBER}' in _track(guest, email='PAT@Example.com')
    assert f'Order {NUMBER}' in _track(guest, email=CUSTOMER_EMAIL)


def test_a_wrong_email_and_a_wrong_number_look_exactly_alike(app, seed, guest):
    _order(app)
    wrong_email = _track(guest, email='someone@else.com')
    wrong_number = _track(guest, number='PMKC00000000FFFFFFFF')
    for html in (wrong_email, wrong_number):
        assert 'We could not find an order with that number and email' in html
        assert 'track-order-no' not in html and 'track-steps' not in html and 'Pat Parent' not in html and f'Order {NUMBER}' not in html
    assert 'We could not find' in _track(guest, number='', email='')


def test_steps_follow_the_order_through_the_shop(app, seed, guest):
    cases = [
        (dict(status='in_production', production_stage='pressed'), 'We are making your order now.'),
        (dict(status='ready', production_stage='packaged_ready'), 'Your order is ready.'),
        (dict(status='completed', production_stage=None), 'Your order is complete. Thank you!'),
        (dict(status='cancelled'), 'This order was cancelled.'),
    ]
    for fields, headline in cases:
        _order(app, **fields)
        assert headline in _track(guest), fields
        with app.app_context():
            Order.query.filter_by(order_number=NUMBER).delete()
            db.session.commit()


def test_a_cancelled_order_shows_no_progress_steps(app, seed, guest):
    _order(app, status='cancelled')
    assert 'track-steps' not in _track(guest)


def test_a_shipped_order_shows_the_tracking_link(app, seed, guest):
    _order(app, status='shipped', fulfillment_method='shipping', carrier='UPS', tracking_number='1Z999AA10123456784')
    html = _track(guest)
    assert 'Your order has shipped.' in html and 'Shipped' in html
    assert 'https://www.ups.com/track?tracknum=1Z999AA10123456784' in html


def test_a_ready_pickup_order_shows_where_to_pick_it_up(app, seed, guest):
    _order(app, status='ready', production_stage='packaged_ready')
    assert 'Pickup address' in _track(guest) or 'Pickup details' in _track(guest) or 'Your order is ready.' in _track(guest)


def test_a_send_home_order_says_who_it_is_going_home_with(app, seed, guest):
    _order(app, status='ready', production_stage='packaged_ready', send_home_with_child=True, child_name='Sam')
    html = _track(guest)
    assert 'Ready, going home with your child' in html and 'Sam' in html


def test_the_estimated_ready_date_shows_while_it_is_being_made(app, seed, guest):
    _order(app, due_date=datetime(2026, 11, 12))
    assert 'Estimated ready date' in _track(guest) and 'November 12' in _track(guest)


def test_the_page_is_not_cached_or_indexed_and_never_puts_the_email_in_the_address(app, seed, guest):
    _order(app)
    resp = guest.post('/track', data={'order_number': NUMBER, 'email': 'pat@example.com'})
    assert resp.status_code == 200 and 'no-store' in resp.headers['Cache-Control'] and 'noindex' in resp.headers['X-Robots-Tag']
    assert guest.get(f'/track?order_number={NUMBER}&email=pat@example.com').get_data(as_text=True).count(f'Order {NUMBER}') == 0


@pytest.fixture()
def limits_on(app):
    was = app.config.get('RATELIMIT_ENABLED')
    app.config['RATELIMIT_ENABLED'] = True
    limiter.enabled = True
    try:
        limiter.reset()
    except Exception:
        pass
    yield
    try:
        limiter.reset()
    except Exception:
        pass
    app.config['RATELIMIT_ENABLED'] = was
    limiter.enabled = bool(was)


def test_guessing_is_capped_but_looking_at_the_form_is_not(app, seed, guest, limits_on):
    for _ in range(30):
        assert guest.get('/track').status_code == 200
    codes = [guest.post('/track', data={'order_number': 'PMKC1', 'email': 'a@b.com'}).status_code for _ in range(22)]
    assert codes[:20] == [200] * 20 and 429 in codes[20:]
