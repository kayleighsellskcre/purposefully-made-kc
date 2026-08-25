from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash, current_app, abort
from flask_login import current_user, login_required
from flask_mail import Message
from models import db, Product, Order, OrderItem, Design, Address, User
from datetime import datetime
from threading import Thread
import math
import secrets
import stripe
import paypalrestsdk
import json
from utils.order_costs import default_due_date, shirt_unit_cost
from utils.local_time import format_central


def _new_request_id():
    return secrets.token_hex(8)


def _json_error(message, code, status=400, **extra):
    payload = {'success': False, 'error': message, 'error_code': code}
    payload.update(extra)
    return jsonify(payload), status


def _clip(value, length):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:length]


def _int_or_none(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _json_safe(value):
    """Drop NaN/Inf/bytes/unknown objects so json.dumps never fails."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return None


def _dumps(value):
    if not value:
        return None
    return json.dumps(_json_safe(value), allow_nan=False)

checkout_bp = Blueprint('checkout', __name__, url_prefix='/checkout')


def _mail_ready():
    from utils.mailer import mail_configured
    return mail_configured(current_app)


MAIL_SENDER_NAME = 'Purposefully Made KC'


def _mail_sender():
    """(display name, address) so inboxes show the business, not a bare address."""
    address = (
        current_app.config.get('MAIL_DEFAULT_SENDER')
        or current_app.config.get('MAIL_USERNAME')
    )
    if isinstance(address, (tuple, list)):
        return tuple(address)
    if not address:
        return None
    return (MAIL_SENDER_NAME, address)


def _receipt_recipients(order):
    """Email the receipt to the checkout address and the account email on file."""
    recipients = []
    seen = set()

    def add(addr):
        addr = (addr or '').strip()
        key = addr.lower()
        if addr and '@' in addr and key not in seen:
            seen.add(key)
            recipients.append(addr)

    add(getattr(order, 'email', None))
    user = getattr(order, 'user', None)
    if user is None and getattr(order, 'user_id', None):
        try:
            user = User.query.get(order.user_id)
        except Exception:
            user = None
    if user is not None:
        add(getattr(user, 'email', None))
    return recipients


def _render_email(template, **context):
    """Render an email template with a request context guaranteed to exist.

    Receipts are sent from a background thread, which has an app context but no
    request. Flask still runs context processors during render, and ours reads
    flask_login's current_user — that proxy resolves to None outside a request,
    so rendering raised AttributeError and every receipt was silently lost.
    Supplying a request context also lets url_for(_external=True) produce real
    absolute links instead of failing.
    """
    from flask import has_request_context
    if has_request_context():
        return render_template(template, **context)
    base_url = current_app.config.get('ADMIN_BASE_URL') or 'https://purposefullymadekc.com'
    with current_app.test_request_context(base_url=base_url):
        return render_template(template, **context)


def send_order_confirmation_email(order, force=False):
    """Send a branded HTML receipt to the customer + a dedicated alert to admin.

    Never raises — a mail failure must not turn a saved order into a checkout 500.
    """
    import socket as _socket
    import sys

    try:
        if getattr(order, 'confirmation_email_sent_at', None) and not force:
            return True
        sent = _send_order_confirmation_email(order)
        if sent:
            try:
                order.confirmation_email_sent_at = datetime.utcnow()
                db.session.commit()
            except Exception:
                db.session.rollback()
        return sent
    except Exception as e:
        print(f"Order confirmation email failed: {e}", file=sys.stderr)
        current_app.logger.exception('order confirmation email failed for %s', getattr(order, 'order_number', '?'))
        return False


def _send_order_confirmation_email(order):
    """Send a branded HTML receipt to the customer + a dedicated alert to admin."""
    import socket as _socket
    import sys

    mail = current_app.extensions.get('mail')
    mail_ready = _mail_ready()
    if not mail_ready:
        current_app.logger.error(
            'order email skipped for %s — MAIL_SERVER/USERNAME/PASSWORD not set',
            getattr(order, 'order_number', '?'),
        )

    # ── Build shared text pieces ───────────────────────────────────────────
    placed_at = order.created_at or datetime.utcnow()

    def _item_lines(item):
        """One item as plain text, including placement and personalization."""
        head = (
            f"  • {item.product_name} – {item.color}, Size {item.size}"
            f" × {item.quantity}  =  ${float(item.subtotal or 0):.2f}"
        )
        detail = []
        if item.placement:
            detail.append(f"placement: {str(item.placement).replace('_', ' ')}")
        personalization = item.back_design_details or {}
        if personalization.get('name'):
            detail.append(f"name: {personalization['name']}")
        if personalization.get('number'):
            detail.append(f"number: {personalization['number']}")
        if detail:
            head += f"\n      ({', '.join(detail)})"
        return head

    order_items = order.items.all() if hasattr(order.items, 'all') else list(order.items or [])
    items_text = '\n'.join(_item_lines(item) for item in order_items)
    if order.fulfillment_method == 'shipping':
        addr_parts = list(filter(None, [
            order.shipping_recipient or order.full_name,
            order.shipping_street,
            order.shipping_street_2,
            f"{order.shipping_city}, {order.shipping_state} {order.shipping_zip}",
            order.shipping_country if order.shipping_country and order.shipping_country != 'USA' else None,
        ]))
        delivery_text = '\n'.join(addr_parts)
    else:
        delivery_text = "Local Pickup — we'll reach out when ready!"

    email_sent = False
    recipients = _receipt_recipients(order)

    # ── 1. Customer receipt (account email + checkout email) ───────────────
    if mail_ready and recipients:
        paid = (order.payment_status == 'paid')
        plain_body = (
            f"Hi {order.first_name or 'there'},\n\n"
            f"Your order is confirmed. Save this email as your receipt.\n\n"
            f"Order Number : {order.order_number}\n"
            f"Date         : {format_central(placed_at)}\n"
            f"Payment      : {(order.payment_method or 'Card').title()} — "
            f"{'PAID' if paid else 'PENDING (pay on pickup)'}\n\n"
            f"Items:\n{items_text}\n\n"
            f"Subtotal : ${float(order.subtotal or 0):.2f}\n"
            f"Shipping : {'$' + f'{float(order.shipping_cost):.2f}' if order.shipping_cost else 'Free (Pickup)'}\n"
            f"Tax      : ${float(order.tax or 0):.2f}\n"
            f"Total    : ${float(order.total or 0):.2f}\n\n"
            f"Delivery:\n{delivery_text}\n\n"
            f"Questions? Email us at purposefullymadekc@gmail.com\n\n"
            f"Made with purpose, for you.\n"
            f"— Purposefully Made KC"
        )
        account_order_url = None
        if getattr(order, 'user_id', None) and order.order_number:
            try:
                account_order_url = url_for(
                    'account.order_detail',
                    order_number=order.order_number,
                    _external=True,
                )
            except Exception:
                account_order_url = None
        html_body = _render_email(
            'email/order_confirmation.html',
            order=order,
            account_order_url=account_order_url,
        )

        from utils.mailer import send as _send_mail
        msg = Message(
            subject=f"Your receipt — {order.order_number} | Purposefully Made KC",
            recipients=recipients,
            body=plain_body,
            html=html_body,
            sender=_mail_sender(),
            reply_to=current_app.config.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com',
        )
        email_sent = _send_mail(
            current_app._get_current_object(), msg,
            description=f'customer receipt for {order.order_number}',
        )
    elif not recipients:
        current_app.logger.error(
            'order email skipped for %s — no customer email on the order or account',
            getattr(order, 'order_number', '?'),
        )

    # ── 2. Admin order alert (always send, separate template) ─────────────
    admin_email = current_app.config.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com'
    if mail_ready and admin_email:
        admin_base_url = current_app.config.get('ADMIN_BASE_URL', 'https://purposefullymadekc.com')
        admin_html = _render_email(
            'email/admin_order_alert.html',
            order=order,
            admin_base_url=admin_base_url,
        )
        payment_note = 'PAID' if order.payment_status == 'paid' else 'CASH — collect on pickup'
        admin_plain = (
            f"NEW ORDER — {order.order_number} · ${order.total:.2f} · {payment_note}\n\n"
            f"Customer : {order.full_name} <{order.email}>"
            f"{' · ' + order.phone if order.phone else ''}\n\n"
            f"Items:\n{items_text}\n\n"
            f"Delivery: {delivery_text}\n\n"
            f"View order: {admin_base_url}/admin/orders/{order.id}"
        )
        from utils.mailer import send as _send_mail
        admin_msg = Message(
            subject=f"New Order — {order.order_number} · ${order.total:.2f}",
            recipients=[admin_email],
            body=admin_plain,
            html=admin_html,
            sender=_mail_sender(),
            reply_to=order.email or None,
        )
        _send_mail(
            current_app._get_current_object(), admin_msg,
            description=f'business new-order alert for {order.order_number}',
        )

    # ── 3. Admin SMS alert (non-critical) ─────────────────────────────────
    try:
        from utils.sms import send_new_order_alert
        send_new_order_alert(current_app._get_current_object(), order)
    except Exception:
        pass  # SMS is best-effort — never block the order

    return email_sent


def queue_order_confirmation_email(order_id):
    """Send receipt and alerts after the customer already got a success response."""
    app = current_app._get_current_object()

    def _run():
        try:
            with app.app_context():
                order = Order.query.get(order_id)
                if order:
                    # Touch related rows in this thread so the receipt has items + account email.
                    _ = list(order.items.all()) if hasattr(order.items, 'all') else list(order.items or [])
                    _ = order.user
                    send_order_confirmation_email(order)
        except Exception:
            app.logger.exception('background confirmation email failed for order_id=%s', order_id)

    if app.config.get('TESTING'):
        # Run inline under test so assertions are deterministic, and so a second
        # thread cannot interleave transactions on SQLite's single connection.
        _run()
        return

    Thread(target=_run, daemon=True).start()


def get_cart():
    """Get cart from session"""
    return session.get('cart', [])


def reprice_cart(cart, persist=True):
    """Recompute every line's unit price from the database.

    The cart lives in the session, so a stale price (the product was edited
    after the item was added) or a tampered one must be corrected before we
    quote a total or take payment. Returns the list of corrections made, which
    is empty on the normal path.
    """
    from utils.pricing import price_cart_item

    corrections = []
    for item in cart:
        if not isinstance(item, dict):
            continue
        product = Product.query.get(_int_or_none(item.get('product_id')))
        if not product:
            continue
        design = None
        design_id = _int_or_none(item.get('design_id'))
        if design_id:
            design = Design.query.get(design_id)

        correct = price_cart_item(item, product, design=design)
        stored = _float_or_none(item.get('unit_price'))
        if stored is None or abs(stored - correct) > 0.01:
            corrections.append({
                'product_id': product.id,
                'was': stored,
                'now': correct,
            })
            item['unit_price'] = correct

    if corrections and persist:
        session['cart'] = cart
        session.modified = True
        current_app.logger.warning('cart repriced at checkout: %s', corrections)
    return corrections


def calculate_totals(cart, shipping_method='pickup'):
    """Calculate order totals.

    Assumes reprice_cart() has already run, so item unit prices are trusted
    server-side values rather than whatever the session happened to hold.
    """
    subtotal = 0.0
    for item in cart:
        qty = _int_or_none(item.get('quantity')) or 0
        unit = _float_or_none(item.get('unit_price')) or 0.0
        subtotal += qty * unit
    subtotal = round(subtotal, 2)

    shipping_cost = 0
    if shipping_method == 'shipping':
        shipping_cost = current_app.config['SHIPPING_FLAT_RATE']
    
    # Fixed KS sales tax on subtotal only (shipping is not taxed)
    tax = round(subtotal * float(current_app.config['KS_SALES_TAX_RATE']), 2)
    
    total = round(subtotal + shipping_cost + tax, 2)
    
    return {
        'subtotal': subtotal,
        'shipping_cost': shipping_cost,
        'tax': tax,
        'total': total
    }

def _paypal_base_url(app):
    mode = (app.config.get('PAYPAL_MODE') or 'sandbox').strip().lower()
    return 'https://api-m.paypal.com' if mode == 'live' else 'https://api-m.sandbox.paypal.com'


def _get_paypal_access_token(app):
    """Fetch a short-lived PayPal OAuth token. Returns None on any failure."""
    import requests as _req
    import base64
    client_id = (app.config.get('PAYPAL_CLIENT_ID') or '').strip()
    secret = (app.config.get('PAYPAL_CLIENT_SECRET') or '').strip()
    if not client_id or not secret:
        return None
    auth = base64.b64encode(f'{client_id}:{secret}'.encode()).decode()
    try:
        resp = _req.post(
            f'{_paypal_base_url(app)}/v1/oauth2/token',
            headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'},
            data='grant_type=client_credentials',
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get('access_token')
        app.logger.error('PayPal token error %s: %s', resp.status_code, resp.text[:200])
    except Exception:
        app.logger.exception('PayPal access token request failed')
    return None


@checkout_bp.route('/paypal/create-order', methods=['POST'])
def paypal_create_order():
    """Create a PayPal Orders v2 order and return its ID to the client."""
    import requests as _req
    data = request.get_json(silent=True) or {}
    cart = get_cart()
    if not cart:
        return jsonify({'error': 'Cart is empty'}), 400

    from utils.group_orders import get_active_collection, ordering_blocked
    collection = get_active_collection(cart)
    if collection:
        blocked = ordering_blocked(collection)
        if blocked:
            return jsonify({'error': blocked}), 400

    reprice_cart(cart)
    shipping_method = data.get('shipping_method', 'pickup')
    totals = calculate_totals(cart, shipping_method)

    token = _get_paypal_access_token(current_app)
    if not token:
        return jsonify({'error': 'PayPal is not configured on this store.'}), 500

    try:
        resp = _req.post(
            f'{_paypal_base_url(current_app)}/v2/checkout/orders',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={
                'intent': 'CAPTURE',
                'purchase_units': [{
                    'amount': {'currency_code': 'USD', 'value': f'{totals["total"]:.2f}'},
                    'description': 'Purposefully Made KC Order',
                }],
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return jsonify({'id': resp.json()['id']})
        current_app.logger.error('PayPal create-order %s: %s', resp.status_code, resp.text[:300])
        return jsonify({'error': 'Could not start PayPal checkout.'}), 500
    except Exception:
        current_app.logger.exception('PayPal create-order request failed')
        return jsonify({'error': 'PayPal is unavailable right now.'}), 500


@checkout_bp.route('/paypal/capture-order', methods=['POST'])
def paypal_capture_order():
    """Capture an approved PayPal order. Records success in session so /complete can verify it."""
    import requests as _req
    data = request.get_json(silent=True) or {}
    order_id = (data.get('order_id') or '').strip()
    if not order_id:
        return jsonify({'success': False, 'error': 'Missing PayPal order_id'}), 400

    token = _get_paypal_access_token(current_app)
    if not token:
        return jsonify({'success': False, 'error': 'PayPal not configured'}), 500

    try:
        resp = _req.post(
            f'{_paypal_base_url(current_app)}/v2/checkout/orders/{order_id}/capture',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            result = resp.json()
            if result.get('status') == 'COMPLETED':
                # Store captured ID in session so /complete can verify without re-hitting PayPal
                captured = session.get('paypal_captured_ids', [])
                if order_id not in captured:
                    captured.append(order_id)
                session['paypal_captured_ids'] = captured
                session.modified = True
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': f'PayPal status: {result.get("status")}'}), 400
        current_app.logger.error('PayPal capture %s %s: %s', order_id, resp.status_code, resp.text[:300])
        return jsonify({'success': False, 'error': 'PayPal capture failed.'}), 500
    except Exception:
        current_app.logger.exception('PayPal capture request failed for %s', order_id)
        return jsonify({'success': False, 'error': 'PayPal is unavailable right now.'}), 500


@checkout_bp.route('/')
def index():
    """Checkout page"""
    cart = get_cart()
    
    if not cart:
        flash('Your cart is empty. Add some items to get started!', 'info')
        return redirect(url_for('cart.index'))
    
    # Calculate totals
    from utils.group_orders import get_active_collection, ordering_blocked
    collection = get_active_collection(cart)
    if collection:
        blocked = ordering_blocked(collection)
        if blocked:
            flash(blocked, 'error')
            return redirect(url_for('collection.view', slug=collection.slug))
    if reprice_cart(cart):
        flash('Some prices in your cart were updated to current pricing.', 'info')
    totals = calculate_totals(cart)
    
    from utils.order_artwork import FRONT_PLACEMENTS, mockup_urls
    enriched_cart = []
    for item in cart:
        enriched = dict(item)
        try:
            prod = Product.query.get(item.get('product_id'))
            enriched['product_name'] = prod.name if prod else 'Item'
            front_image, back_image = mockup_urls(prod, item.get('color'))
            placement = item.get('placement') or 'center_chest'
            enriched['front_image'] = front_image
            enriched['back_image'] = back_image
            enriched['placement'] = placement
            enriched['design_overlay'] = item.get('design_url') if placement in FRONT_PLACEMENTS else None
            enriched['back_overlay'] = item.get('back_design_url')
            _back_meta = item.get('back_design_meta') or {}
            if isinstance(_back_meta, str):
                try:
                    _back_meta = json.loads(_back_meta)
                except Exception:
                    _back_meta = {}
            enriched['back_overlay_class'] = (
                'back_name_number'
                if (_back_meta.get('name') or _back_meta.get('number'))
                else 'center_back'
            )
            d_id = item.get('design_id')
            if d_id:
                d = Design.query.get(int(d_id))
                if d:
                    enriched['design_title'] = d.title or d.original_filename or 'Custom Design'
                    enriched['design_thumb'] = (
                        d.file_path if (d.file_path or '').startswith('http')
                        else f"/static/{d.file_path}" if d.file_path else None
                    )
                else:
                    enriched['design_title'] = 'Custom Design'
                    enriched['design_thumb'] = item.get('design_url')
            elif item.get('design_url'):
                enriched['design_title'] = 'Uploaded Design'
                enriched['design_thumb'] = item.get('design_url')
            else:
                enriched['design_title'] = None
                enriched['design_thumb'] = None
        except Exception:
            enriched['product_name'] = 'Item'
            enriched['design_title'] = None
            enriched['design_thumb'] = None
        enriched_cart.append(enriched)
    
    # Get user addresses if logged in
    addresses = []
    if current_user.is_authenticated:
        addresses = current_user.addresses.all()
    
    is_group_order = bool(collection)
    allow_cash_payment = bool(
        collection and getattr(collection, 'allow_cash_pickup', False)
    )
    paypal_client_id = (current_app.config.get('PAYPAL_CLIENT_ID') or '').strip()
    return render_template('checkout/index.html',
                         cart=enriched_cart,
                         totals=totals,
                         addresses=addresses,
                         is_group_order=is_group_order,
                         group_collection=collection,
                         allow_cash_payment=allow_cash_payment,
                         stripe_public_key=current_app.config.get('STRIPE_PUBLIC_KEY'),
                         paypal_client_id=paypal_client_id,
                         shipping_flat_rate=current_app.config.get('SHIPPING_FLAT_RATE', 11.00))


@checkout_bp.route('/create-payment-intent', methods=['POST'])
def create_payment_intent():
    """Create Stripe payment intent"""
    data = request.get_json(silent=True) or {}
    
    cart = get_cart()
    if not cart:
        return jsonify({'error': 'Cart is empty'}), 400

    from utils.group_orders import get_active_collection, ordering_blocked
    collection = get_active_collection(cart)
    if collection:
        blocked = ordering_blocked(collection)
        if blocked:
            return jsonify({'error': blocked}), 400

    from utils.stock import aggregate_cart_blanks, check_stock
    grouped, labels = aggregate_cart_blanks(cart)
    for sku_key, qty in grouped.items():
        product = Product.query.get(sku_key[0])
        color, size = labels[sku_key]
        if not product:
            return jsonify({'error': 'One of the items in your cart is no longer available.'}), 400
        ok, stock_err, _remaining = check_stock(product, color, size, qty)
        if not ok:
            return jsonify({'error': stock_err}), 400

    shipping_method = data.get('shipping_method', 'pickup')
    # Price the intent from the database, never from the session's stored prices.
    reprice_cart(cart)
    totals = calculate_totals(cart, shipping_method)
    
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(round(totals['total'] * 100)),
            currency='usd',
            # Explicit card-only list: Apple Pay / Google Pay still appear as
            # wallets. Do NOT use automatic_payment_methods here — that would
            # surface Klarna, bank debit, and other methods from the Dashboard.
            payment_method_types=['card'],
            # Statement descriptor shown on customer's card statement (max 22 chars)
            statement_descriptor_suffix='PMKC ORDER',
            metadata={
                'shipping_method': shipping_method
            }
        )

        return jsonify({
            'clientSecret': intent.client_secret
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


PENDING_CHECKOUT_FIELDS = (
    'shipping_method', 'email', 'first_name', 'last_name', 'phone',
    'shipping_info', 'checkout_token', 'send_home_with_child',
    'teacher_name', 'child_grade', 'child_name',
)


@checkout_bp.route('/prepare', methods=['POST'])
def prepare():
    """Stash the checkout form server-side just before payment is confirmed.

    Wallet payments (Apple Pay, Google Pay) may redirect the customer off
    the page to authorize, and Stripe sends them back to /payment-return with
    nothing but a PaymentIntent id. Without this, the name, email, and shipping
    address typed into the form are gone by the time the order is created.
    """
    data = request.get_json(silent=True) or {}
    session['pending_checkout'] = {k: data.get(k) for k in PENDING_CHECKOUT_FIELDS}
    session.modified = True
    return jsonify({'success': True})


@checkout_bp.route('/payment-return')
def payment_return():
    """
    Return URL for wallet-based payments (Apple Pay, Google Pay) that
    redirect the user away from the page to authorize. Stripe sends them back
    here with ?payment_intent=... and ?payment_intent_client_secret=...
    """
    payment_intent_id = request.args.get('payment_intent')
    client_secret = request.args.get('payment_intent_client_secret')

    if not payment_intent_id:
        flash('Payment could not be verified. Please try again.', 'error')
        return redirect(url_for('checkout.index'))

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        status = intent.get('status')

        if status == 'succeeded':
            # Delegate to /checkout/complete so all order-creation logic is reused.
            # The payload must use the same field names complete() reads —
            # payment_method and payment_id. Sending only payment_intent_id made
            # complete() fall through to its 'cash' default, which skipped Stripe
            # verification and saved a paid card order as unpaid cash.
            import json as _json
            pending = session.get('pending_checkout') or {}
            payload = {k: pending.get(k) for k in PENDING_CHECKOUT_FIELDS}
            payload['payment_method'] = 'stripe'
            payload['payment_id'] = payment_intent_id
            if not payload.get('shipping_method'):
                payload['shipping_method'] = 'pickup'
            # Reuse the same idempotency key so a repeated return cannot
            # create a second order for one payment.
            if not payload.get('checkout_token'):
                payload['checkout_token'] = f'pi:{payment_intent_id}'[:64]

            # Build an internal call via the same app context
            with current_app.test_client() as c:
                # Preserve session
                with c.session_transaction() as sess:
                    sess.update(session)
                resp = c.post(
                    url_for('checkout.complete'),
                    data=_json.dumps(payload),
                    content_type='application/json',
                )
                result = resp.get_json() or {}

            if result.get('success'):
                # The internal client owns its own session, so mirror the
                # success markers onto the real one or the customer will be
                # denied their own confirmation page.
                session['checkout_success_token'] = payload.get('checkout_token')
                session['checkout_success_order'] = result.get('order_number')
                session['cart'] = []
                session.pop('pending_checkout', None)
                session.pop('collection_id', None)
                session.modified = True
                return redirect(url_for('checkout.confirmation',
                                        order_number=result.get('order_number', '')))
            else:
                flash(result.get('error', 'Order could not be placed. Please contact us.'), 'error')
                return redirect(url_for('checkout.index'))

        elif status in ('requires_payment_method', 'requires_action'):
            flash('Payment was not completed. Please try again.', 'error')
            return redirect(url_for('checkout.index'))

        else:
            flash(f'Payment status: {status}. Please contact us if you were charged.', 'warning')
            return redirect(url_for('checkout.index'))

    except stripe.error.StripeError as e:
        flash(f'Payment error: {e.user_message}', 'error')
        return redirect(url_for('checkout.index'))


@checkout_bp.route('/complete', methods=['POST'])
def complete():
    """Complete order after payment."""
    from sqlalchemy.exc import SQLAlchemyError, IntegrityError
    from sqlalchemy import text as _text

    rid = _new_request_id()

    try:
        data = request.get_json(silent=True) or {}
        cart = get_cart()
        if not cart:
            return _json_error('Your cart is empty.', 'CART_EMPTY', 400, request_id=rid)

        from utils.group_orders import get_active_collection, ordering_blocked
        collection = get_active_collection(cart)
        if collection:
            blocked = ordering_blocked(collection)
            if blocked:
                return _json_error(blocked, 'GROUP_ORDER_CLOSED', 400, request_id=rid)

        checkout_token = _clip(data.get('checkout_token'), 64)
        if checkout_token and session.get('checkout_success_token') == checkout_token:
            order_number = session.get('checkout_success_order')
            if order_number:
                return jsonify({
                    'success': True,
                    'order_number': order_number,
                    'redirect_url': url_for('checkout.confirmation', order_number=order_number),
                    'replayed': True,
                    'request_id': rid,
                })
        if checkout_token:
            existing = Order.query.filter_by(checkout_token=checkout_token).first()
            if existing:
                session['checkout_success_token'] = checkout_token
                session['checkout_success_order'] = existing.order_number
                session['cart'] = []
                session.modified = True
                return jsonify({
                    'success': True,
                    'order_number': existing.order_number,
                    'redirect_url': url_for('checkout.confirmation', order_number=existing.order_number),
                    'replayed': True,
                    'request_id': rid,
                })

        payment_method = (data.get('payment_method') or '').strip() or 'cash'
        payment_id = data.get('payment_id')
        shipping_method = data.get('shipping_method') or 'pickup'
        email = _clip(data.get('email') or (current_user.email if current_user.is_authenticated else None), 120)
        # Logged-in customers always get the receipt at the account email on file.
        if current_user.is_authenticated and getattr(current_user, 'email', None):
            email = _clip(current_user.email, 120) or email
        first_name = _clip(data.get('first_name'), 100)
        last_name = _clip(data.get('last_name'), 100)
        phone = _clip(data.get('phone'), 20)
        shipping_info = data.get('shipping_info') or {}
        # Final authority on price. Runs before the Stripe amount comparison
        # below, so a session whose prices were altered after the intent was
        # created fails the comparison instead of being charged the wrong sum.
        reprice_cart(cart)
        totals = calculate_totals(cart, shipping_method)

        if not email:
            return _json_error('Please enter your email so we can send the order confirmation.', 'EMAIL_REQUIRED', 400, request_id=rid)
        if not first_name or not last_name:
            return _json_error('Please enter your first and last name.', 'NAME_REQUIRED', 400, request_id=rid)
        if payment_method not in ('cash', 'stripe', 'paypal'):
            return _json_error('Please choose a payment method.', 'PAYMENT_METHOD_INVALID', 400, request_id=rid)
        if payment_method == 'cash':
            if not collection or not getattr(collection, 'allow_cash_pickup', False):
                return _json_error(
                    'Cash / pay at pickup is only available for group orders when the organizer allows it.',
                    'CASH_NOT_ALLOWED',
                    400,
                    request_id=rid,
                )
        if payment_method == 'stripe' and not payment_id:
            return _json_error('Card payment was not completed. Please try the card again.', 'PAYMENT_ID_REQUIRED', 400, request_id=rid)
        if payment_method == 'paypal' and not payment_id:
            return _json_error('PayPal payment was not completed. Please try again.', 'PAYMENT_ID_REQUIRED', 400, request_id=rid)
        if shipping_method == 'shipping':
            missing = [k for k in ('street', 'city', 'state', 'zip') if not (shipping_info.get(k) or '').strip()]
            if missing:
                return _json_error('Please complete the shipping address.', 'SHIPPING_ADDRESS_REQUIRED', 400, request_id=rid, fields=missing)
            if collection and not collection.shipping_enabled:
                return _json_error('This group order is pickup only.', 'SHIPPING_NOT_ALLOWED', 400, request_id=rid)

        send_home = bool(data.get('send_home_with_child')) and bool(collection)
        teacher_name = _clip(data.get('teacher_name'), 120) if send_home else None
        child_grade = _clip(data.get('child_grade'), 40) if send_home else None
        child_name = _clip(data.get('child_name'), 120) if send_home else None
        if send_home and (not teacher_name or not child_grade or not child_name):
            return _json_error(
                'Please enter the coach/teacher name, grade, and child\'s name so we can send this home with them.',
                'SEND_HOME_DETAILS_REQUIRED',
                400,
                request_id=rid,
            )
        if payment_method == 'paypal' and payment_id:
            captured_ids = session.get('paypal_captured_ids', [])
            if payment_id not in captured_ids:
                return _json_error(
                    'PayPal payment was not captured. Please complete the PayPal flow before placing your order.',
                    'PAYPAL_NOT_CAPTURED',
                    400,
                    request_id=rid,
                )
        if payment_method == 'stripe' and payment_id:
            try:
                intent = stripe.PaymentIntent.retrieve(payment_id)
            except Exception:
                current_app.logger.exception('checkout rid=%s stripe retrieve failed', rid)
                return _json_error(
                    'We could not confirm the card payment. Please try again.',
                    'PAYMENT_LOOKUP_FAILED',
                    400,
                    request_id=rid,
                )
            expected_cents = int(round(totals['total'] * 100))
            if getattr(intent, 'amount', None) != expected_cents:
                return _json_error(
                    'The card total does not match this order. Please wait a moment and try checkout again.',
                    'PAYMENT_AMOUNT_MISMATCH',
                    400,
                    request_id=rid,
                )
            if getattr(intent, 'status', None) not in ('succeeded', 'processing'):
                return _json_error(
                    'Card payment was not completed. Please try the card again.',
                    'PAYMENT_NOT_COMPLETE',
                    400,
                    request_id=rid,
                )
    except Exception as pre_err:
        current_app.logger.exception('checkout.complete pre-processing error rid=%s: %s', rid, pre_err)
        return _json_error(
            'We could not read this checkout request. Your cart is still saved.',
            'PREPROCESS_ERROR',
            500,
            request_id=rid,
        )

    try:
        try:
            db.session.execute(_text('SET LOCAL lock_timeout = 5000'))
            db.session.execute(_text('SET LOCAL statement_timeout = 8000'))
        except Exception:
            pass

        from utils.stock import reserve_cart_inventory
        stock_ok, stock_err = reserve_cart_inventory(cart)
        if not stock_ok:
            db.session.rollback()
            return _json_error(stock_err or 'That size just sold out.', 'OUT_OF_STOCK', 400, request_id=rid)

        is_cash = (payment_method == 'cash')
        order = Order(
            user_id=current_user.id if current_user.is_authenticated else None,
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            fulfillment_method=shipping_method,
            subtotal=totals['subtotal'],
            shipping_cost=totals['shipping_cost'],
            tax=totals['tax'],
            total=totals['total'],
            payment_method=payment_method,
            payment_status='pending' if is_cash else 'paid',
            payment_intent_id=payment_id if payment_method == 'stripe' and payment_id else None,
            paypal_order_id=payment_id if payment_method == 'paypal' and payment_id else None,
            paid_at=None if is_cash else datetime.utcnow(),
            status='new' if is_cash else 'paid',
            production_stage='order_received',
            due_date=default_due_date(),
            checkout_token=checkout_token,
            send_home_with_child=send_home,
            teacher_name=teacher_name,
            child_grade=child_grade,
            child_name=child_name,
        )

        try:
            if collection:
                order.collection_id = collection.id
        except Exception:
            pass

        if shipping_method == 'shipping':
            order.shipping_recipient = _clip(shipping_info.get('recipient'), 200)
            order.shipping_street = _clip(shipping_info.get('street'), 200)
            order.shipping_street_2 = _clip(shipping_info.get('street_2'), 200)
            order.shipping_city = _clip(shipping_info.get('city'), 100)
            order.shipping_state = _clip(shipping_info.get('state'), 50)
            order.shipping_zip = _clip(shipping_info.get('zip'), 20)
            order.shipping_country = _clip(shipping_info.get('country'), 50) or 'USA'

        db.session.add(order)
        db.session.flush()

        saved_items = 0
        blank_cogs = 0.0
        cogs_found = False
        for cart_item in cart:
            try:
                product = Product.query.get(_int_or_none(cart_item.get('product_id')))
                if not product:
                    current_app.logger.error('checkout rid=%s skipped item, product missing: %s', rid, cart_item.get('product_id'))
                    continue
                design_id = _int_or_none(cart_item.get('design_id'))
                design = Design.query.get(design_id) if design_id else None
                back_url = cart_item.get('back_design_url')
                back_filename = _clip((back_url or '').split('/')[-1] if back_url else None, 500)
                back_meta = cart_item.get('back_design_meta')
                if isinstance(back_meta, str):
                    try:
                        back_meta = json.loads(back_meta)
                    except Exception:
                        back_meta = None
                if isinstance(back_meta, dict):
                    back_meta = dict(back_meta)
                elif back_url:
                    back_meta = {}
                else:
                    back_meta = None
                if isinstance(back_meta, dict) and back_url:
                    back_meta['file_url'] = back_url
                # Personalized-back fields are optional. Keep the file URL so
                # production can still show and save a back image with no name/number.
                if isinstance(back_meta, dict) and not (
                    back_meta.get('name') or back_meta.get('number') or back_meta.get('file_url')
                ):
                    back_meta = None
                transfer_prod = cart_item.get('transfer_production')
                if isinstance(transfer_prod, str):
                    try:
                        transfer_prod = json.loads(transfer_prod)
                    except Exception:
                        transfer_prod = None
                if isinstance(transfer_prod, dict):
                    transfer_prod = dict(transfer_prod)
                    back_block = transfer_prod.get('back')
                    if isinstance(back_block, dict) and (back_block.get('name') or back_block.get('number')):
                        transfer_prod['back'] = dict(back_block)
                        transfer_prod['back']['customer_name'] = (
                            transfer_prod['back'].get('customer_name') or order.full_name
                        )
                    else:
                        transfer_prod['back'] = None
                design_filename = _clip(design.filename if design else None, 500)
                if not design_filename:
                    design_url = cart_item.get('design_url') or ''
                    design_filename = _clip(design_url.split('/')[-1] if design_url else None, 500)
                qty = max(1, _int_or_none(cart_item.get('quantity')) or 1)
                unit_price = _float_or_none(cart_item.get('unit_price'))
                if unit_price is None:
                    raise ValueError('unit_price')
                proof_image = _clip(
                    cart_item.get('proof_image') or cart_item.get('proof_front_url'),
                    500,
                )
                proof_back_image = _clip(cart_item.get('proof_back_url'), 500)
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    design_id=design.id if design else None,
                    product_name=_clip(product.name, 200),
                    style_number=_clip(product.style_number, 50),
                    size=_clip(cart_item.get('size'), 20) or 'M',
                    color=_clip(cart_item.get('color'), 100) or 'Unknown',
                    quantity=qty,
                    unit_price=unit_price,
                    subtotal=qty * unit_price,
                    placement=_clip(cart_item.get('placement'), 50),
                    print_type=_clip(cart_item.get('print_type'), 50) or 'DTF',
                    design_file_name=design_filename,
                    back_design_file_name=back_filename,
                    print_width=_float_or_none(cart_item.get('print_width')),
                    print_height=_float_or_none(cart_item.get('print_height')),
                    position_x=_float_or_none(cart_item.get('position_x')),
                    position_y=_float_or_none(cart_item.get('position_y')),
                    rotation=_float_or_none(cart_item.get('rotation')) or 0,
                    proof_image=proof_image,
                    proof_back_image=proof_back_image,
                )
                try:
                    order_item.back_design_meta = _dumps(back_meta)
                except Exception:
                    pass
                try:
                    order_item.transfer_production = _dumps(transfer_prod)
                except Exception:
                    pass
                db.session.add(order_item)
                saved_items += 1
                shirt_cost = shirt_unit_cost(product)
                if shirt_cost is not None:
                    blank_cogs += shirt_cost * qty
                    cogs_found = True
            except Exception as item_err:
                current_app.logger.exception('checkout rid=%s item failed: %s', rid, item_err)
                db.session.rollback()
                return _json_error(
                    'One item in your cart could not be saved. Check the design, size, and color, then try again.',
                    'ORDER_ITEM_INVALID',
                    400,
                    request_id=rid,
                    field=str(item_err),
                )

        if saved_items == 0:
            db.session.rollback()
            return _json_error(
                'None of the items in your cart could be saved. Please return to the cart and try again.',
                'NO_ORDER_ITEMS',
                400,
                request_id=rid,
            )

        if cogs_found:
            order.cost_of_goods = round(blank_cogs, 2)
            order.profit = round(float(order.total or 0) - order.cost_of_goods, 2)

        db.session.commit()

    except IntegrityError as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        # A unique-token collision means a concurrent request already saved this
        # exact checkout. That is a duplicate submit, not a failure: hand the
        # customer the order that won the race instead of an error.
        if checkout_token:
            winner = Order.query.filter_by(checkout_token=checkout_token).first()
            if winner:
                current_app.logger.info(
                    'checkout rid=%s duplicate submit resolved to %s',
                    rid, winner.order_number,
                )
                session['checkout_success_token'] = checkout_token
                session['checkout_success_order'] = winner.order_number
                session['cart'] = []
                session.pop('collection_id', None)
                session.modified = True
                return jsonify({
                    'success': True,
                    'order_number': winner.order_number,
                    'redirect_url': url_for('checkout.confirmation', order_number=winner.order_number),
                    'replayed': True,
                    'request_id': rid,
                })
        current_app.logger.exception('checkout.complete integrity error rid=%s: %s', rid, e)
        return _json_error(
            'This order could not be saved. Your cart is still here — please try again.',
            'DB_CONSTRAINT',
            500,
            request_id=rid,
        )
    except SQLAlchemyError as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception('checkout.complete DB error rid=%s: %s', rid, e)
        return _json_error(
            'We could not save this order. Your cart is still here — please try again.',
            'DB_ERROR',
            500,
            request_id=rid,
        )
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception('checkout.complete unexpected error rid=%s: %s', rid, e)
        return _json_error(
            'Something went wrong placing this order. Your cart is still saved.',
            'UNEXPECTED_ERROR',
            500,
            request_id=rid,
        )

    # Cart clears only after the order row exists. Email goes out after we
    # answer the browser so SMTP cannot turn a saved order into a timeout.
    session['checkout_success_token'] = checkout_token
    session['checkout_success_order'] = order.order_number
    session['cart'] = []
    session.pop('collection_id', None)
    session.modified = True

    queue_order_confirmation_email(order.id)

    return jsonify({
        'success': True,
        'order_number': order.order_number,
        'redirect_url': url_for('checkout.confirmation', order_number=order.order_number),
        'request_id': rid,
    })


@checkout_bp.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    """Stripe's authenticated confirmation that a payment really succeeded.

    Until now nothing consumed STRIPE_WEBHOOK_SECRET, so order creation relied
    entirely on the customer's browser posting back to /complete. If they closed
    the tab or lost signal after paying, the money arrived and no order existed.

    This handler is deliberately narrow: it does not create orders (it has no
    cart), it reconciles ones that already exist and raises a loud alert for a
    payment with no order so it can be fixed by hand.
    """
    secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
    if not secret:
        current_app.logger.error('stripe webhook received but STRIPE_WEBHOOK_SECRET is not set')
        return jsonify({'error': 'Webhook not configured'}), 503

    payload = request.get_data()
    signature = request.headers.get('Stripe-Signature', '')
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except ValueError:
        current_app.logger.warning('stripe webhook rejected: malformed payload')
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        current_app.logger.warning('stripe webhook rejected: bad signature')
        return jsonify({'error': 'Invalid signature'}), 400

    event_type = event.get('type')
    obj = (event.get('data') or {}).get('object') or {}
    intent_id = obj.get('id')

    if event_type == 'payment_intent.succeeded' and intent_id:
        order = Order.query.filter_by(payment_intent_id=intent_id).first()
        if order is None:
            # Paid, but no order row. Alert rather than guess at a cart.
            current_app.logger.error(
                'ORPHANED PAYMENT: stripe intent %s succeeded for %s cents with no matching order',
                intent_id, obj.get('amount'),
            )
            try:
                from utils.sms import send_server_error_alert
                send_server_error_alert(
                    current_app._get_current_object(),
                    'ORPHANED-PAY',
                    f'stripe/{intent_id}',
                    'Payment succeeded with no order. Check the Stripe dashboard.',
                )
            except Exception:
                pass
            return jsonify({'received': True, 'orphaned': True})

        # Idempotent: Stripe retries webhooks, so re-delivery must be a no-op.
        if order.payment_status != 'paid':
            order.payment_status = 'paid'
            order.status = 'paid' if order.status == 'new' else order.status
            order.paid_at = order.paid_at or datetime.utcnow()
            db.session.commit()
            current_app.logger.info('webhook marked %s paid', order.order_number)

        # Covers the case where the browser never reached the thank-you page.
        if not getattr(order, 'confirmation_email_sent_at', None):
            queue_order_confirmation_email(order.id)

        return jsonify({'received': True, 'order_number': order.order_number})

    if event_type == 'payment_intent.payment_failed' and intent_id:
        order = Order.query.filter_by(payment_intent_id=intent_id).first()
        if order and order.payment_status == 'pending':
            order.payment_status = 'failed'
            db.session.commit()
            current_app.logger.info('webhook marked %s failed', order.order_number)
        return jsonify({'received': True})

    return jsonify({'received': True, 'ignored': event_type})


@checkout_bp.route('/confirmation/<order_number>')
def confirmation(order_number):
    """Order confirmation page — only the buyer (or admin) can open it."""
    from utils.privacy import user_can_view_order
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    if not user_can_view_order(order):
        abort(404)

    email_sent = bool(getattr(order, 'confirmation_email_sent_at', None))
    return render_template('checkout/confirmation.html', order=order, email_sent=email_sent)


@checkout_bp.route('/confirmation/<order_number>/send-email', methods=['POST'])
def send_confirmation_email_now(order_number):
    """Send the receipt while the thank-you page is still open.

    Checkout returns immediately so SMTP cannot time out the order. This
    follow-up request stays alive long enough for Gmail to accept the mail.
    """
    from utils.privacy import user_can_view_order
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    if not user_can_view_order(order):
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    sent = send_order_confirmation_email(order)
    return jsonify({
        'success': bool(sent),
        'already_sent': bool(getattr(order, 'confirmation_email_sent_at', None)),
        'mail_ready': _mail_ready(),
        'recipients': _receipt_recipients(order),
    })
