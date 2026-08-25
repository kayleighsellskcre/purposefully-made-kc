"""Every transactional email: does it send, what does it contain, can it double-send.

MAIL_SUPPRESS_SEND is on, so nothing leaves the machine. The `outbox` fixture
captures what would have been sent.
"""
import io
from datetime import datetime
from unittest.mock import patch

import pytest

from models import db, CustomDesignRequest, Order, User
from utils.mailer import SENDER_NAME


TAX = 0.095


def _fill_cart(client, seed):
    resp = client.post('/cart/add', data={
        'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black',
        'quantity': 1, 'placement': 'left_chest',
        'design_id': seed['free_design_id'],
        'back_design_name': 'SMITH', 'back_design_number': '12',
    })
    assert resp.status_code == 200


def _place_cash_order(client, seed, app, token='tok-mail-1', email='buyer@example.com'):
    from models import Collection, db
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.allow_cash_pickup = True
        db.session.commit()
    with client.session_transaction() as sess:
        sess['collection_id'] = seed['collection_id']
    _fill_cart(client, seed)
    body = client.post('/checkout/complete', json={
        'payment_method': 'cash', 'shipping_method': 'pickup',
        'email': email, 'first_name': 'Casey', 'last_name': 'Customer',
        'phone': '816-555-0100', 'checkout_token': token,
    }).get_json()
    assert body['success'] is True, body
    return body['order_number']


# ── The bug that stopped every receipt ───────────────────────────────────────

def test_order_emails_actually_send(client, seed, outbox, app):
    """Regression for the root cause: rendering a receipt outside a request
    context hit flask_login's current_user (None) and raised AttributeError,
    so confirmation_email_sent_at stayed NULL and nothing was ever delivered."""
    order_number = _place_cash_order(client, seed, app)
    assert len(outbox) >= 1, 'no email was generated for a completed order'
    with app.app_context():
        order = Order.query.filter_by(order_number=order_number).one()
        assert order.confirmation_email_sent_at is not None


def test_receipt_renders_with_no_request_context(app, seed):
    """Directly exercise the path the background thread takes."""
    from routes.checkout import _render_email
    with app.app_context():
        order = Order(
            order_number='CTX-1', email='a@example.com', first_name='Casey',
            last_name='Customer', subtotal=30.0, tax=2.85, total=32.85,
            payment_status='paid', payment_method='stripe',
            created_at=datetime.utcnow(),
        )
        db.session.add(order)
        db.session.commit()
        html = _render_email('email/order_confirmation.html', order=order)
    assert 'CTX-1' in html


def test_both_customer_and_business_emails_are_sent(client, seed, outbox, app):
    _place_cash_order(client, seed, app)
    subjects = [m.subject for m in outbox]
    assert any('receipt' in s.lower() for s in subjects), subjects
    assert any('new order' in s.lower() for s in subjects), subjects


# ── Sender identity ──────────────────────────────────────────────────────────

def test_sender_shows_the_business_name(client, seed, outbox, app):
    _place_cash_order(client, seed, app)
    for message in outbox:
        assert SENDER_NAME in str(message.sender), message.sender


def test_customer_receipt_has_a_reply_to(client, seed, outbox, app):
    _place_cash_order(client, seed, app)
    receipt = next(m for m in outbox if 'receipt' in m.subject.lower())
    assert receipt.reply_to


# ── Receipt content ──────────────────────────────────────────────────────────

@pytest.fixture()
def receipt(client, seed, outbox, app):
    _place_cash_order(client, seed, app)
    return next(m for m in outbox if 'receipt' in m.subject.lower())


def test_receipt_has_a_plain_text_fallback(receipt):
    assert receipt.body
    assert receipt.html
    assert receipt.body != receipt.html


def test_receipt_names_the_customer(receipt):
    assert 'Casey' in receipt.body


def test_receipt_shows_the_order_number(receipt):
    assert 'PMKC' in receipt.body
    assert 'PMKC' in receipt.html


def test_receipt_itemises_the_product(receipt):
    assert 'Unisex Jersey Short Sleeve Tee' in receipt.body
    assert 'Black' in receipt.body
    assert 'Size M' in receipt.body


def test_receipt_shows_placement_and_personalization(receipt):
    """These were missing from the plain-text receipt entirely."""
    assert 'left chest' in receipt.body
    assert 'SMITH' in receipt.body
    assert '12' in receipt.body
    assert 'SMITH' in receipt.html


def test_receipt_breaks_out_every_money_line(receipt):
    for label in ('Subtotal', 'Shipping', 'Tax', 'Total'):
        assert label in receipt.body, f'{label} missing from plain-text receipt'


def test_receipt_totals_are_internally_consistent(client, seed, outbox, app):
    order_number = _place_cash_order(client, seed, app)
    receipt = next(m for m in outbox if 'receipt' in m.subject.lower())
    with app.app_context():
        order = Order.query.filter_by(order_number=order_number).one()
    assert f'${order.total:.2f}' in receipt.body
    assert f'${order.subtotal:.2f}' in receipt.body
    assert f'{order.total:.2f}' in receipt.html


def test_receipt_explains_the_next_step(receipt):
    assert 'Pickup' in receipt.body or 'pickup' in receipt.body


def test_receipt_includes_business_contact(receipt):
    assert 'purposefullymadekc@gmail.com' in receipt.body


def test_receipt_has_no_localhost_links(receipt):
    """ADMIN_BASE_URL used to default to localhost, poisoning real emails."""
    assert 'localhost' not in receipt.html
    assert 'localhost' not in receipt.body


# ── Business alert content ───────────────────────────────────────────────────

@pytest.fixture()
def business_alert(client, seed, outbox, app):
    _place_cash_order(client, seed, app)
    return next(m for m in outbox if 'new order' in m.subject.lower())


def test_business_alert_has_customer_contact(business_alert):
    assert 'Casey Customer' in business_alert.body
    assert 'buyer@example.com' in business_alert.body
    assert '816-555-0100' in business_alert.body


def test_business_alert_shows_payment_status(business_alert):
    assert 'CASH' in business_alert.body.upper()


def test_business_alert_links_to_the_admin_order(business_alert, app):
    with app.app_context():
        base = app.config['ADMIN_BASE_URL']
    assert f'{base}/admin/orders/' in business_alert.body
    assert 'localhost' not in business_alert.body


def test_business_alert_links_the_artwork(business_alert):
    """Production needs the file, not just its name."""
    assert 'artwork' in business_alert.html.lower()


def test_business_alert_replies_to_the_customer(business_alert):
    assert business_alert.reply_to == 'buyer@example.com'


def test_business_alert_shows_personalization(business_alert):
    assert 'SMITH' in business_alert.html


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_receipt_is_not_sent_twice_for_one_order(client, seed, outbox, app):
    order_number = _place_cash_order(client, seed, app)
    first_count = len(outbox)

    with app.app_context():
        from routes.checkout import send_order_confirmation_email
        order = Order.query.filter_by(order_number=order_number).one()
        send_order_confirmation_email(order)

    assert len(outbox) == first_count, 'a second receipt was generated'


def test_resending_the_confirmation_page_does_not_duplicate(client, seed, outbox, app):
    order_number = _place_cash_order(client, seed, app)
    before = len(outbox)
    for _ in range(3):
        client.post(f'/checkout/confirmation/{order_number}/send-email')
    assert len(outbox) == before


def test_force_allows_a_deliberate_resend(client, seed, outbox, app):
    """The owner must still be able to re-send a receipt on request."""
    order_number = _place_cash_order(client, seed, app)
    before = len(outbox)
    with app.app_context():
        from routes.checkout import send_order_confirmation_email
        order = Order.query.filter_by(order_number=order_number).one()
        send_order_confirmation_email(order, force=True)
    assert len(outbox) > before


# ── Design request emails ────────────────────────────────────────────────────

def _submit_design_request(client, description='Please recreate this logo in navy.'):
    return client.post(
        '/custom-design/submit',
        data={
            'description': description,
            'reference_image': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 200), 'logo.png'),
        },
        content_type='multipart/form-data',
        follow_redirects=False,
    )


def test_design_request_sends_both_emails(customer_client, seed, outbox, app):
    """Regression: design requests previously sent no email at all, only an SMS."""
    resp = _submit_design_request(customer_client)
    assert resp.status_code == 302

    subjects = [m.subject for m in outbox]
    assert any('got your design request' in s.lower() for s in subjects), subjects
    assert any('new design request' in s.lower() for s in subjects), subjects

    with app.app_context():
        req = CustomDesignRequest.query.order_by(CustomDesignRequest.id.desc()).first()
        assert req.emails_sent_at is not None


@pytest.fixture()
def design_request_emails(customer_client, seed, outbox):
    _submit_design_request(customer_client)
    customer = next(m for m in outbox if 'got your design request' in m.subject.lower())
    business = next(m for m in outbox if 'new design request' in m.subject.lower())
    return customer, business


def test_design_request_customer_email_content(design_request_emails):
    customer, _ = design_request_emails
    assert customer.body and customer.html
    assert 'Casey Customer' in customer.body
    assert 'recreate this logo' in customer.body
    assert 'logo.png' in customer.body
    assert 'business day' in customer.body
    assert 'purposefullymadekc@gmail.com' in customer.body
    assert 'localhost' not in customer.html


def test_design_request_customer_email_goes_to_the_customer(design_request_emails, seed):
    customer, _ = design_request_emails
    assert customer.recipients == ['customer-test@example.com']


def test_design_request_business_email_content(design_request_emails, app):
    _, business = design_request_emails
    assert business.body and business.html
    assert 'Casey Customer' in business.body
    assert 'customer-test@example.com' in business.body
    assert '816-555-0100' in business.body
    assert 'recreate this logo' in business.body
    with app.app_context():
        base = app.config['ADMIN_BASE_URL']
    assert f'{base}/admin/custom-design-requests/' in business.body


def test_design_request_business_email_links_the_reference(design_request_emails):
    _, business = design_request_emails
    assert 'reference' in business.html.lower()
    assert 'logo.png' in business.html


def test_design_request_business_email_replies_to_the_customer(design_request_emails):
    _, business = design_request_emails
    assert business.reply_to == 'customer-test@example.com'


def test_design_request_emails_are_not_sent_twice(customer_client, seed, outbox, app):
    _submit_design_request(customer_client)
    before = len(outbox)
    with app.app_context():
        from utils.design_request_mail import send_design_request_emails
        req = CustomDesignRequest.query.order_by(CustomDesignRequest.id.desc()).first()
        send_design_request_emails(app, req.id)
    assert len(outbox) == before


def test_a_failed_design_request_sends_nothing(customer_client, seed, outbox):
    """No description means no saved request, so no email should go out."""
    resp = customer_client.post(
        '/custom-design/submit',
        data={'description': '', 'reference_image': (io.BytesIO(b'x'), 'a.png')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 302
    assert len(outbox) == 0


# ── Password reset ───────────────────────────────────────────────────────────

def test_password_reset_email_is_sent(client, seed, outbox):
    """Regression: this ran in a background thread with no request context, so
    url_for(_external=True) and the template render both failed silently."""
    resp = client.post('/auth/forgot-password',
                       data={'email': 'customer-test@example.com'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert len(outbox) == 1
    assert 'reset' in outbox[0].subject.lower()


def test_password_reset_email_has_a_working_link(client, seed, outbox, app):
    client.post('/auth/forgot-password', data={'email': 'customer-test@example.com'})
    message = outbox[0]
    assert message.body and message.html
    assert '/auth/reset-password/' in message.body
    assert '/auth/reset-password/' in message.html
    assert 'localhost' not in message.body

    with app.app_context():
        token = User.query.filter_by(email='customer-test@example.com').one().reset_token
    assert token in message.body

    resp = client.get(f'/auth/reset-password/{token}')
    assert resp.status_code == 200


def test_password_reset_for_unknown_email_sends_nothing(client, seed, outbox):
    client.post('/auth/forgot-password', data={'email': 'nobody@example.com'})
    assert len(outbox) == 0


# ── Dev-mode guard ───────────────────────────────────────────────────────────

def test_mail_test_redirect_protects_real_customers(app, seed, outbox, client):
    """With MAIL_TEST_REDIRECT set, no customer address can receive mail."""
    app.config['MAIL_TEST_REDIRECT'] = 'owner-only@example.com'
    try:
        _place_cash_order(client, seed, app, email='real-customer@example.com')
        assert outbox, 'expected at least one message'
        for message in outbox:
            assert message.recipients == ['owner-only@example.com']
            # The intended recipient is preserved in the subject for triage.
            assert message.subject.startswith('[TEST \u2192 ')
        receipt = next(m for m in outbox if 'receipt' in m.subject.lower())
        assert 'real-customer@example.com' in receipt.subject
    finally:
        app.config['MAIL_TEST_REDIRECT'] = None


def test_no_redirect_by_default(app):
    assert not app.config.get('MAIL_TEST_REDIRECT')


# ── Failure tolerance ────────────────────────────────────────────────────────

def test_a_mail_outage_does_not_lose_a_paid_order(client, seed, app):
    """A dead SMTP relay must never turn a saved order into a checkout failure."""
    # Connection.send is the real work; app.extensions['mail'] is a state
    # object rather than the Mail instance, so patching Mail.send misses it.
    with patch('flask_mail.Connection.send', side_effect=Exception('smtp down')):
        order_number = _place_cash_order(client, seed, app, token='tok-outage')

    with app.app_context():
        order = Order.query.filter_by(order_number=order_number).one()
        assert order.confirmation_email_sent_at is None


def test_an_order_with_no_email_left_unsent_can_be_retried(client, seed, app, outbox):
    with patch('flask_mail.Connection.send', side_effect=Exception('smtp down')):
        order_number = _place_cash_order(client, seed, app, token='tok-retry')
    assert len(outbox) == 0

    with app.app_context():
        from routes.checkout import send_order_confirmation_email
        order = Order.query.filter_by(order_number=order_number).one()
        assert send_order_confirmation_email(order) is True
        assert order.confirmation_email_sent_at is not None
    assert len(outbox) >= 1


def test_missing_mail_credentials_are_reported_not_crashed(app, seed, client):
    original = app.config['MAIL_SERVER']
    app.config['MAIL_SERVER'] = None
    try:
        order_number = _place_cash_order(client, seed, app, token='tok-nocreds')
        assert order_number
    finally:
        app.config['MAIL_SERVER'] = original
