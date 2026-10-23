"""Pay a hand-made invoice online: a private link, email, text and QR code.

Kayleigh's hand-made invoices (ManualInvoice) used to be print-only. Each one can now
carry a private pay link. The customer opens it, sees the invoice and pays the balance
by card. Stripe confirms the payment (the page they return to and the webhook both
check with Stripe), the invoice is marked paid, and both sides get an email.

The link only ever opens that one invoice, and turning it off makes it stop working.
"""
from __future__ import annotations

import secrets
from urllib.parse import quote

MIN_CARD_CENTS = 50            # Stripe will not take less than $0.50


def doc_for(inv):
    from utils.receipts import doc_from_invoice
    return doc_from_invoice(inv)


def balance_cents(inv) -> int:
    return int(round(doc_for(inv)['balance'] * 100))


def ensure_token(inv):
    """Turn the pay link on (a new private address) if it is not already."""
    from models import db
    if not inv.pay_token:
        inv.pay_token = secrets.token_urlsafe(24)
        db.session.commit()
    return inv.pay_token


def turn_off(inv):
    from models import db
    inv.pay_token = None
    db.session.commit()


def invoice_for_token(token):
    from models import ManualInvoice
    if not token:
        return None
    return ManualInvoice.query.filter_by(pay_token=token).first()


def pay_url(inv):
    from flask import current_app
    from utils.mailer import admin_base_url
    return f"{admin_base_url(current_app)}/pay/{inv.pay_token}"


def sms_href(inv):
    """A link that opens the phone's text app with the message already written."""
    digits = ''.join(ch for ch in (inv.phone or '') if ch.isdigit() or ch == '+')
    doc = doc_for(inv)
    first = (doc['attn'] or doc['name'] or '').split(' ')[0]
    body = (f"Hi{' ' + first if first else ''}! Here is your invoice from Purposefully Made KC "
            f"({inv.number}) for ${doc['balance']:,.2f}. You can see it and pay by card here: {pay_url(inv)}")
    return f"sms:{digits}?&body={quote(body)}"


def qr_png(url) -> bytes:
    import io
    import qrcode
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color='#3A3D48', back_color='white').save(buf, format='PNG')
    return buf.getvalue()


def apply_card_payment(inv, intent_id, cents) -> bool:
    """Record a card payment that Stripe confirmed. Safe to call twice for the same payment."""
    from flask import current_app
    from models import db

    if inv.card_paid_intent_id == intent_id:
        return True
    if not cents or cents <= 0:
        return False
    total = doc_for(inv)['total']
    inv.amount_paid = min(total, round((inv.amount_paid or 0) + cents / 100.0, 2))
    inv.payment_method = 'Card'
    inv.card_paid_intent_id = intent_id
    db.session.commit()
    current_app.logger.info('invoice %s paid $%.2f by card', inv.number, cents / 100.0)
    from utils import invoice_emails
    invoice_emails.paid(inv, cents / 100.0)
    return True
