"""Emails for company-sponsored group orders.

Employee: request received, removed (with refund note), items in production.
Shop owner: a company invoice was paid and orders are ready to make.

Every send goes through utils.mailer.send, which never raises, so an email
problem can never undo a payment or break a page. Outside tests the send runs in
a background thread so the page is not held up.
"""
from __future__ import annotations

from threading import Thread

from flask import current_app


def _send(to, subject, heading, paragraphs, *, button=None, details=None, note=None, attachments=None):
    from flask_mail import Message
    from routes.checkout import _render_email
    from utils.mailer import (admin_base_url, mail_configured, reply_to,
                              send as send_mail, sender)

    app = current_app._get_current_object()
    to = [t for t in ([to] if isinstance(to, str) else to) if t and '@' in t]
    if not to or not mail_configured(app):
        return False
    html = _render_email('email/sponsor_update.html', heading=heading, paragraphs=paragraphs,
                         button=button, details=details or [], note=note)
    plain_lines = [heading, ''] + paragraphs
    if details:
        plain_lines += [''] + [f'{k}: {v}' for k, v in details]
    if button:
        plain_lines += ['', f"{button['label']}: {button['url']}"]
    if note:
        plain_lines += ['', note]
    plain_lines += ['', 'Made with purpose, for you.', 'Purposefully Made KC']
    msg = Message(subject=subject, recipients=to, body='\n'.join(plain_lines), html=html,
                  sender=sender(app), reply_to=reply_to(app))
    for filename, content_type, data in (attachments or []):
        msg.attach(filename, content_type, data)

    def run():
        with app.app_context():
            send_mail(app, msg, description=f'sponsored order email: {subject}')

    if app.config.get('TESTING'):
        run()
    else:
        Thread(target=run, daemon=True).start()
    return True


def _items_text(sub):
    return '; '.join(
        f"{i.get('product_name') or 'Item'}, {i.get('color')}, size {i.get('size')}"
        for i in sub.items
    )


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        current_app.logger.exception('sponsored order email failed')
        return False


def request_received(sub):
    paid = (f' We received your payment of ${sub.overage_charge:,.2f} for your extra items'
            f'{" and shipping" if sub.overage_shipping else ""}.') if sub.overage_paid_at else ''
    from utils.group_sponsor import is_immediate_line
    now_items = any(is_immediate_line(l) for l in sub.items)
    covered_items = any(not is_immediate_line(l) for l in sub.items)
    if now_items and covered_items:
        timing = ("The items you paid for are being made now. The items your company covers are made "
                  "as soon as its invoice is paid, and we will email you when that happens.")
    elif now_items:
        timing = 'The items you paid for are being made now.'
    else:
        timing = ("Your items are made as soon as your company's invoice is paid, "
                  "and we will email you when that happens.")
    return _safe(
        _send, sub.email, f"You're in: {sub.collection.name}",
        f"Thanks, {sub.first_name}! Your request is in.",
        [f'Everything is set.{paid} {timing}'],
        details=[('Group', sub.collection.name), ('Items', _items_text(sub))],
        button={'label': 'Change a size or cancel', 'url': _edit_link(sub)},
        note='Need to fix something? Use the button until the invoice is created. '
             'If you cancel, any card payment you made is refunded.' if sub.overage_paid_at else
             'Need to fix something? Use the button until the invoice is created.',
    )


def _edit_link(sub):
    from utils.group_sponsor import edit_url
    return edit_url(sub)


def cancelled(sub, refunded):
    paras = ['Your request has been cancelled.']
    if refunded:
        paras.append(f'Your card payment of ${sub.overage_charge:,.2f} has been refunded. '
                     'It can take a few days to show up.')
    return _safe(_send, sub.email, f'Request cancelled: {sub.collection.name}',
                 f'Hi {sub.first_name},', paras, details=[('Group', sub.collection.name)])


def declined(sub, refunded):
    paras = ['Your organizer removed your request from the list.']
    if sub.rejection_reason:
        paras.append(f'Their note: {sub.rejection_reason}')
    if refunded:
        paras.append(f'Your card payment of ${sub.overage_charge:,.2f} has been refunded. '
                     'It can take a few days to show up.')
    paras.append('If you think this is a mistake, please talk to your organizer.')
    return _safe(_send, sub.email, f'Update on your request: {sub.collection.name}',
                 f'Hi {sub.first_name},', paras,
                 details=[('Group', sub.collection.name)])


def in_production(sub, order):
    c = sub.collection
    if order.fulfillment_method == 'shipping':
        how = 'We will ship it to the address you gave us.'
    else:
        where = (c.pickup_address or '').strip()
        how = ('Pickup: ' + where) if where else 'We will let you know when it is ready for pickup.'
    return _safe(
        _send, sub.email, f'Your order is going into production: {c.name}',
        f'{sub.first_name}, your order is in!',
        ["Your company's invoice has been paid, so we are making your items now.", how],
        details=[('Order number', order.order_number), ('Items', _items_text(sub))],
    )


def invoice_paid_to_shop(invoice, orders):
    from utils.mailer import admin_base_url, admin_recipient

    app = current_app._get_current_object()
    base = admin_base_url(app)
    return _safe(
        _send, admin_recipient(app),
        f'Company invoice paid: {invoice.collection.name} ({len(orders)} orders)',
        'A company invoice was paid',
        [f'{invoice.collection.name}: invoice {invoice.invoice_number} for ${invoice.total:,.2f} '
         f'was paid ({invoice.payment_method or "unknown"}). {len(orders)} '
         f'order{"s are" if len(orders) != 1 else " is"} now in your list, ready to make.'],
        button={'label': 'Open orders', 'url': f'{base}/admin/orders'},
        details=[(o.order_number, o.full_name) for o in orders[:30]],
    )


def invoice_paid_to_organizer(invoice, orders):
    """Receipt for the person who paid the company invoice, with the one-page PDF attached."""
    organizer = getattr(invoice.collection, 'created_by', None)
    to = getattr(organizer, 'email', None)
    if not to:
        return False
    attachments = []
    try:
        from utils.business_info import BUSINESS
        from utils.receipt_pdf import build_receipt_pdf
        from utils.receipts import _date_label, doc_from_company_invoice
        from datetime import datetime
        doc = doc_from_company_invoice(invoice)
        pdf = build_receipt_pdf(doc, BUSINESS, paid_on=_date_label(invoice.paid_at or datetime.utcnow()))
        attachments = [(f'Receipt-{invoice.invoice_number}.pdf', 'application/pdf', pdf)]
    except Exception:
        current_app.logger.exception('company receipt PDF failed for %s', invoice.invoice_number)
    first = (getattr(organizer, 'first_name', '') or '').strip()
    return _safe(
        _send, to, f'Payment received: {invoice.invoice_number}', 'Thank you, your payment was received',
        [f"Hi{' ' + first if first else ''}! We received ${invoice.total:,.2f} for invoice {invoice.invoice_number}. "
         f'The {len(orders)} order{"s" if len(orders) != 1 else ""} for {invoice.collection.name} '
         'are now going into production.']
        + (['Your receipt is attached as a PDF for your records.'] if attachments else []),
        details=[('Invoice', invoice.invoice_number), ('Total', f'${invoice.total:,.2f}')],
        attachments=attachments,
    )
