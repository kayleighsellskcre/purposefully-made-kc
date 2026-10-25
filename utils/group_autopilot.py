"""Group orders on autopilot: emails to the organizer at the right moments, so nobody has to remember.

* Weekly progress (Mondays): orders so far, items by size, days left, and the share link.
* Two days before closing: a copy-ready note the organizer can paste to parents.
* After closing: a final summary to the organizer and to the owner, with the blanks list ready.

Stores already open and close themselves on their dates. Each email is sent once per store (a timestamp on the store), and a
store that closed long ago is never emailed about, so turning this on never floods an old organizer.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import current_app

from models import Collection, GroupRosterEntry, Order, OrderItem, db
from utils.deadline_reminders import _group_key, _name_for, _plan, _share_url
from utils.group_orders import is_deadline_passed, is_not_yet_open, orders_for_collection, schedule_date_input
from utils.mailer import admin_base_url, admin_recipient
from utils.sizes import sort_sizes
from utils.sponsor_emails import _safe, _send

PROGRESS_EVERY_DAYS = 6
MIN_STORE_AGE_DAYS = 5
SUMMARY_WINDOW_DAYS = 3


def _today():
    from utils.ledger import kc_today
    return kc_today()


def deadline_day(store):
    """The Kansas City calendar day the store closes, or None."""
    if not store.order_deadline:
        return None
    return date.fromisoformat(schedule_date_input(store.order_deadline))


def days_left(store, today=None):
    day = deadline_day(store)
    return None if day is None else (day - (today or _today())).days


def size_counts(store):
    """{size: pieces} for the store: paid orders, or the roster when the organizer pays."""
    counts = {}
    if getattr(store, 'payment_mode', None) == 'organizer_pays':
        for entry in GroupRosterEntry.query.filter_by(collection_id=store.id).all():
            counts[entry.size] = counts.get(entry.size, 0) + 1
        return counts
    paid = orders_for_collection(store.id).filter(Order.payment_status == 'paid', Order.is_refunded.isnot(True)).all()
    for order in paid:
        for item in order.items:
            if (item.collection_id or order.collection_id) == store.id:
                counts[item.size or '-'] = counts.get(item.size or '-', 0) + int(item.quantity or 0)
    return counts


def sizes_text(counts):
    if not counts:
        return 'none yet'
    return ', '.join(f'{size} x{counts[size]}' for size in sort_sizes(counts.keys()))


def order_count(store):
    if getattr(store, 'payment_mode', None) == 'organizer_pays':
        return GroupRosterEntry.query.filter_by(collection_id=store.id).count()
    return orders_for_collection(store.id).filter(Order.payment_status == 'paid').count()


def _label(group, store):
    return group['labels'].get(store.id) or store.name


def _groups(stores):
    groups = {}
    for store in stores:
        key, org, label = _group_key(store)
        group = groups.setdefault(key, {'org': org, 'stores': [], 'labels': {}})
        group['stores'].append(store)
        group['labels'][store.id] = label
    return list(groups.values())


def _first(person):
    return person['first_name'] or 'there'


def _mark(stores, column):
    now = datetime.utcnow()
    for store in stores:
        setattr(store, column, now)
    db.session.commit()


def _admin():
    return (admin_recipient(current_app._get_current_object()) or '').strip().lower()


# ---- the three emails ---------------------------------------------------------------------------

def send_progress(today=None):
    """Weekly progress for stores that are open and have a few days left. Returns emails sent."""
    today = today or _today()
    sent = 0
    due = []
    for store in Collection.query.filter(Collection.is_active.is_(True), Collection.order_deadline.isnot(None)).all():
        left = days_left(store, today)
        if left is None or left < 3 or is_deadline_passed(store) or is_not_yet_open(store):
            continue
        if store.created_at and (datetime.utcnow() - store.created_at).days < MIN_STORE_AGE_DAYS:
            continue
        if store.progress_sent_at and (datetime.utcnow() - store.progress_sent_at).days < PROGRESS_EVERY_DAYS:
            continue
        due.append(store)
    for group in _groups(due):
        people, _unassigned, _admin_runs = _plan(group, _admin())
        group_sent = False
        for person in people:
            details = []
            for store in person['stores']:
                details += [(_label(group, store), f"{order_count(store)} so far, {days_left(store, today)} days left"),
                            ('Sizes', sizes_text(size_counts(store)))]
            name = _name_for(group, person['stores'])
            if _safe(_send, person['email'], f'How {name} is going', 'Your group order so far',
                     [f"Hi {_first(person)}! Here is how {name} is doing. Share the link again if you would like more orders."],
                     button={'label': 'Open the group link', 'url': _share_url(current_app._get_current_object(), group, person['stores'])},
                     details=details):
                sent += 1
                group_sent = True
        if group_sent:
            _mark(group['stores'], 'progress_sent_at')
    return sent


def send_two_day(today=None):
    """Two days before a store closes: a note the organizer can paste to parents. Returns emails sent."""
    today = today or _today()
    sent = 0
    due = [s for s in Collection.query.filter(Collection.is_active.is_(True), Collection.order_deadline.isnot(None)).all()
           if days_left(s, today) == 2 and not s.two_day_sent_at and not is_not_yet_open(s)]
    for group in _groups(due):
        people, _unassigned, _admin_runs = _plan(group, _admin())
        group_sent = False
        for person in people:
            name = _name_for(group, person['stores'])
            closes = deadline_day(person['stores'][0])
            url = _share_url(current_app._get_current_object(), group, person['stores'])
            copy = (f"Reminder: orders for {name} close on {closes.strftime('%A, %B')} {closes.day}. "
                    f"Order here before then: {url}")
            if _safe(_send, person['email'], f'Two days left: {name}', 'Two days to go',
                     [f"Hi {_first(person)}! Orders for {name} close in two days. Here is a note you can copy and send to your group:", copy],
                     button={'label': 'Open the group link', 'url': url}):
                sent += 1
                group_sent = True
        if group_sent:
            _mark(group['stores'], 'two_day_sent_at')
    return sent


def send_closed_summary(today=None):
    """After a store closes: the final numbers to the organizer, and the owner with the blanks list. Returns emails sent."""
    today = today or _today()
    sent = 0
    cutoff = today - timedelta(days=SUMMARY_WINDOW_DAYS)
    due = [s for s in Collection.query.filter(Collection.order_deadline.isnot(None), Collection.closed_summary_sent_at.is_(None)).all()
           if is_deadline_passed(s) and deadline_day(s) >= cutoff]
    app = current_app._get_current_object()
    for group in _groups(due):
        people, _unassigned, _admin_runs = _plan(group, _admin())
        group_sent = False
        total = sum(order_count(s) for s in group['stores'])
        if total:
            for person in people:
                details = []
                for store in person['stores']:
                    details += [(_label(group, store), f"{order_count(store)} orders"), ('Sizes', sizes_text(size_counts(store)))]
                name = _name_for(group, person['stores'])
                if _safe(_send, person['email'], f'{name} is closed', 'Your group order is closed',
                         [f"Hi {_first(person)}! Ordering for {name} has closed, and Kayleigh is getting your pieces ready. "
                          "We will let you know when they are ready for pickup."], details=details):
                    sent += 1
                    group_sent = True
        details = []
        for store in group['stores']:
            details += [(_label(group, store), f"{order_count(store)} orders"), ('Sizes', sizes_text(size_counts(store)))]
        first_store = group['stores'][0]
        name = _name_for(group, group['stores'])
        link = f"{admin_base_url(app)}/admin/production/blank-apparel-list?collection={first_store.id}"
        if _safe(_send, admin_recipient(app), f'Closed: {name} ({total} orders)', f'{name} just closed',
                 [f"{name} closed with {total} order{'s' if total != 1 else ''}. The blanks list for it is ready whenever you are."],
                 button={'label': 'Open the blanks list', 'url': link}, details=details):
            sent += 1
            group_sent = True
        if group_sent:
            _mark(group['stores'], 'closed_summary_sent_at')
    return sent


def run_all(today=None):
    """What the daily job does: the two-day note and closing summary every day, progress on Mondays."""
    today = today or _today()
    return {'progress': send_progress(today) if today.weekday() == 0 else 0, 'two_day': send_two_day(today),
            'closed': send_closed_summary(today)}
