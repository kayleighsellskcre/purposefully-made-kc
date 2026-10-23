"""Caring emails to customers as their order moves along, and the review request that follows.

* Ready: pickup (with the address), sent home with a child (named teacher or coach), or handed to a group organizer.
* Shipped: with tracking when we have it.
* Review request: once, 15 days after the order was completed.

Each email is claimed in the database before it is sent (the same way receipts are), so a double click or two
workers can never send one twice. Nothing is sent for orders finished before this feature existed, because
only orders that reach a finished stage afterwards get a completion time.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from flask import current_app, url_for

from models import Order, db

REVIEW_DELAY_DAYS = 15
FLAG_KEY = 'customer_status_emails'
PICKUP_ADDRESS_KEY = 'pickup_address'
PICKUP_NOTES_KEY = 'pickup_notes'


def _send(*args, **kwargs):
    from utils.sponsor_emails import _send as send
    return send(*args, **kwargs)


def _first_name(order):
    return (order.first_name or '').strip() or 'there'


def _base_url():
    return (current_app.config.get('ADMIN_BASE_URL') or 'https://purposefullymadekc.com').rstrip('/')


def _pickup_lines(order):
    """(address, notes) for this order: the group's own pickup spot when it has one, else the shop's."""
    from utils.group_orders import _pickup_text
    from utils.site_settings import get_setting
    coll = getattr(order, 'collection', None)
    notes, address = _pickup_text(coll)
    if address or notes:
        return address, notes
    from utils.business_info import BUSINESS
    return (get_setting(PICKUP_ADDRESS_KEY, '').strip() or BUSINESS['pickup_address'],
            get_setting(PICKUP_NOTES_KEY, '').strip())


def _order_details(order):
    return [('Order', order.order_number)]


def ready_email(order):
    """(subject, heading, paragraphs, details) for an order that is packaged and ready, or None to send nothing."""
    from utils.group_orders import group_uses_organizer_fulfillment
    name = _first_name(order)
    details = _order_details(order)
    if (order.fulfillment_method or '').lower() == 'shipping':
        return None                                     # shipping orders hear from us when they ship
    if order.send_home_with_child and order.child_name:
        who = (order.teacher_name or '').strip()
        hand = f' We are passing it to {who}, who will send it home with {order.child_name}.' if who \
            else f' It will come home with {order.child_name}.'
        details += [('Going home with', order.child_name)]
        if who:
            details += [('Given to', who)]
        if order.child_grade:
            details += [('Grade', order.child_grade)]
        return (f'Your order is ready and headed home with {order.child_name}',
                'Ready and on its way home',
                [f'Hi {name}, your order is finished and packed with care.' + hand,
                 'There is nothing you need to do. If anything looks off when it arrives, just reply to this email and we will make it right.'],
                details)
    coll = getattr(order, 'collection', None)
    address, notes = _pickup_lines(order)
    if group_uses_organizer_fulfillment(coll) and not address:
        return ('Your order is ready',
                'Your order is ready',
                [f'Hi {name}, your order is finished and packed with care. We are getting it to your group organizer, '
                 'who will make sure it reaches you.',
                 'If you have any questions about when it will be handed out, just reply to this email.'],
                details)
    paragraphs = [f'Hi {name}, your order is finished and packed with care. It is ready for you to pick up.']
    if address:
        details += [('Pickup address', address)]
    if notes:
        details += [('Pickup details', notes)]
    if not address and not notes:
        paragraphs.append('Just reply to this email and we will send you the pickup details and a good time to stop by.')
    return ('Your order is ready for pickup', 'Ready for pickup', paragraphs, details)


def shipped_email(order):
    name = _first_name(order)
    details = _order_details(order)
    if order.tracking_number:
        details += [('Tracking', f'{order.carrier + " " if order.carrier else ""}{order.tracking_number}')]
    addr = ', '.join(p for p in (order.shipping_street, order.shipping_city, order.shipping_state, order.shipping_zip) if p)
    if addr:
        details += [('Shipping to', addr)]
    paragraphs = [f'Hi {name}, your order is finished and on its way to you.']
    paragraphs.append('Your tracking number is below.' if order.tracking_number
                      else 'We will email your tracking number as soon as we have it.')
    return ('Your order is on its way', 'On its way to you', paragraphs, details)


def completed_email(order):
    name = _first_name(order)
    return ('Your order is complete', 'Your order is complete',
            [f'Hi {name}, your order is complete. Thank you for letting us make it for you.',
             'If anything is not right, just reply to this email and we will fix it.'],
            _order_details(order))


def _claim(order_id, column):
    """Mark an email as sent before sending. True only for the one caller that wins."""
    claimed = (Order.query.filter(Order.id == order_id, column.is_(None))
               .update({column: datetime.utcnow()}, synchronize_session=False))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    return bool(claimed)


TRACK_URLS = {
    'USPS': 'https://tools.usps.com/go/TrackConfirmAction?tLabels={n}',
    'UPS': 'https://www.ups.com/track?tracknum={n}',
    'FEDEX': 'https://www.fedex.com/fedextrack/?trknbr={n}',
}


def tracking_url(carrier, number):
    template = TRACK_URLS.get((carrier or '').strip().upper())
    return template.format(n=''.join(ch for ch in (number or '') if ch.isalnum())) if template else None


def send_tracking_email(order):
    """Tell the customer their tracking number (with a track-it link for USPS, UPS and FedEx)."""
    from utils.site_settings import get_flag
    if not get_flag(FLAG_KEY, True) or not (order.email or '').strip() or not order.tracking_number:
        return False
    url = tracking_url(order.carrier, order.tracking_number)
    name = _first_name(order)
    return _send(
        order.email.strip(), 'Tracking for your order', 'Here is your tracking number',
        [f'Hi {name}, your order is on its way. Here is the tracking number so you can follow it home.'],
        button={'label': 'Track your package', 'url': url} if url else None,
        details=_order_details(order) + [('Tracking', f'{order.carrier + " " if order.carrier else ""}{order.tracking_number}')],
        note='Carriers can take a few hours to show movement after a label is made.')


def notify_stage_change(order_id, stage):
    """Send the right email for a stage the admin just moved an order to. Never raises."""
    try:
        from utils.site_settings import get_flag
        if not get_flag(FLAG_KEY, True):
            return False
        order = db.session.get(Order, order_id)
        if order is None or not (order.email or '').strip() or order.status == 'cancelled':
            return False
        # Finishing a shipping order lands on "shipped", a pickup order on "picked up": go by where it ended up.
        landed = order.status if stage in ('completed', 'shipped', 'picked_up') else stage
        if landed == 'packaged_ready':
            column, content = Order.ready_notified_at, ready_email
        elif landed == 'shipped':
            column, content = Order.completed_notified_at, shipped_email
        elif landed == 'completed':
            column, content = Order.completed_notified_at, completed_email
        else:
            return False                                 # picked up: they already know
        built = content(order)
        if built is None or not _claim(order.id, column):
            return False
        subject, heading, paragraphs, details = built
        return _send(order.email.strip(), subject, heading, paragraphs, details=details,
                     note='Thank you for choosing a small local business.')
    except Exception:
        current_app.logger.exception('order status email failed for order %s', order_id)
        return False


def notify_in_background(order_ids, stage):
    """Send after the admin's page has been answered, so clicking a button never waits on email."""
    ids = [i for i in order_ids if i]
    if not ids:
        return
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            for oid in ids:
                notify_stage_change(oid, stage)

    if app.config.get('TESTING'):
        run()
    else:
        from threading import Thread
        Thread(target=run, daemon=True).start()


# ---- review requests --------------------------------------------------------------------------

def review_url(order):
    return f'{_base_url()}/review/{order.review_token}'


def send_review_request(order):
    """Email the review link (once). The link is private to this order."""
    from utils.site_settings import get_flag
    if not get_flag(FLAG_KEY, True) or not (order.email or '').strip():
        return False
    if not _claim(order.id, Order.review_email_sent_at):
        return False
    order = db.session.get(Order, order.id)
    if not order.review_token:
        order.review_token = secrets.token_urlsafe(24)
        db.session.commit()
    name = _first_name(order)
    return _send(
        order.email.strip(), 'How is your order treating you?', 'We would love to hear from you',
        [f'Hi {name}, it has been a couple of weeks since your order, and we hope you are loving it.',
         'If you have a minute, would you tell us how it turned out? A few kind words mean the world to a small shop like ours.',
         'And please feel free to take photos of you wearing your items and upload them. We would love to show people how great everyone looks!'],
        button={'label': 'Share your thoughts and photos', 'url': review_url(order)},
        details=_order_details(order),
        note='There is no pressure and no account needed. We read every note ourselves.')


def due_review_orders(now=None):
    cutoff = (now or datetime.utcnow()) - timedelta(days=REVIEW_DELAY_DAYS)
    return (Order.query
            .filter(Order.completed_at.isnot(None), Order.completed_at <= cutoff,
                    Order.review_email_sent_at.is_(None), Order.email.isnot(None),
                    Order.status.in_(['completed', 'shipped', 'picked_up']))
            .order_by(Order.completed_at).limit(100).all())


def send_due_review_requests(now=None):
    """Called every morning. Returns how many emails went out."""
    sent = 0
    for order in due_review_orders(now):
        try:
            if send_review_request(order):
                sent += 1
        except Exception:
            current_app.logger.exception('review request failed for order %s', order.id)
    return sent
