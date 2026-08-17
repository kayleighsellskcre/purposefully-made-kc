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
    return bool(
        current_app.extensions.get('mail')
        and current_app.config.get('MAIL_SERVER')
        and current_app.config.get('MAIL_USERNAME')
        and current_app.config.get('MAIL_PASSWORD')
    )


def _mail_sender():
    return (
        current_app.config.get('MAIL_DEFAULT_SENDER')
        or current_app.config.get('MAIL_USERNAME')
    )


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
    try:
        return render_template(template, **context)
    except RuntimeError:
        with current_app.test_request_context():
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
    items_text = '\n'.join(
        f"  • {item.product_name} – {item.color}, Size {item.size}"
        f" × {item.quantity}  =  ${float(item.subtotal or 0):.2f}"
        for item in (order.items.all() if hasattr(order.items, 'all') else list(order.items or []))
    )
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

        timeout = int(current_app.config.get('MAIL_TIMEOUT') or 20)
        _prev = _socket.getdefaulttimeout()
        _socket.setdefaulttimeout(timeout)
        try:
            msg = Message(
                subject=f"Your receipt — {order.order_number} | Purposefully Made KC",
                recipients=recipients,
                body=plain_body,
                html=html_body,
                sender=_mail_sender(),
                reply_to=current_app.config.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com',
            )
            mail.send(msg)
            email_sent = True
            current_app.logger.info(
                'customer confirmation email sent for %s to %s',
                getattr(order, 'order_number', '?'),
                ', '.join(recipients),
            )
        except Exception as e:
            print(f"Customer confirmation email error: {e}", file=sys.stderr)
            current_app.logger.exception(
                'customer confirmation email error for %s to %s',
                getattr(order, 'order_number', '?'),
                ', '.join(recipients),
            )
        finally:
            _socket.setdefaulttimeout(_prev)
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
        timeout = int(current_app.config.get('MAIL_TIMEOUT') or 20)
        _prev = _socket.getdefaulttimeout()
        _socket.setdefaulttimeout(timeout)
        try:
            admin_msg = Message(
                subject=f"🛍 New Order — {order.order_number} · ${order.total:.2f}",
                recipients=[admin_email],
                body=admin_plain,
                html=admin_html,
                sender=_mail_sender(),
            )
            mail.send(admin_msg)
        except Exception as e:
            print(f"Admin order alert email error: {e}", file=sys.stderr)
        finally:
            _socket.setdefaulttimeout(_prev)

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

    Thread(target=_run, daemon=True).start()


def get_cart():
    """Get cart from session"""
    return session.get('cart', [])

KS_SALES_TAX_RATE = 0.065  # Kansas state sales tax 6.5%

def calculate_totals(cart, shipping_method='pickup'):
    """Calculate order totals"""
    subtotal = sum(item['quantity'] * item['unit_price'] for item in cart)
    
    shipping_cost = 0
    if shipping_method == 'shipping':
        shipping_cost = current_app.config['SHIPPING_FLAT_RATE']
    
    # Kansas 6.5% sales tax applied to the subtotal only (shipping is not taxed)
    tax = round(subtotal * KS_SALES_TAX_RATE, 2)
    
    total = subtotal + shipping_cost + tax
    
    return {
        'subtotal': subtotal,
        'shipping_cost': shipping_cost,
        'tax': tax,
        'total': total
    }

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
    return render_template('checkout/index.html',
                         cart=enriched_cart,
                         totals=totals,
                         addresses=addresses,
                         is_group_order=is_group_order,
                         group_collection=collection,
                         stripe_public_key=current_app.config.get('STRIPE_PUBLIC_KEY'))


@checkout_bp.route('/create-payment-intent', methods=['POST'])
def create_payment_intent():
    """Create Stripe payment intent"""
    data = request.get_json()
    
    cart = get_cart()
    if not cart:
        return jsonify({'error': 'Cart is empty'}), 400

    from utils.group_orders import get_active_collection, ordering_blocked
    collection = get_active_collection(cart)
    if collection:
        blocked = ordering_blocked(collection)
        if blocked:
            return jsonify({'error': blocked}), 400

    shipping_method = data.get('shipping_method', 'pickup')
    totals = calculate_totals(cart, shipping_method)
    
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(totals['total'] * 100),  # Convert to cents
            currency='usd',
            # automatic_payment_methods enables card, Apple Pay, Google Pay,
            # Venmo, and any other methods enabled in the Stripe dashboard.
            automatic_payment_methods={'enabled': True},
            metadata={
                'shipping_method': shipping_method
            }
        )

        return jsonify({
            'clientSecret': intent.client_secret
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@checkout_bp.route('/payment-return')
def payment_return():
    """
    Return URL for wallet-based payments (Apple Pay, Google Pay, Venmo) that
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
            # Delegate to /checkout/complete so all order-creation logic is reused
            # We POST the payment_intent_id so complete() can validate it
            from flask import make_response
            import json as _json
            # Build an internal call via the same app context
            with current_app.test_client() as c:
                # Preserve session
                with c.session_transaction() as sess:
                    sess.update(session)
                resp = c.post(
                    url_for('checkout.complete'),
                    data=_json.dumps({'payment_intent_id': payment_intent_id}),
                    content_type='application/json',
                )
                result = resp.get_json() or {}

            if result.get('success'):
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
        totals = calculate_totals(cart, shipping_method)

        if not email:
            return _json_error('Please enter your email so we can send the order confirmation.', 'EMAIL_REQUIRED', 400, request_id=rid)
        if not first_name or not last_name:
            return _json_error('Please enter your first and last name.', 'NAME_REQUIRED', 400, request_id=rid)
        if payment_method not in ('cash', 'stripe', 'paypal'):
            return _json_error('Please choose a payment method.', 'PAYMENT_METHOD_INVALID', 400, request_id=rid)
        if payment_method == 'stripe' and not payment_id:
            return _json_error('Card payment was not completed. Please try the card again.', 'PAYMENT_ID_REQUIRED', 400, request_id=rid)
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
