"""Track my order without logging in: order number plus the email on the order.

Everything here is read-only. A wrong number and a wrong email give the same answer, so the page can never be
used to find out which orders or emails exist.
"""
from __future__ import annotations

import re

from models import Order, db

# Where an order is: index into the four steps a customer sees
_RECEIVED, _MAKING, _READY, _DONE = 0, 1, 2, 3


def clean_number(raw):
    """"pmkc-2026 1025ab12" and "PMKC20261025AB12" are the same number."""
    return re.sub(r'[^A-Za-z0-9]', '', raw or '').upper()


def find_order(number, email):
    """The order when the number and the email both match, else None."""
    number, email = clean_number(number), (email or '').strip().lower()
    if not number or '@' not in email:
        return None
    order = Order.query.filter(
        db.func.replace(db.func.replace(db.func.upper(Order.order_number), '-', ''), ' ', '') == number).first()
    if order is None:
        return None
    emails = {(order.email or '').strip().lower()}
    if order.user is not None:
        emails.add((order.user.email or '').strip().lower())
    return order if email in emails else None


def _method(order):
    return (order.fulfillment_method or 'pickup').lower()


def progress(order):
    """Index of the step the order is on, or None for a cancelled order."""
    status = (order.status or '').lower()
    stage = (order.production_stage or '').lower()
    if status == 'cancelled':
        return None
    if status in ('completed', 'shipped', 'picked_up'):
        return _DONE
    if status == 'ready' or stage == 'packaged_ready':
        return _READY
    if status == 'in_production' or stage in ('ready_to_press', 'pressed'):
        return _MAKING
    return _RECEIVED


def step_labels(order):
    shipping = _method(order) == 'shipping'
    if order.send_home_with_child:
        return ['Order received', 'Being made', 'Ready, going home with your child', 'Sent home']
    if shipping:
        return ['Order received', 'Being made', 'Packed and ready to ship', 'Shipped']
    return ['Order received', 'Being made', 'Ready for pickup', 'Picked up']


def steps(order):
    """[{label, state}] where state is done, current or upcoming."""
    at = progress(order)
    out = []
    for i, label in enumerate(step_labels(order)):
        if at is None:
            state = 'upcoming'
        elif at == _DONE:
            state = 'done'
        else:
            state = 'done' if i < at else ('current' if i == at else 'upcoming')
        out.append({'label': label, 'state': state})
    return out


def summary(order):
    """Everything the tracking page shows for one order."""
    from utils.customer_emails import _pickup_lines, tracking_url
    from utils.group_orders import is_deadline_passed
    at = progress(order)
    shipping = _method(order) == 'shipping'
    info = {'order': order, 'steps': steps(order), 'cancelled': at is None, 'headline': '', 'details': [],
            'tracking_url': None}
    coll = getattr(order, 'collection', None)
    if at is None:
        info['headline'] = 'This order was cancelled. If that is a surprise, just reply to any email from us.'
        return info
    if at == _DONE:
        info['headline'] = ('Your order has shipped.' if shipping and not order.send_home_with_child
                            else 'Your order is complete. Thank you!')
    elif at == _READY:
        info['headline'] = 'Your order is ready.' if not shipping else 'Your order is packed and about to ship.'
    elif at == _MAKING:
        info['headline'] = 'We are making your order now.'
    else:
        info['headline'] = 'We have your order and will start on it soon.'
        if coll is not None and coll.order_deadline and not is_deadline_passed(coll):
            info['details'].append(('Note', f'Your group order closes {coll.order_deadline.strftime("%B")} '
                                            f'{coll.order_deadline.day}. We start printing after it closes.'))
    if order.due_date and at < _READY:
        info['details'].append(('Estimated ready date', f'{order.due_date.strftime("%B")} {order.due_date.day}'))
    if order.send_home_with_child and order.child_name and at >= _READY:
        info['details'].append(('Going home with', order.child_name))
    elif at == _READY and not shipping:
        address, notes = _pickup_lines(order)
        if address:
            info['details'].append(('Pickup address', address))
        if notes:
            info['details'].append(('Pickup details', notes))
    if shipping and order.tracking_number and at >= _READY:
        info['details'].append(('Tracking', f'{order.carrier + " " if order.carrier else ""}{order.tracking_number}'))
        info['tracking_url'] = tracking_url(order.carrier, order.tracking_number)
    return info
