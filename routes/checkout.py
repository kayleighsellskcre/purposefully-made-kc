from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash, current_app
from flask_login import current_user, login_required
from flask_mail import Message
from models import db, Product, Order, OrderItem, Design, Address
from datetime import datetime
import stripe
import paypalrestsdk
import json

checkout_bp = Blueprint('checkout', __name__, url_prefix='/checkout')


def send_order_confirmation_email(order):
    """Send a branded HTML receipt to the customer and a copy to the admin."""
    if not order.email:
        return False
    mail = current_app.extensions.get('mail')
    if not mail or not current_app.config.get('MAIL_SERVER') or not current_app.config.get('MAIL_USERNAME'):
        return False

    # Set a global socket timeout so SMTP never hangs the request indefinitely.
    # We reset it after sending.
    import socket as _socket
    _prev_timeout = _socket.getdefaulttimeout()
    _socket.setdefaulttimeout(10)  # 10s max for any SMTP connection/send

    try:
        # ── Build plain-text fallback ──────────────────────────────────────
        items_text = '\n'.join(
            f"  • {item.product_name} – {item.color}, Size {item.size}"
            f" × {item.quantity}  =  ${item.subtotal:.2f}"
            for item in order.items
        )
        if order.fulfillment_method == 'shipping':
            addr_parts = filter(None, [
                order.shipping_recipient or order.full_name,
                order.shipping_street,
                order.shipping_street_2,
                f"{order.shipping_city}, {order.shipping_state} {order.shipping_zip}",
                order.shipping_country if order.shipping_country and order.shipping_country != 'USA' else None,
            ])
            delivery_text = '\n'.join(addr_parts)
        else:
            delivery_text = "Local Pickup — we'll reach out when your order is ready!"

        plain_body = (
            f"Hi {order.first_name or 'there'},\n\n"
            f"Your order is confirmed! Here's your receipt.\n\n"
            f"Order Number : {order.order_number}\n"
            f"Date         : {order.created_at.strftime('%B %d, %Y at %I:%M %p')} UTC\n"
            f"Payment      : {(order.payment_method or 'Card').title()} — PAID\n\n"
            f"Items:\n{items_text}\n\n"
            f"Subtotal : ${order.subtotal:.2f}\n"
            f"Shipping : {'$' + f'{order.shipping_cost:.2f}' if order.shipping_cost else 'Free (Pickup)'}\n"
            f"Total    : ${order.total:.2f}\n\n"
            f"Delivery:\n{delivery_text}\n\n"
            f"Questions? Email us at purposefullymadekc@gmail.com\n\n"
            f"Made with purpose, for you.\n"
            f"— Purposefully Made KC"
        )

        # ── HTML body from template ────────────────────────────────────────
        html_body = render_template('email/order_confirmation.html', order=order)

        # ── Customer receipt ───────────────────────────────────────────────
        msg = Message(
            subject=f"Your Order is Confirmed ✓ — {order.order_number}",
            recipients=[order.email],
            body=plain_body,
            html=html_body,
        )
        mail.send(msg)

        # ── Admin copy (new order alert) ───────────────────────────────────
        admin_email = current_app.config.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com'
        if admin_email and admin_email != order.email:
            admin_msg = Message(
                subject=f"New Order — {order.order_number} · ${order.total:.2f}",
                recipients=[admin_email],
                body=(
                    f"New order received!\n\n"
                    f"Order : {order.order_number}\n"
                    f"From  : {order.full_name} <{order.email}>\n"
                    f"Total : ${order.total:.2f}\n\n"
                    f"Items:\n{items_text}\n\n"
                    f"Delivery: {delivery_text}"
                ),
                html=html_body,
            )
            try:
                mail.send(admin_msg)
            except Exception:
                pass  # Don't fail the customer email if admin copy fails

        return True

    except Exception as e:
        import sys
        print(f"Order confirmation email error: {e}", file=sys.stderr)
        return False
    finally:
        _socket.setdefaulttimeout(_prev_timeout)

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
        flash('Your cart is empty', 'warning')
        return redirect(url_for('shop.index'))
    
    # Calculate totals
    totals = calculate_totals(cart)
    
    # Get user addresses if logged in
    addresses = []
    if current_user.is_authenticated:
        addresses = current_user.addresses.all()
    
    return render_template('checkout/index.html',
                         cart=cart,
                         totals=totals,
                         addresses=addresses,
                         stripe_public_key=current_app.config.get('STRIPE_PUBLIC_KEY'))


@checkout_bp.route('/create-payment-intent', methods=['POST'])
def create_payment_intent():
    """Create Stripe payment intent"""
    data = request.get_json()
    
    cart = get_cart()
    if not cart:
        return jsonify({'error': 'Cart is empty'}), 400
    
    shipping_method = data.get('shipping_method', 'pickup')
    totals = calculate_totals(cart, shipping_method)
    
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(totals['total'] * 100),  # Convert to cents
            currency='usd',
            metadata={
                'shipping_method': shipping_method
            }
        )
        
        return jsonify({
            'clientSecret': intent.client_secret
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@checkout_bp.route('/complete', methods=['POST'])
def complete():
    """Complete order after payment"""
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy import text as _text

    try:
        data = request.get_json(silent=True) or {}
        cart = get_cart()
        if not cart:
            return jsonify({'error': 'Cart is empty'}), 400

        payment_method = data.get('payment_method')
        payment_id = data.get('payment_id')
        shipping_method = data.get('shipping_method', 'pickup')
        email = data.get('email') or (current_user.email if current_user.is_authenticated else None)
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        phone = data.get('phone')
        shipping_info = data.get('shipping_info') or {}
        totals = calculate_totals(cart, shipping_method)
    except Exception as pre_err:
        current_app.logger.exception('checkout.complete pre-processing error: %s', pre_err)
        return jsonify({'error': 'Pre-processing error: ' + str(pre_err)}), 500

    try:
        # Apply per-transaction DB timeouts so a lock wait never hangs the request.
        # lock_timeout: fail fast if waiting on a table/row lock (not a slow query).
        # statement_timeout: fail fast if any single SQL statement runs too long.
        try:
            db.session.execute(_text('SET LOCAL lock_timeout = 5000'))
            db.session.execute(_text('SET LOCAL statement_timeout = 8000'))
        except Exception:
            pass  # Non-critical; continue even if SET LOCAL isn't supported

        # Cash orders are not yet paid — mark pending until collected
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
        )

        # collection_id is optional — skip if the column isn't in the DB yet
        try:
            order.collection_id = session.get('collection_id')
        except Exception:
            pass

        if shipping_method == 'shipping':
            order.shipping_recipient = shipping_info.get('recipient')
            order.shipping_street = shipping_info.get('street')
            order.shipping_street_2 = shipping_info.get('street_2')
            order.shipping_city = shipping_info.get('city')
            order.shipping_state = shipping_info.get('state')
            order.shipping_zip = shipping_info.get('zip')
            order.shipping_country = shipping_info.get('country', 'USA')

        db.session.add(order)
        db.session.flush()  # Assigns order.id without committing

        for cart_item in cart:
            try:
                product = Product.query.get(cart_item['product_id'])
                if not product:
                    continue
                design = Design.query.get(cart_item['design_id']) if cart_item.get('design_id') else None
                back_url = cart_item.get('back_design_url')
                back_filename = back_url.split('/')[-1] if back_url else None
                back_meta = cart_item.get('back_design_meta')
                back_meta_json = json.dumps(back_meta) if back_meta else None
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    design_id=cart_item.get('design_id'),
                    product_name=product.name,
                    style_number=product.style_number,
                    size=cart_item['size'],
                    color=cart_item['color'],
                    quantity=cart_item['quantity'],
                    unit_price=cart_item['unit_price'],
                    subtotal=cart_item['quantity'] * cart_item['unit_price'],
                    placement=cart_item.get('placement'),
                    print_type=cart_item.get('print_type') or 'DTF',
                    design_file_name=design.filename if design else None,
                    back_design_file_name=back_filename,
                    print_width=cart_item.get('print_width'),
                    print_height=cart_item.get('print_height'),
                    position_x=cart_item.get('position_x'),
                    position_y=cart_item.get('position_y'),
                    rotation=cart_item.get('rotation', 0),
                    proof_image=cart_item.get('proof_image'),
                )
                try:
                    order_item.back_design_meta = back_meta_json
                except Exception:
                    pass
                db.session.add(order_item)
            except Exception as item_err:
                current_app.logger.exception('Error building order item: %s', item_err)

        db.session.commit()

    except SQLAlchemyError as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception('checkout.complete DB error: %s', e)
        return jsonify({'error': 'DB error: ' + str(e)}), 500
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception('checkout.complete unexpected error: %s', e)
        return jsonify({'error': 'Unexpected error: ' + str(e)}), 500

    email_sent = send_order_confirmation_email(order)
    session['confirmation_email_sent'] = email_sent
    session['confirmation_email_sent_for'] = order.order_number
    session['cart'] = []
    session.modified = True

    return jsonify({
        'success': True,
        'order_number': order.order_number,
        'redirect_url': url_for('checkout.confirmation', order_number=order.order_number)
    })


@checkout_bp.route('/confirmation/<order_number>')
def confirmation(order_number):
    """Order confirmation page"""
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    
    # If user is logged in, verify it's their order
    if current_user.is_authenticated and order.user_id != current_user.id:
        if not current_user.is_admin:
            flash('Order not found', 'error')
            return redirect(url_for('main.index'))
    
    # Check if confirmation email was sent (from session, for this order)
    email_sent = False
    if session.get('confirmation_email_sent_for') == order_number:
        email_sent = session.get('confirmation_email_sent', False)
        session.pop('confirmation_email_sent', None)
        session.pop('confirmation_email_sent_for', None)
    
    return render_template('checkout/confirmation.html', order=order, email_sent=email_sent)
