"""Public pay page for a hand-made invoice (see utils/invoice_pay.py).

  GET /pay/<token>          the invoice and a card form
  GET /pay/<token>/return   where Stripe sends the customer back; confirmed with Stripe
  GET /pay/<token>/qr.png   QR code that opens the pay page
"""
import stripe
from flask import Blueprint, Response, abort, current_app, redirect, render_template, request, url_for

from models import db
from utils.invoice_pay import (MIN_CARD_CENTS, apply_card_payment, balance_cents, doc_for,
                               invoice_for_token, pay_url, qr_png, receipt_pdf_bytes)

invoice_pay_bp = Blueprint('invoice_pay', __name__, url_prefix='/pay')


def _invoice_or_404(token):
    inv = invoice_for_token(token)
    if inv is None:
        abort(404)
    return inv


@invoice_pay_bp.route('/<token>')
def pay(token):
    inv = _invoice_or_404(token)
    doc = doc_for(inv)
    base = dict(inv=inv, doc=doc, token=token, client_secret=None, stripe_public_key=None,
                return_url=None, notice=None, thanks=request.args.get('paid') == '1')
    if doc['balance'] <= 0:
        return render_template('invoice_pay/pay.html', **base)

    public_key = current_app.config.get('STRIPE_PUBLIC_KEY')
    cents = balance_cents(inv)
    if not public_key or not stripe.api_key:
        base['notice'] = 'Online payment is not available right now. Please contact us to pay this invoice.'
        return render_template('invoice_pay/pay.html', **base)
    if cents < MIN_CARD_CENTS:
        base['notice'] = 'This balance is too small to pay by card. Please contact us to settle it.'
        return render_template('invoice_pay/pay.html', **base)

    try:
        intent = None
        if inv.payment_intent_id:
            old = stripe.PaymentIntent.retrieve(inv.payment_intent_id)
            if old.status in ('requires_payment_method', 'requires_confirmation') and old.amount == cents:
                intent = old
        if intent is None:
            intent = stripe.PaymentIntent.create(
                amount=cents, currency='usd', automatic_payment_methods={'enabled': True},
                description=f'Invoice {inv.number}',
                receipt_email=inv.email or None,
                metadata={'manual_invoice_id': str(inv.id), 'invoice_number': inv.number},
            )
            inv.payment_intent_id = intent.id
            db.session.commit()
    except stripe.error.StripeError:
        current_app.logger.exception('invoice %s payment intent failed', inv.number)
        base['notice'] = 'We could not start the payment. Please try again in a moment.'
        return render_template('invoice_pay/pay.html', **base)

    base.update(client_secret=intent.client_secret, stripe_public_key=public_key,
                return_url=url_for('invoice_pay.pay_return', token=token, _external=True))
    return render_template('invoice_pay/pay.html', **base)


@invoice_pay_bp.route('/<token>/return')
def pay_return(token):
    """Stripe sends the customer back here; confirm with Stripe, not the URL."""
    inv = _invoice_or_404(token)
    if inv.payment_intent_id:
        try:
            intent = stripe.PaymentIntent.retrieve(inv.payment_intent_id)
            if intent.status == 'succeeded':
                apply_card_payment(inv, intent.id, intent.amount)
        except stripe.error.StripeError:
            current_app.logger.exception('invoice %s return check failed', inv.number)
    return redirect(url_for('invoice_pay.pay', token=token, paid='1'))


@invoice_pay_bp.route('/<token>/receipt.pdf')
def receipt_pdf(token):
    """The one-page PDF receipt for a payment that was made. Only the private link opens it."""
    inv = _invoice_or_404(token)
    if doc_for(inv)['paid'] <= 0:
        abort(404)
    return Response(receipt_pdf_bytes(inv), mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="Receipt-{inv.number}.pdf"',
                             'Cache-Control': 'private, no-store'})


@invoice_pay_bp.route('/<token>/qr.png')
def qr(token):
    inv = _invoice_or_404(token)
    return Response(qr_png(pay_url(inv)), mimetype='image/png',
                    headers={'Cache-Control': 'private, max-age=3600'})
