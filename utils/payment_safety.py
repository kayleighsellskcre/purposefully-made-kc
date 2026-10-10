"""Safety net for paid checkouts.

PayPal takes the money before the site saves the order. These helpers make
sure a paid checkout is never silently lost:

* every PayPal capture is written to the database the moment it succeeds,
  together with the cart and the customer's checkout details;
* /checkout/complete can confirm a capture from the database or straight from
  PayPal, so it no longer depends on the browser's session cookie;
* if an order still can't be saved, the admin gets an email and a
  notification right away with everything needed to finish it by hand;
* a background sweep catches payments whose customer closed the page before
  the order step ran.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import current_app, session


# ── PayPal API ────────────────────────────────────────────────────────────────

def _paypal_get(path):
    import requests
    from routes.checkout import _get_paypal_access_token, _paypal_base_url
    app = current_app._get_current_object()
    token = _get_paypal_access_token(app)
    if not token:
        return None
    resp = requests.get(
        f'{_paypal_base_url(app)}{path}',
        headers={'Authorization': f'Bearer {token}'},
        timeout=15,
    )
    if resp.status_code != 200:
        current_app.logger.warning('PayPal GET %s -> %s: %s', path, resp.status_code, resp.text[:200])
        return None
    return resp.json()


def completed_capture_total(order_json):
    """Sum of COMPLETED captures in a PayPal Orders v2 response, or None."""
    if not order_json:
        return None
    total = 0.0
    found = False
    for unit in order_json.get('purchase_units') or []:
        for cap in ((unit.get('payments') or {}).get('captures') or []):
            if (cap.get('status') or '').upper() != 'COMPLETED':
                continue
            try:
                total += float((cap.get('amount') or {}).get('value'))
                found = True
            except (TypeError, ValueError):
                continue
    return round(total, 2) if found else None


def _capture_time(order_json):
    """When PayPal says the money was captured (naive UTC), or None."""
    for unit in (order_json or {}).get('purchase_units') or []:
        for cap in ((unit.get('payments') or {}).get('captures') or []):
            stamp = cap.get('create_time')
            if stamp:
                try:
                    return datetime.strptime(stamp.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
                except ValueError:
                    continue
    return None


def payer_from_order_json(order_json):
    payer = (order_json or {}).get('payer') or {}
    name = payer.get('name') or {}
    full = ' '.join(p for p in (name.get('given_name'), name.get('surname')) if p).strip()
    return full or None, payer.get('email_address')


def fetch_paypal_order(paypal_order_id):
    try:
        return _paypal_get(f'/v2/checkout/orders/{paypal_order_id}')
    except Exception as exc:
        current_app.logger.warning('PayPal order lookup failed for %s: %s', paypal_order_id, exc)
        return None


def resolve_paypal_order_id(ref):
    """Accept a PayPal order ID or a transaction (capture) ID; return the order ID."""
    ref = (ref or '').strip()
    if not ref:
        return None
    if fetch_paypal_order(ref):
        return ref
    try:
        cap = _paypal_get(f'/v2/payments/captures/{ref}')
    except Exception:
        cap = None
    related = ((cap or {}).get('supplementary_data') or {}).get('related_ids') or {}
    return related.get('order_id')


# ── Capture records ───────────────────────────────────────────────────────────

def record_paypal_capture(paypal_order_id, amount, order_json=None, cart=None,
                          customer=None, collection_id=None, user_id=None):
    """Save (or refresh) the database record of a captured PayPal payment."""
    from models import db, PaymentCapture
    payer_name, payer_email = payer_from_order_json(order_json)
    try:
        cap = PaymentCapture.query.filter_by(provider_ref=paypal_order_id).first()
        if cap is None:
            cap = PaymentCapture(provider='paypal', provider_ref=paypal_order_id)
            db.session.add(cap)
        paid_at = _capture_time(order_json)
        if paid_at:
            cap.created_at = paid_at
        cap.amount = amount
        cap.payer_name = payer_name or cap.payer_name
        cap.payer_email = payer_email or cap.payer_email
        if customer:
            cap.customer_json = json.dumps(customer)
        if cart:
            cap.cart_json = json.dumps(cart)
        cap.collection_id = collection_id or cap.collection_id
        cap.user_id = user_id or cap.user_id
        db.session.commit()
        return cap
    except Exception:
        db.session.rollback()
        current_app.logger.exception('could not record PayPal capture %s', paypal_order_id)
        return None


def get_capture(paypal_order_id):
    from models import PaymentCapture
    if not paypal_order_id:
        return None
    try:
        return PaymentCapture.query.filter_by(provider_ref=paypal_order_id).first()
    except Exception:
        return None


def verified_paypal_amount(paypal_order_id):
    """How much PayPal actually captured for this order. None if nothing was.

    Checks the browser session first, then the database record, then asks
    PayPal directly, so a lost or oversized session cookie can't lose a sale.
    """
    if not paypal_order_id:
        return None
    amounts = session.get('paypal_captured_amounts') or {}
    if paypal_order_id in amounts:
        return float(amounts[paypal_order_id])
    cap = get_capture(paypal_order_id)
    if cap is not None and cap.amount is not None:
        return float(cap.amount)
    order_json = fetch_paypal_order(paypal_order_id)
    amount = completed_capture_total(order_json)
    if amount is not None:
        record_paypal_capture(paypal_order_id, amount, order_json=order_json)
    return amount


def link_capture_to_order(paypal_order_id, order):
    from models import db
    cap = get_capture(paypal_order_id)
    if cap is None:
        return
    try:
        cap.order_id = order.id
        cap.failure_reason = None
        db.session.commit()
    except Exception:
        db.session.rollback()


def cart_lines_text(cart):
    lines = []
    for item in cart or []:
        if not isinstance(item, dict):
            continue
        name = item.get('product_name') or item.get('name') or item.get('style_number')
        if not name and item.get('product_id'):
            try:
                from models import Product
                product = Product.query.get(int(item.get('product_id')))
                name = product.name if product else None
            except Exception:
                name = None
        name = name or 'Item'
        bits = [str(b) for b in (item.get('color'), item.get('size')) if b]
        design = item.get('design_title') or item.get('design_name') or ''
        if not design and item.get('design_id'):
            try:
                from models import Design
                d = Design.query.get(int(item.get('design_id')))
                design = (getattr(d, 'title', None) or getattr(d, 'sku', None) or '') if d else ''
            except Exception:
                design = ''
        qty = item.get('quantity') or 1
        price = item.get('unit_price')
        line = f'- {name}'
        if bits:
            line += ' (' + ', '.join(bits) + ')'
        if design:
            line += f', design: {design}'
        line += f' x{qty}'
        if price is not None:
            try:
                line += f' @ ${float(price):.2f}'
            except (TypeError, ValueError):
                pass
        lines.append(line)
    return '\n'.join(lines) or '(cart details were not saved)'


# ── Alerts ────────────────────────────────────────────────────────────────────

def _email_admin(subject, body):
    from flask_mail import Message
    from utils import mailer
    app = current_app._get_current_object()
    msg = Message(subject=subject, recipients=[mailer.admin_recipient(app)], body=body)
    return mailer.send(app, msg, description='payment alert')


def _notify(title, preview, body, url='', related_id=None):
    from models import db
    from utils.admin_notifications import create_notification
    try:
        create_notification(kind='payment', title=title, preview=preview, body=body,
                            url=url, related_id=related_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('could not save payment notification')


def alert_unsaved_payment(paypal_order_id, reason):
    """Paid, but no order. Email + notify the admin once per payment."""
    from models import db, PaymentCapture
    from utils.mailer import admin_base_url
    cap = get_capture(paypal_order_id)
    if cap is not None:
        if cap.order_id:
            return False
        # Claim the alert atomically so several web workers never double-send.
        try:
            claimed = (
                PaymentCapture.query
                .filter(PaymentCapture.id == cap.id, PaymentCapture.alert_sent_at.is_(None))
                .update({'alert_sent_at': datetime.utcnow(), 'failure_reason': reason},
                        synchronize_session=False)
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            claimed = 0
        if not claimed:
            return False
        db.session.refresh(cap)
    customer = {}
    cart = []
    if cap is not None:
        try:
            customer = json.loads(cap.customer_json or '{}') or {}
        except ValueError:
            customer = {}
        try:
            cart = json.loads(cap.cart_json or '[]') or []
        except ValueError:
            cart = []
    name = ' '.join(p for p in (customer.get('first_name'), customer.get('last_name')) if p) \
        or (cap.payer_name if cap else None) or 'Unknown customer'
    email = customer.get('email') or (cap.payer_email if cap else None) or 'unknown'
    amount = f'${cap.amount:.2f}' if cap is not None and cap.amount is not None else 'unknown amount'
    link = f'{admin_base_url(current_app)}/admin/orders/unsaved-payments'
    body = (
        f'{name} paid {amount} by PayPal, but the order did not save.\n\n'
        f'Customer email: {email}\n'
        f'Phone: {customer.get("phone") or "not given"}\n'
        f'Pickup or shipping: {customer.get("shipping_method") or "unknown"}\n'
        f'PayPal order ID: {paypal_order_id}\n'
        f'What went wrong: {reason}\n\n'
        f'What they were buying:\n{cart_lines_text(cart)}\n\n'
        f'Create the order with one click here: {link}\n'
    )
    _email_admin(f'Paid order needs attention: {name} ({amount})', body)
    _notify(f'Paid order did not save: {name} ({amount})', f'{reason}', body, url=link)
    return True


def alert_order_saved_with_issues(order, issues):
    """The order saved, but something about it needs a human look."""
    from utils.mailer import admin_base_url
    if not issues:
        return
    link = f'{admin_base_url(current_app)}/admin/orders/{order.id}'
    lines = '\n'.join(f'- {i}' for i in issues)
    body = (
        f'Order {order.order_number} for {order.full_name} was paid and saved, '
        f'but please check it:\n\n{lines}\n\nOpen the order: {link}\n'
    )
    _email_admin(f'Check order {order.order_number}: {order.full_name}', body)
    _notify(f'Check order {order.order_number}', issues[0], body, url=link, related_id=order.id)


# ── Background sweep ──────────────────────────────────────────────────────────

def sweep_unsaved_payments(min_age_minutes=10):
    """Alert on captures that never became an order (customer left the page)."""
    from models import PaymentCapture
    cutoff = datetime.utcnow() - timedelta(minutes=min_age_minutes)
    pending = (
        PaymentCapture.query
        .filter(PaymentCapture.order_id.is_(None))
        .filter(PaymentCapture.alert_sent_at.is_(None))
        .filter(PaymentCapture.created_at <= cutoff)
        .all()
    )
    sent = 0
    for cap in pending:
        from models import Order
        existing = Order.query.filter_by(paypal_order_id=cap.provider_ref).first()
        if existing:
            link_capture_to_order(cap.provider_ref, existing)
            continue
        if alert_unsaved_payment(
            cap.provider_ref,
            cap.failure_reason or 'The customer paid but never reached the order step (page closed or connection dropped).',
        ):
            sent += 1
    return sent


# ── Clues for recovering what a guest bought ──────────────────────────────────

def activity_near(when, minutes_before=120, minutes_after=10):
    """Shopping activity around a payment, for working out what a guest bought.

    Guest carts live only in the shopper's browser, but adding a customized
    item saves a preview picture (named by the second it was added), uploaded
    artwork is saved too, and signed-in shoppers keep their cart on file.
    """
    import os
    import time as _time
    from pathlib import Path
    from models import User, Design, CartHandoff, SiteError

    if when is None:
        return {}
    start = when - timedelta(minutes=minutes_before)
    end = when + timedelta(minutes=minutes_after)
    start_ts = int((start - datetime(1970, 1, 1)).total_seconds())
    end_ts = int((end - datetime(1970, 1, 1)).total_seconds())

    def _files(folder, prefixes):
        found = []
        base = Path(current_app.root_path) / 'static' / 'uploads' / folder
        if not base.is_dir():
            return found
        for entry in os.scandir(base):
            if not entry.is_file() or not entry.name.startswith(prefixes):
                continue
            try:
                mtime = int(entry.stat().st_mtime)
            except OSError:
                continue
            if start_ts <= mtime <= end_ts:
                found.append({
                    'url': f'/static/uploads/{folder}/{entry.name}',
                    'name': entry.name,
                    'at': datetime.utcfromtimestamp(mtime),
                })
        return sorted(found, key=lambda f: f['at'])

    clues = {
        'proofs': _files('proofs', ('proof_front_', 'proof_back_')),
        'uploads': _files('designs', ('',)),
        'carts': [],
        'designs': [],
        'handoffs': [],
        'errors': [],
    }
    try:
        for user in (User.query.filter(User.cart_updated_at >= start, User.cart_updated_at <= end).all()):
            try:
                cart = json.loads(user.cart_json or '[]') or []
            except ValueError:
                cart = []
            clues['carts'].append({'email': user.email, 'at': user.cart_updated_at,
                                   'cart': cart, 'lines': cart_lines_text(cart)})
    except Exception:
        pass
    try:
        for d in Design.query.filter(Design.uploaded_at >= start, Design.uploaded_at <= end).all():
            clues['designs'].append({'id': d.id, 'title': d.title or d.original_filename or d.filename,
                                     'at': d.uploaded_at, 'path': d.file_path})
    except Exception:
        pass
    try:
        for h in CartHandoff.query.filter(CartHandoff.created_at >= start, CartHandoff.created_at <= end).all():
            try:
                cart = json.loads(h.cart_json or '[]') or []
            except ValueError:
                cart = []
            clues['handoffs'].append({'at': h.created_at, 'cart': cart, 'lines': cart_lines_text(cart)})
    except Exception:
        pass
    try:
        for e in SiteError.query.filter(SiteError.created_at >= start, SiteError.created_at <= end).all():
            clues['errors'].append({'at': e.created_at, 'path': e.path, 'message': (e.message or '')[:200]})
    except Exception:
        pass
    return clues
