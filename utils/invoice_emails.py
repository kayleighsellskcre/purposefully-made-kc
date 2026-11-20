"""Emails for hand-made invoices: send the invoice with a Pay button, and the paid receipt."""
from __future__ import annotations

from flask import current_app

from utils.sponsor_emails import _safe, _send


def _doc(inv):
    from utils.invoice_pay import doc_for
    return doc_for(inv)


def _lines_text(doc):
    return '; '.join(f"{l['qty']:g} × {l['name']}" for l in doc['lines'])


def mockup_attachments(inv):
    """A PDF with a front and back mockup of each shirt on this invoice (empty when there is nothing to draw)."""
    try:
        from models import Order
        from utils.order_artwork import items_of
        from utils.order_mockups import mockup_pdf
        from models import ManualInvoice, db
        order = db.session.get(Order, inv.order_id) if inv.order_id else None
        if not order:
            return []
        items = items_of(order)
        if ManualInvoice.query.filter_by(order_id=order.id).count() > 1:       # one invoice per person: only their shirts
            items = [i for i in items if (i.notes or '') == f'For {inv.customer_name}']
        pdf = mockup_pdf(order, items, title=f'Your shirt mockups - invoice {inv.number}') if items else None
        return [(f'Mockups-{inv.number}.pdf', 'application/pdf', pdf)] if pdf else []
    except Exception:
        current_app.logger.exception('mockup PDF could not be made for %s', getattr(inv, 'number', '?'))
        return []


def send_invoice(inv):
    """Email the customer their invoice with a Pay button. Returns True if it was handed to the mailer."""
    from utils.invoice_pay import pay_url
    doc = _doc(inv)
    first = (doc['attn'] or doc['name'] or '').split(' ')[0]
    mockups = mockup_attachments(inv)
    invoice_pdf = invoice_attachments(inv)
    return _safe(
        _send, inv.email, f"Your invoice from Purposefully Made KC ({inv.number})",
        f"Your invoice, ${doc['balance']:,.2f}",
        [f"Hi{' ' + first if first else ''}! Thank you so much for your order. "
         "Your invoice is ready, and you can pay it by card with the button below.",
         'Prefer Venmo, cash or a check? Just reply to this email and we will sort it out.']
        + (['A PDF copy of your invoice is attached for your records.'] if invoice_pdf else [])
        + (['Mockups of your shirts, front and back, are attached as a PDF so you can see exactly what we will make.'] if mockups else []),
        attachments=invoice_pdf + mockups,
        button={'label': 'View & pay invoice', 'url': pay_url(inv)},
        details=[('Invoice', inv.number), ('Items', _lines_text(doc)),
                 ('Total', f"${doc['total']:,.2f}"), ('Balance due', f"${doc['balance']:,.2f}")],
    )


def invoice_attachments(inv):
    """The one-page invoice PDF as an email attachment, for the customer's records (empty if it could not be made)."""
    try:
        from utils.invoice_pay import receipt_pdf_bytes
        return [(f"Invoice-{inv.number}.pdf", 'application/pdf', receipt_pdf_bytes(inv))]
    except Exception:
        current_app.logger.exception('invoice PDF could not be made for %s', getattr(inv, 'number', '?'))
        return []


def receipt_attachments(inv, doc=None):
    """The one-page PDF receipt as an email attachment (empty if it could not be made)."""
    try:
        from utils.business_info import BUSINESS
        from utils.receipt_pdf import build_receipt_pdf
        from utils.receipts import _date_label
        from datetime import datetime
        doc = doc or _doc(inv)
        pdf = build_receipt_pdf(doc, BUSINESS, paid_on=_date_label(datetime.utcnow()))
        return [(f"Receipt-{inv.number}.pdf", 'application/pdf', pdf)]
    except Exception:
        current_app.logger.exception('receipt PDF could not be made for %s', getattr(inv, 'number', '?'))
        return []


def paid(inv, amount):
    """Receipt to the customer, and a heads-up to the shop."""
    from utils.mailer import admin_base_url, admin_recipient
    doc = _doc(inv)
    app = current_app._get_current_object()
    if inv.email:
        attachments = receipt_attachments(inv, doc)
        _safe(
            _send, inv.email, f"Payment received: {inv.number}",
            'Thank you, your payment went through!',
            [f"We received ${amount:,.2f} for invoice {inv.number}."
             + (' Your invoice is now paid in full.' if doc['balance'] <= 0 else
                f" The remaining balance is ${doc['balance']:,.2f}.")]
            + (['Your receipt is attached as a PDF for your records.'] if attachments else []),
            details=[('Invoice', inv.number), ('Paid by', 'Card')],
            attachments=attachments,
        )
    _safe(
        _send, admin_recipient(app), f"Invoice paid by card: {inv.number} (${amount:,.2f})",
        'An invoice was paid online',
        [f"{inv.customer_name or 'A customer'} paid ${amount:,.2f} by card on invoice {inv.number}."
         + (' It is now paid in full.' if doc['balance'] <= 0 else f" Balance left: ${doc['balance']:,.2f}.")],
        button={'label': 'Open invoice', 'url': f"{admin_base_url(app)}/admin/invoices/{inv.id}"},
    )


_REMINDER_COPY = {
    1: ("A quick reminder about your invoice",
        'Just a friendly reminder that this invoice is still open. If you have already paid, thank you, and please ignore this note.'),
    2: ("Your invoice is still open",
        'This invoice is still waiting on a payment. You can pay by card with the button below, or reply and we will sort out Venmo, cash or a check.'),
    3: ("Checking in on your invoice",
        'It has been about a month, so we wanted to check in. Is there anything we can help with? Reply any time and we will work it out together.'),
}


def send_reminder(inv, stage):
    """A gentle reminder that an invoice is still open. Returns True if it was handed to the mailer."""
    from utils.invoice_pay import pay_url
    doc = _doc(inv)
    title, line = _REMINDER_COPY.get(stage, _REMINDER_COPY[1])
    first = (doc['attn'] or doc['name'] or '').split(' ')[0]
    return _safe(
        _send, inv.email, f"{title} ({inv.number})", f"Balance due, ${doc['balance']:,.2f}",
        [f"Hi{' ' + first if first else ''}! {line}"],
        button={'label': 'View & pay invoice', 'url': pay_url(inv)},
        details=[('Invoice', inv.number), ('Total', f"${doc['total']:,.2f}"), ('Balance due', f"${doc['balance']:,.2f}")],
    )
