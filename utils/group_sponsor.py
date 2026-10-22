"""Company-sponsored group orders: a company covers N items per employee.

Employees shop the normal group storefront and fill the normal cart. At
checkout they send a request instead of paying. The organizer approves
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
    """Why this cart cannot be sent as a sponsored request, or None.

    Phase 1 covers whole items only: the cart must fit inside the allowance, so
    nothing is ever left for the employee to pay.
    """
    lines = [i for i in cart or [] if isinstance(i, dict)]
    if not lines:
        return 'Your cart is empty.'
    if any((i.get('collection_id') or None) != collection.id for i in lines):
        return ('Your cart has items from somewhere else. This company-sponsored order '
                'can only include items from this page. Please remove the others.')
    allowed = collection.sponsor_items_per_person or 1
    qty = sum(max(1, int(i.get('quantity') or 1)) for i in lines)
    if qty > allowed:
        noun = 'item' if allowed == 1 else 'items'
        return (f'Your company covers {allowed} {noun} per person and you have {qty} in your cart. '
                f'Please remove {qty - allowed} to continue.')
    cap = collection.sponsor_budget_per_person
    if cap is not None:
        over = [i for i in lines if float(i.get('unit_price') or 0) > cap + 0.005]
        if over:
            return (f'Your company covers up to ${cap:,.2f} per item. '
                    'Please choose a less expensive item or a different print option.')
    return None


def sponsored_total(cart) -> float:
    return round(sum(
        max(1, int(i.get('quantity') or 1)) * float(i.get('unit_price') or 0)
        for i in cart if isinstance(i, dict)
    ), 2)


def tax_for(collection, amount) -> float:
    from flask import current_app
    rate = float(current_app.config.get('KS_SALES_TAX_RATE', 0.095))
    return round(float(amount or 0) * rate, 2)


def submission_summary(collection):
    from models import SponsorSubmission

    rows = (SponsorSubmission.query.filter_by(collection_id=collection.id)
            .order_by(SponsorSubmission.created_at, SponsorSubmission.id).all())
    counts = {s: 0 for s in ('pending', 'approved', 'invoiced', 'converted', 'rejected')}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return rows, counts


def create_invoice(collection):
    """Invoice every approved request and lock the link. Returns (invoice, error)."""
    from models import CompanyInvoice, SponsorSubmission, db

    rows = SponsorSubmission.query.filter_by(collection_id=collection.id).all()
    pending = [r for r in rows if r.status == 'pending']
    approved = [r for r in rows if r.status == 'approved']
    if pending:
        n = len(pending)
        return None, (f'{n} request{"s are" if n != 1 else " is"} still waiting for your '
                      'answer. Approve or decline each one first.')
    if not approved:
        return None, 'There are no approved requests to invoice yet.'

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
    made = []
    for sub_id in invoice.submission_ids:
        sub = db.session.get(SponsorSubmission, sub_id)
        if not sub or sub.status != 'invoiced' or sub.order_id:
            continue
        try:
            tax = tax_for(sub.collection, sub.sponsored_total)
            total = round((sub.sponsored_total or 0) + tax, 2)
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
                subtotal=sub.sponsored_total or 0,
                shipping_cost=0.0,
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
            if not build_order_items(order, sub.items, rid=f'sponsor-{sub.id}'):
                db.session.rollback()
                current_app.logger.error('sponsor submission %s had no usable items', sub.id)
                continue
            sub.status = 'converted'
            sub.order_id = order.id
            db.session.commit()
            made.append(order)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('sponsor submission %s could not become an order', sub_id)
    return made
