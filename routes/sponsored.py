"""Company-sponsored group orders: employee requests, organizer dashboard, invoice.

URL map (all under /c/<slug>):
  GET/POST /sponsored/checkout             employee reviews cart and sends a request
  GET      /sponsored/confirm              "request received" page
  GET      /manage-sponsored               organizer dashboard
  POST     /manage-sponsored/review        approve / decline one request
  POST     /manage-sponsored/invoice       lock the link and create the invoice
  GET      /manage-sponsored/invoice/<id>  printable invoice
  GET      /manage-sponsored/invoice/<id>/pay     pay online (card)
  GET      /manage-sponsored/invoice/<id>/return  where the card form sends them back
  POST     /manage-sponsored/invoice/<id>/mark-paid  admin only: paid by check/cash/etc.

Nothing is produced until the invoice is paid (see utils/group_sponsor.py).
"""
import stripe
from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required

from models import CompanyInvoice, Collection, SponsorSubmission, db
from utils.group_sponsor import (
    create_invoice, is_company_sponsored, mark_invoice_paid, sponsor_cart_problem,
    sponsored_total, submission_summary,
)

sponsored_bp = Blueprint('sponsored', __name__, url_prefix='/c')

MANUAL_METHODS = ('check', 'cash', 'venmo', 'paypal', 'other')


def _sponsored_collection(slug):
    collection = Collection.query.filter_by(slug=slug, is_active=True).first_or_404()
    if not is_company_sponsored(collection):
        abort(404)
    return collection


def _organizer_collection(slug):
    from utils.group_orders import user_can_manage_collection
    collection = _sponsored_collection(slug)
    if not user_can_manage_collection(collection):
        abort(403)
    return collection


def _clean(value, length):
    return ' '.join((value or '').split())[:length]


# ── Employee ────────────────────────────────────────────────────────────────

@sponsored_bp.route('/<slug>/sponsored/checkout', methods=['GET', 'POST'])
def checkout(slug):
    from routes.checkout import reprice_cart
    from utils.cart_store import get_cart, save_cart
    from utils.group_orders import access_code_required, ordering_blocked

    collection = _sponsored_collection(slug)
    if access_code_required(collection):
        return redirect(url_for('collection.password', slug=slug))

    blocked = ordering_blocked(collection)
    if not blocked and collection.sponsor_submissions_locked:
        blocked = 'This group order is no longer taking requests.'
    if blocked:
        flash(blocked, 'error')
        return redirect(url_for('collection.view', slug=slug))

    cart = get_cart()
    problem = sponsor_cart_problem(collection, cart)
    if problem:
        flash(problem, 'error')
        return redirect(url_for('cart.index') if cart else url_for('collection.view', slug=slug))
    reprice_cart(cart)
    problem = sponsor_cart_problem(collection, cart)  # a corrected price may break the cap
    if problem:
        flash(problem, 'error')
        return redirect(url_for('cart.index'))

    if request.method == 'GET':
        return render_template('sponsored/checkout.html', collection=collection, cart=cart,
                               form={}, error=None)

    form = request.form
    if (form.get('website') or '').strip():          # honeypot
        return redirect(url_for('collection.view', slug=slug))
    first, last = _clean(form.get('first_name'), 80), _clean(form.get('last_name'), 80)
    email = (form.get('email') or '').strip().lower()[:120]
    phone = _clean(form.get('phone'), 20)
    method = 'shipping' if form.get('fulfillment_method') == 'shipping' else 'pickup'

    error = None
    if not first or not last:
        error = 'Please enter your first and last name.'
    elif '@' not in email or '.' not in email.rsplit('@', 1)[-1]:
        error = 'Please enter an email address so we can reach you.'
    elif method == 'shipping' and not collection.shipping_enabled:
        error = 'This group order is pickup only.'
    elif method == 'shipping' and not all(_clean(form.get(k), 200) for k in ('street', 'city', 'state', 'zip')):
        error = 'Please fill in your full shipping address.'
    elif SponsorSubmission.query.filter(
        SponsorSubmission.collection_id == collection.id,
        SponsorSubmission.email == email,
        SponsorSubmission.status.in_(('pending', 'approved', 'invoiced', 'converted')),
    ).first():
        error = 'We already have a request from this email address. Each person can send one.'
    if error:
        return render_template('sponsored/checkout.html', collection=collection, cart=cart,
                               form=form, error=error), 400

    import json
    sub = SponsorSubmission(
        collection_id=collection.id,
        first_name=first, last_name=last, email=email, phone=phone,
        fulfillment_method=method,
        shipping_recipient=f'{first} {last}' if method == 'shipping' else None,
        shipping_street=_clean(form.get('street'), 200) if method == 'shipping' else None,
        shipping_city=_clean(form.get('city'), 100) if method == 'shipping' else None,
        shipping_state=_clean(form.get('state'), 50) if method == 'shipping' else None,
        shipping_zip=_clean(form.get('zip'), 20) if method == 'shipping' else None,
        items_json=json.dumps(cart, default=str),
        sponsored_total=sponsored_total(cart),
        status='pending',
    )
    db.session.add(sub)
    db.session.commit()

    save_cart([])
    session.pop('collection_id', None)
    session[f'sponsor_request_{collection.id}'] = sub.id
    session.modified = True
    return redirect(url_for('sponsored.confirm', slug=slug))


@sponsored_bp.route('/<slug>/sponsored/confirm')
def confirm(slug):
    collection = _sponsored_collection(slug)
    sub = db.session.get(SponsorSubmission, session.get(f'sponsor_request_{collection.id}') or 0)
    if not sub or sub.collection_id != collection.id:
        return redirect(url_for('collection.view', slug=slug))
    return render_template('sponsored/confirm.html', collection=collection, sub=sub)


# ── Organizer ───────────────────────────────────────────────────────────────

@sponsored_bp.route('/<slug>/manage-sponsored')
@login_required
def manage(slug):
    collection = _organizer_collection(slug)
    rows, counts = submission_summary(collection)
    invoices = (CompanyInvoice.query.filter_by(collection_id=collection.id)
                .order_by(CompanyInvoice.created_at.desc()).all())
    return render_template(
        'sponsored/manage.html', collection=collection, submissions=rows, counts=counts,
        invoices=invoices, is_admin=bool(getattr(current_user, 'is_admin', False)),
        manual_methods=MANUAL_METHODS,
        stripe_ready=bool(current_app.config.get('STRIPE_PUBLIC_KEY') and stripe.api_key),
    )


@sponsored_bp.route('/<slug>/manage-sponsored/review', methods=['POST'])
@login_required
def review(slug):
    collection = _organizer_collection(slug)
    sub = SponsorSubmission.query.filter_by(
        id=request.form.get('submission_id', type=int), collection_id=collection.id,
    ).first_or_404()
    action = request.form.get('action')
    if sub.status not in ('pending', 'approved', 'rejected'):
        flash('That request is already on an invoice, so it cannot change.', 'error')
    elif action == 'approve':
        sub.status = 'approved'
        sub.rejection_reason = None
        db.session.commit()
        flash(f'Approved {sub.full_name}.', 'success')
    elif action == 'reject':
        sub.status = 'rejected'
        sub.rejection_reason = _clean(request.form.get('reason'), 500) or None
        db.session.commit()
        flash(f'Declined {sub.full_name}.', 'success')
    return redirect(url_for('sponsored.manage', slug=slug))


@sponsored_bp.route('/<slug>/manage-sponsored/invoice', methods=['POST'])
@login_required
def make_invoice(slug):
    collection = _organizer_collection(slug)
    invoice, error = create_invoice(collection)
    if error:
        flash(error, 'error')
    else:
        flash(f'Invoice {invoice.invoice_number} created for ${invoice.total:,.2f}.', 'success')
    return redirect(url_for('sponsored.manage', slug=slug))


def _invoice_for(collection, invoice_id):
    return CompanyInvoice.query.filter_by(id=invoice_id, collection_id=collection.id).first_or_404()


@sponsored_bp.route('/<slug>/manage-sponsored/invoice/<int:invoice_id>')
@login_required
def invoice_view(slug, invoice_id):
    collection = _organizer_collection(slug)
    invoice = _invoice_for(collection, invoice_id)
    subs = [db.session.get(SponsorSubmission, i) for i in invoice.submission_ids]
    return render_template('sponsored/invoice.html', collection=collection, invoice=invoice,
                           submissions=[s for s in subs if s])


@sponsored_bp.route('/<slug>/manage-sponsored/invoice/<int:invoice_id>/pay')
@login_required
def invoice_pay(slug, invoice_id):
    collection = _organizer_collection(slug)
    invoice = _invoice_for(collection, invoice_id)
    if invoice.payment_status != 'unpaid':
        return redirect(url_for('sponsored.manage', slug=slug))
    public_key = current_app.config.get('STRIPE_PUBLIC_KEY')
    if not public_key or not stripe.api_key:
        flash('Online payment is not available right now. Please call us to pay this invoice.', 'error')
        return redirect(url_for('sponsored.manage', slug=slug))

    amount = int(round(invoice.total * 100))
    try:
        intent = None
        if invoice.payment_intent_id:
            old = stripe.PaymentIntent.retrieve(invoice.payment_intent_id)
            if old.status in ('requires_payment_method', 'requires_confirmation') and old.amount == amount:
                intent = old
        if intent is None:
            intent = stripe.PaymentIntent.create(
                amount=amount, currency='usd',
                automatic_payment_methods={'enabled': True},
                description=f'Invoice {invoice.invoice_number}',
                metadata={'invoice_number': invoice.invoice_number,
                          'company_invoice_id': str(invoice.id),
                          'collection_id': str(collection.id)},
            )
            invoice.payment_intent_id = intent.id
            db.session.commit()
    except stripe.error.StripeError:
        current_app.logger.exception('invoice %s payment intent failed', invoice.invoice_number)
        flash('We could not start the payment. Please try again or call us.', 'error')
        return redirect(url_for('sponsored.manage', slug=slug))

    return render_template(
        'sponsored/pay.html', collection=collection, invoice=invoice,
        client_secret=intent.client_secret, stripe_public_key=public_key,
        return_url=url_for('sponsored.invoice_return', slug=slug, invoice_id=invoice.id, _external=True),
    )


@sponsored_bp.route('/<slug>/manage-sponsored/invoice/<int:invoice_id>/return')
@login_required
def invoice_return(slug, invoice_id):
    """Stripe sends the organizer back here; confirm with Stripe, not the URL."""
    collection = _organizer_collection(slug)
    invoice = _invoice_for(collection, invoice_id)
    if invoice.payment_status != 'paid' and invoice.payment_intent_id:
        try:
            intent = stripe.PaymentIntent.retrieve(invoice.payment_intent_id)
            if intent.status == 'succeeded' and intent.amount == int(round(invoice.total * 100)):
                mark_invoice_paid(invoice, 'stripe', intent.id)
        except stripe.error.StripeError:
            current_app.logger.exception('invoice %s return check failed', invoice.invoice_number)
    if invoice.payment_status == 'paid':
        flash('Thank you! The invoice is paid and your items are going into production.', 'success')
    else:
        flash('We have not received the payment yet. If your card was charged, it will show here shortly.', 'info')
    return redirect(url_for('sponsored.manage', slug=slug))


@sponsored_bp.route('/<slug>/manage-sponsored/invoice/<int:invoice_id>/mark-paid', methods=['POST'])
@login_required
def invoice_mark_paid(slug, invoice_id):
    """Shop owner only: the company paid by check, cash, Venmo or PayPal."""
    if not getattr(current_user, 'is_admin', False):
        abort(403)
    collection = _sponsored_collection(slug)
    invoice = _invoice_for(collection, invoice_id)
    method = request.form.get('method')
    if method not in MANUAL_METHODS:
        abort(400)
    if invoice.payment_status == 'unpaid':
        invoice.admin_notes = _clean(request.form.get('notes'), 500) or invoice.admin_notes
        orders = mark_invoice_paid(invoice, method)
        flash(f'Marked paid. {len(orders)} order{"s" if len(orders) != 1 else ""} sent to production.', 'success')
    return redirect(url_for('sponsored.manage', slug=slug))
