"""Company-sponsored group orders: a company covers N items per employee.

Employees shop the normal group storefront and fill the normal cart. At
checkout they send a request. The company covers the first N items (up to an
optional per-item price cap); anything extra, plus tax on it and shipping if
they want it shipped, the employee pays by card right then. If the organizer
later removes the request, that card payment is refunded. Requests are counted
automatically from the group order's settings (items per person, price limit): there
is no approval step. The organizer only
requests and pays one invoice. Nothing is produced until that invoice is paid:
a SponsorSubmission is only a saved request, and the real Order rows are built
by convert_invoice_to_orders() once the money is in.

Nothing here changes the each-pays or organizer-pays flows.
"""
from __future__ import annotations

import json
from datetime import datetime

COMPANY_SPONSORED = 'company_sponsored'
ITEMS_MAX = 20


def is_company_sponsored(collection) -> bool:
    return bool(collection) and getattr(collection, 'payment_mode', None) == COMPANY_SPONSORED


def apply_sponsor_settings_from_form(collection):
    """Save the sponsor fields from the current request. Returns (ok, error)."""
    from flask import request

    if not is_company_sponsored(collection):
        return True, None
    form = request.form
    if 'sponsor_items_per_person' in form:
        raw = (form.get('sponsor_items_per_person') or '').strip()
        try:
            count = int(raw)
        except ValueError:
            return False, 'Please enter how many items the company covers per person (a whole number).'
        if count < 1 or count > ITEMS_MAX:
            return False, f'The company can cover between 1 and {ITEMS_MAX} items per person.'
        collection.sponsor_items_per_person = count
    if 'sponsor_budget_per_person' in form:
        raw = (form.get('sponsor_budget_per_person') or '').strip().lstrip('$')
        if not raw:
            collection.sponsor_budget_per_person = None
        else:
            try:
                amount = float(raw)
            except ValueError:
                return False, 'Please enter the most the company will pay for one item as a dollar amount.'
            if amount <= 0:
                return False, 'The most the company will pay for one item must be more than $0.'
            collection.sponsor_budget_per_person = round(amount, 2)
    if 'sponsor_message' in form:
        collection.sponsor_message = (form.get('sponsor_message') or '').strip()[:300] or None
    return True, None


def sponsor_cart_problem(collection, cart):
    """Why this cart cannot be sent as a sponsored request, or None."""
    lines = [i for i in cart or [] if isinstance(i, dict)]
    if not lines:
        return 'Your cart is empty.'
    if any((i.get('collection_id') or None) != collection.id for i in lines):
        return ('Your cart has items from somewhere else. This company-sponsored order '
                'can only include items from this page. Please remove the others.')
    return None


def split_cart(collection, cart):
    """Split a cart into what the company covers and what the employee pays.

    One line per unit. The first N units (cart order) are covered, each up to the
    per-item price cap; the employee pays the rest of any unit above the cap and
    all of every unit past N. Returns (lines, company_total, employee_total).
    """
    allowed = collection.sponsor_items_per_person or 1
    cap = collection.sponsor_budget_per_person
    lines, covered = [], 0
    for item in cart:
        if not isinstance(item, dict):
            continue
        unit = round(float(item.get('unit_price') or 0), 2)
        for _ in range(max(1, int(item.get('quantity') or 1))):
            line = dict(item)
            line['quantity'] = 1
            company = 0.0
            if covered < allowed:
                covered += 1
                company = min(unit, cap) if cap is not None else unit
            line['company_part'] = round(company, 2)
            line['employee_part'] = round(unit - company, 2)
            lines.append(line)
    return (lines,
            round(sum(l['company_part'] for l in lines), 2),
            round(sum(l['employee_part'] for l in lines), 2))


def employee_charge(collection, overage_total, method):
    """What the employee pays by card: (tax, shipping, total). Shipping is always theirs."""
    from flask import current_app
    shipping = float(current_app.config.get('SHIPPING_FLAT_RATE', 11.0)) if method == 'shipping' else 0.0
    tax = tax_for(collection, overage_total)
    return tax, round(shipping, 2), round(overage_total + tax + shipping, 2)


def finalize_overage_payment(sub, intent_id, amount_cents):
    """The employee's card payment went through: the request now waits for the organizer.

    Safe to call twice (the return page and the webhook both do). Returns True once paid.
    """
    from flask import current_app
    from models import db

    if sub.status != 'awaiting_payment':
        return bool(sub.overage_paid_at)
    if sub.overage_payment_intent_id != intent_id or amount_cents != int(round(sub.overage_charge * 100)):
        current_app.logger.error('sponsor request %s paid with a mismatched intent or amount', sub.id)
        return False
    sub.status = 'approved'          # counted automatically: no approval step
    sub.overage_paid_at = datetime.utcnow()
    db.session.commit()
    from utils import sponsor_emails
    sponsor_emails.request_received(sub)
    return True


def refund_overage(sub):
    """Give the employee their card payment back. Returns (ok, error)."""
    import stripe
    from flask import current_app
    from models import db

    if not sub.overage_paid_at or sub.overage_refunded_at:
        return True, None
    try:
        stripe.Refund.create(payment_intent=sub.overage_payment_intent_id,
                             idempotency_key=f'sponsor-refund-{sub.id}')
    except stripe.error.StripeError:
        current_app.logger.exception('sponsor request %s refund failed', sub.id)
        return False, ('We could not send the refund through Stripe. Please try again, '
                       'or refund it from your Stripe dashboard.')
    sub.overage_refunded_at = datetime.utcnow()
    db.session.commit()
    return True, None


def tax_for(collection, amount) -> float:
    from flask import current_app
    rate = float(current_app.config.get('KS_SALES_TAX_RATE', 0.095))
    return round(float(amount or 0) * rate, 2)


def submission_summary(collection):
    from models import SponsorSubmission

    rows = (SponsorSubmission.query.filter_by(collection_id=collection.id)
            .filter(SponsorSubmission.status != 'awaiting_payment')
            .order_by(SponsorSubmission.created_at, SponsorSubmission.id).all())
    counts = {s: 0 for s in ('pending', 'approved', 'invoiced', 'converted', 'rejected')}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return rows, counts


def create_invoice(collection):
    """Invoice every request and lock the link. Returns (invoice, error)."""
    from models import CompanyInvoice, SponsorSubmission, db

    rows = SponsorSubmission.query.filter_by(collection_id=collection.id).all()
    approved = [r for r in rows if r.status in ('approved', 'pending')]   # 'pending' = older rows
    if not approved:
        return None, 'No requests have come in yet, so there is nothing to invoice.'

    subtotal = round(sum(r.sponsored_total or 0 for r in approved), 2)
    tax = round(sum(tax_for(collection, r.sponsored_total) for r in approved), 2)
    invoice = CompanyInvoice(
        invoice_number=CompanyInvoice.generate_invoice_number(),
        collection_id=collection.id,
        submission_ids_json=json.dumps([r.id for r in approved]),
        subtotal=subtotal,
        tax=tax,
        total=round(subtotal + tax, 2),
        payment_status='unpaid',
    )
    for r in approved:
        r.status = 'invoiced'
    collection.sponsor_submissions_locked = True
    db.session.add(invoice)
    db.session.commit()
    return invoice, None


def mark_invoice_paid(invoice, method, payment_intent_id=None):
    """Record payment and build the production orders. Safe to call twice."""
    from models import db

    if invoice.payment_status != 'paid':
        invoice.payment_status = 'paid'
        invoice.payment_method = method
        invoice.paid_at = datetime.utcnow()
        if payment_intent_id:
            invoice.payment_intent_id = payment_intent_id
        db.session.commit()
    return convert_invoice_to_orders(invoice)


def convert_invoice_to_orders(invoice):
    """Turn each invoiced request into a real, paid Order. Returns the orders made.

    Only runs for a paid invoice; a request is converted once.
    """
    from flask import current_app
    from models import Order, SponsorSubmission, db
    from routes.checkout import build_order_items
    from utils.order_costs import default_due_date

    if invoice.payment_status != 'paid':
        return []
    from utils import sponsor_emails
    made = []
    for sub_id in invoice.submission_ids:
        sub = db.session.get(SponsorSubmission, sub_id)
        if not sub or sub.status != 'invoiced' or sub.order_id:
            continue
        try:
            lines = sub.items
            subtotal = round(sum(float(l.get('unit_price') or 0) for l in lines), 2)
            shipping = sub.overage_shipping or 0.0
            tax = round(tax_for(sub.collection, sub.sponsored_total) + (sub.overage_tax or 0), 2)
            total = round(subtotal + shipping + tax, 2)
            order = Order(
                collection_id=invoice.collection_id,
                email=sub.email,
                first_name=sub.first_name,
                last_name=sub.last_name,
                phone=sub.phone,
                fulfillment_method=sub.fulfillment_method or 'pickup',
                shipping_recipient=sub.shipping_recipient,
                shipping_street=sub.shipping_street,
                shipping_city=sub.shipping_city,
                shipping_state=sub.shipping_state,
                shipping_zip=sub.shipping_zip,
                subtotal=subtotal,
                shipping_cost=shipping,
                tax=tax,
                total=total,
                payment_method='company_invoice',
                payment_status='paid',
                amount_paid=total,
                paid_at=invoice.paid_at,
                status='paid',
                production_stage='order_received',
                due_date=default_due_date(),
            )
            db.session.add(order)
            db.session.flush()
            if not build_order_items(order, lines, rid=f'sponsor-{sub.id}'):
                db.session.rollback()
                current_app.logger.error('sponsor submission %s had no usable items', sub.id)
                continue
            sub.status = 'converted'
            sub.order_id = order.id
            db.session.commit()
            made.append(order)
            sponsor_emails.in_production(sub, order)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('sponsor submission %s could not become an order', sub_id)
    if made:
        sponsor_emails.invoice_paid_to_shop(invoice, made)
    return made
