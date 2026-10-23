"""Emails for hand-made invoices: send the invoice with a Pay button, and the paid receipt."""
from __future__ import annotations

from flask import current_app

from utils.sponsor_emails import _safe, _send


def _doc(inv):
    from utils.invoice_pay import doc_for
    return doc_for(inv)


def _lines_text(doc):
    return '; '.join(f"{l['qty']:g} × {l['name']}" for l in doc['lines'])


def send_invoice(inv):
    """Email the customer their invoice with a Pay button. Returns True if it was handed to the mailer."""
    from utils.invoice_pay import pay_url
    doc = _doc(inv)
    first = (doc['attn'] or doc['name'] or '').split(' ')[0]
    return _safe(
        _send, inv.email, f"Your invoice from Purposefully Made KC ({inv.number})",
        f"Your invoice, ${doc['balance']:,.2f}",
        [f"Hi{' ' + first if first else ''}! Thank you so much for your order. "
         "Your invoice is ready, and you can pay it by card with the button below.",
         'Prefer Venmo, cash or a check? Just reply to this email and we will sort it out.'],
        button={'label': 'View & pay invoice', 'url': pay_url(inv)},
        details=[('Invoice', inv.number), ('Items', _lines_text(doc)),
                 ('Total', f"${doc['total']:,.2f}"), ('Balance due', f"${doc['balance']:,.2f}")],
    )


def paid(inv, amount):
    """Receipt to the customer, and a heads-up to the shop."""
    from utils.mailer import admin_base_url, admin_recipient
    doc = _doc(inv)
    app = current_app._get_current_object()
    if inv.email:
        _safe(
            _send, inv.email, f"Payment received: {inv.number}",
            'Thank you, your payment went through!',
            [f"We received ${amount:,.2f} for invoice {inv.number}."
             + (' Your invoice is now paid in full.' if doc['balance'] <= 0 else
                f" The remaining balance is ${doc['balance']:,.2f}.")],
            details=[('Invoice', inv.number), ('Paid by', 'Card')],
        )
    _safe(
        _send, admin_recipient(app), f"Invoice paid by card: {inv.number} (${amount:,.2f})",
        'An invoice was paid online',
        [f"{inv.customer_name or 'A customer'} paid ${amount:,.2f} by card on invoice {inv.number}."
         + (' It is now paid in full.' if doc['balance'] <= 0 else f" Balance left: ${doc['balance']:,.2f}.")],
        button={'label': 'Open invoice', 'url': f"{admin_base_url(app)}/admin/invoices/{inv.id}"},
    )
