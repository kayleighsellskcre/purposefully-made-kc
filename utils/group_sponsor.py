"""Company-sponsored group orders: a company covers N items per employee.

Employees shop the normal group storefront and fill the normal cart. At
checkout they send a request. The company covers the first N items (up to an
optional per-item price cap); anything extra, plus tax on it and shipping if
they want it shipped, the employee pays by card right then. If the organizer
later removes the request, that card payment is refunded (unless those items are already being made). Requests are counted
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
    try:
        create_immediate_order(sub)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('sponsor request %s: paid items could not be started', sub.id)
    return True


def is_immediate_line(line) -> bool:
    """A unit the employee pays for entirely: it can be made now, without the company."""
    return float(line.get('employee_part') or 0) > 0 and float(line.get('company_part') or 0) == 0


def _build_order(sub, lines, *, shipping, tax, payment_method, paid_at, rid):
    from models import Order, db
    from routes.checkout import build_order_items
    from utils.order_costs import default_due_date

    subtotal = round(sum(float(l.get('unit_price') or 0) for l in lines), 2)
    total = round(subtotal + shipping + tax, 2)
    order = Order(
        collection_id=sub.collection_id, email=sub.email, first_name=sub.first_name,
        last_name=sub.last_name, phone=sub.phone,
        fulfillment_method=sub.fulfillment_method or 'pickup',
        shipping_recipient=sub.shipping_recipient, shipping_street=sub.shipping_street,
        shipping_city=sub.shipping_city, shipping_state=sub.shipping_state,
        shipping_zip=sub.shipping_zip,
        subtotal=subtotal, shipping_cost=shipping, tax=tax, total=total,
        payment_method=payment_method, payment_status='paid', amount_paid=total,
        paid_at=paid_at, status='paid', production_stage='order_received',
        due_date=default_due_date(),
    )
    db.session.add(order)
    db.session.flush()
    if not build_order_items(order, lines, rid=rid):
        db.session.rollback()
        return None
    return order


def create_immediate_order(sub):
    """Start production now on the items the employee paid for in full.

    Their shipping and the tax on those items ride with this order. Items the company
    covers (even partly) wait for the company's invoice and keep the employee's name.
    """
    from models import db

    if sub.immediate_order_id:
        return None
    lines = [l for l in sub.items if is_immediate_line(l)]
    if not lines:
        return None
    subtotal = round(sum(float(l.get('unit_price') or 0) for l in lines), 2)
    order = _build_order(
        sub, lines, shipping=sub.overage_shipping or 0.0, tax=tax_for(sub.collection, subtotal),
        payment_method='stripe', paid_at=sub.overage_paid_at or datetime.utcnow(),
        rid=f'sponsor-now-{sub.id}',
    )
    if order is None:
        return None
    sub.immediate_order_id = order.id
    db.session.commit()
    from routes.checkout import queue_order_confirmation_email
    queue_order_confirmation_email(order.id)       # receipt to the employee, alert to the shop
    return order


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


def create_invoice(collection, close=True):
    """Invoice every request that is not on an invoice yet. Returns (invoice, error).

    close=True also stops new requests (the usual "we are done" step). close=False
    bills what has come in so far and keeps the link open: requests that arrive later
    go on the next invoice, so a long-running group can be billed in batches.
    """
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
    if close:
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
            company_tax = tax_for(sub.collection, sub.sponsored_total)
            if sub.immediate_order_id:
                # The employee's own paid items are already being made; this order is the rest.
                lines = [l for l in lines if not is_immediate_line(l)]
                made_now = sum(float(l.get('unit_price') or 0) for l in sub.items if is_immediate_line(l))
                left_over_tax = max(0.0, round((sub.overage_tax or 0) - tax_for(sub.collection, made_now), 2))
                shipping, tax = 0.0, round(company_tax + left_over_tax, 2)
            else:
                shipping, tax = sub.overage_shipping or 0.0, round(company_tax + (sub.overage_tax or 0), 2)
            if not lines:
                sub.status = 'converted'
                db.session.commit()
                continue
            order = _build_order(sub, lines, shipping=shipping, tax=tax,
                                 payment_method='company_invoice', paid_at=invoice.paid_at,
                                 rid=f'sponsor-{sub.id}')
            if order is None:
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


# ── Employee self-service: change a size or cancel until the invoice is made ─

def _edit_serializer():
    from flask import current_app
    from itsdangerous import URLSafeSerializer
    return URLSafeSerializer(current_app.secret_key, salt='sponsor-edit')


def edit_url(sub):
    """Private link in the employee's email. Anyone holding it can edit that one request."""
    from flask import current_app
    from utils.mailer import admin_base_url
    token = _edit_serializer().dumps(sub.id)
    return f"{admin_base_url(current_app)}/c/{sub.collection.slug}/sponsored/my-request/{token}"


def sub_from_token(collection, token):
    from itsdangerous import BadSignature
    from models import SponsorSubmission, db
    try:
        sub_id = _edit_serializer().loads(token)
    except BadSignature:
        return None
    sub = db.session.get(SponsorSubmission, sub_id)
    return sub if sub and sub.collection_id == collection.id else None


def is_editable(sub) -> bool:
    # Until it is on an invoice, and not once their own paid items are being made.
    return sub.status in ('approved', 'pending') and not sub.immediate_order_id


def _line_can_resize(line) -> bool:
    """Only simple front-logo items: the print size is recomputed from the new size.

    Anything with back artwork, a name or number, or a back-only placement needs
    a person to redo it, so those are left alone.
    """
    meta = line.get('back_design_meta')
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = None
    personalised = isinstance(meta, dict) and (meta.get('name') or meta.get('number'))
    return not (line.get('back_design_url') or personalised or line.get('placement') == 'center_back')


def sizes_for(line):
    from models import Product, db
    from utils.json_fields import parse_json_list
    from utils.sizes import sort_sizes
    product = db.session.get(Product, int(line.get('product_id') or 0))
    return sort_sizes(parse_json_list(product.available_sizes)) if product else []


def change_sizes(sub, new_sizes):
    """Apply {line index: size}. Returns (ok, error). Never changes what anyone owes."""
    from models import Design, Product, db
    from utils.pricing import price_cart_item
    from utils.print_sizes import build_item_production

    if not is_editable(sub):
        return False, 'This request can no longer be changed.'
    lines = sub.items
    changed = False
    for idx, size in new_sizes.items():
        if not (0 <= idx < len(lines)) or not size or size == lines[idx].get('size'):
            continue
        line = lines[idx]
        product = db.session.get(Product, int(line.get('product_id') or 0))
        if not product or size not in sizes_for(line):
            return False, 'Please choose a size from the list.'
        if not _line_can_resize(line):
            return False, ('That item has custom back artwork, so its size cannot be changed here. '
                           'Please cancel your request and send a new one.')
        design = db.session.get(Design, int(line['design_id'])) if line.get('design_id') else None
        old_front = ((line.get('transfer_production') or {}).get('front') or {})
        line['size'] = size
        production = build_item_production(
            product=product, size=size, color=line.get('color'), placement=line.get('placement'),
            quantity=1, design_name=old_front.get('design_name') or (design.title if design else None),
            design_id=line.get('design_id'),
            aspect_w=float(design.width) if design and design.width else None,
            aspect_h=float(design.height) if design and design.height else None,
            has_front=bool(line.get('design_id') or line.get('design_url')),
            customer_name=((line.get('transfer_production') or {}).get('customer_name')),
        )
        front = (production or {}).get('front') or {}
        line['transfer_production'] = production
        line['print_width'] = front.get('width')
        line['print_height'] = front.get('height')
        if abs(price_cart_item(line, product, design=design) - float(line.get('unit_price') or 0)) > 0.005:
            return False, ('That size is priced differently, so it cannot be swapped here. '
                           'Please cancel your request and send a new one.')
        changed = True
    if changed:
        sub.items_json = json.dumps(lines, default=str)
        db.session.commit()
    return True, None


def cancel_request(sub):
    """The employee cancels their own request. Returns (ok, error)."""
    from models import db
    if not is_editable(sub):
        return False, 'This request can no longer be cancelled here.'
    was_refunded = bool(sub.overage_refunded_at)
    ok, error = refund_overage(sub)
    if not ok:
        return False, error
    sub.status = 'rejected'
    sub.rejection_reason = 'Cancelled by the employee'
    db.session.commit()
    from utils import sponsor_emails
    sponsor_emails.cancelled(sub, refunded=bool(sub.overage_refunded_at) and not was_refunded)
    return True, None


# ── What the company and the employees are paying ───────────────────────────

def spend_summary(rows):
    """Plain totals for the organizer's dashboard."""
    live = [r for r in rows if r.status != 'rejected']
    unbilled = [r for r in live if r.status in ('approved', 'pending')]
    billed = [r for r in live if r.status in ('invoiced', 'converted')]
    paid_extra = [r for r in rows if r.overage_paid_at and not r.overage_refunded_at]
    return {
        'people': len(live),
        'items': sum(r.item_count for r in live),
        'company_unbilled': round(sum(r.sponsored_total or 0 for r in unbilled), 2),
        'company_billed': round(sum(r.sponsored_total or 0 for r in billed), 2),
        'employees_paid': round(sum(r.overage_charge for r in paid_extra), 2),
    }


def _csv_cell(value):
    """Spreadsheet-safe text: a leading = + - @ would be run as a formula."""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@') else text


def requests_csv(collection) -> str:
    """One row per item: who, what, size, who pays how much, and where it goes."""
    import csv
    import io

    rows, _counts = submission_summary(collection)
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(['Name', 'Email', 'Phone', 'Item', 'Color', 'Size',
                  'Company pays', 'Employee pays', 'Status', 'How they get it'])
    labels = {'approved': 'Counted', 'pending': 'Counted', 'invoiced': 'On invoice',
              'converted': 'In production', 'rejected': 'Removed'}
    for r in rows:
        how = 'Ship' if r.fulfillment_method == 'shipping' else 'Pickup'
        for line in r.items:
            out.writerow([_csv_cell(v) for v in (
                r.full_name, r.email, r.phone, line.get('product_name') or 'Item',
                line.get('color'), line.get('size'),
                f"{float(line.get('company_part') or 0):.2f}",
                f"{float(line.get('employee_part') or 0):.2f}",
                labels.get(r.status, r.status), how)])
    return buf.getvalue()
