"""Morning-of-the-deadline reminder emails for group orders.

On the day a group order closes, the organizer gets a nudge to remind their
group, and the admin gets a heads-up with the numbers. A multi-team
organization is ONE group: one email each, listing every team, never one per
team. Each store remembers the day its reminder went out, so running this
more than once on the same morning (a late deploy, an hourly retry) can never
send it twice.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from flask import render_template
from flask_mail import Message

from models import db, Collection, GroupRosterEntry, Order, OrgSection
from utils.group_orders import schedule_date_input
from utils.mailer import admin_base_url, admin_recipient, reply_to, send

CHICAGO = ZoneInfo('America/Chicago')


def _render(app, template, **context):
    """Render with a request context: this runs from a background thread."""
    with app.test_request_context(base_url=admin_base_url(app)):
        return render_template(template, **context)


def _kc_today():
    return datetime.now(CHICAGO).date()


def _store_due(collection, today_str):
    """True when this store closes today (Kansas City time) and has not been reminded yet."""
    if not collection.is_active or not collection.order_deadline:
        return False
    if schedule_date_input(collection.order_deadline) != today_str:
        return False
    sent = collection.deadline_reminder_sent_at
    return not (sent and schedule_date_input(sent) == today_str)


def _group_key(collection):
    """('org', id) for a store inside an active organization, else ('store', id)."""
    section = OrgSection.query.filter_by(collection_id=collection.id).first()
    org = section.organization if section else None
    if org is not None and org.is_active:
        return ('org', org.id), org, (section.label or collection.name)
    return ('store', collection.id), None, collection.name


def _organizer_contacts(stores, org):
    """[(email, first_name)] for the people who run this group, without duplicates."""
    found = []

    def add(email, name=None):
        email = (email or '').strip()
        if email and email.lower() not in {e.lower() for e, _ in found}:
            found.append((email, (name or '').strip() or None))

    for store in stores:
        if store.created_by is not None:
            add(store.created_by.email, store.created_by.first_name)
        add(store.pending_organizer_email)
    if not found and org is not None:
        if org.created_by is not None:
            add(org.created_by.email, org.created_by.first_name)
        add(org.pending_organizer_email)
    return found


def _count(store):
    if getattr(store, 'payment_mode', None) == 'organizer_pays':
        n = GroupRosterEntry.query.filter_by(collection_id=store.id).count()
        return n, 'size' if n == 1 else 'sizes'
    n = Order.query.filter_by(collection_id=store.id).count()
    return n, 'order' if n == 1 else 'orders'


def due_groups(today=None):
    """Groups whose deadline is today and who have not been reminded yet."""
    today = today or _kc_today()
    today_str = today.strftime('%Y-%m-%d')
    stores = Collection.query.filter(
        Collection.is_active == True,  # noqa: E712
        Collection.order_deadline.isnot(None),
    ).all()
    groups = {}
    for store in stores:
        if not _store_due(store, today_str):
            continue
        key, org, label = _group_key(store)
        group = groups.setdefault(key, {'org': org, 'stores': [], 'labels': {}})
        group['stores'].append(store)
        group['labels'][store.id] = label
    return list(groups.values())


def _share_url(app, group):
    base = admin_base_url(app)
    if group['org'] is not None:
        return f"{base}/org/{group['org'].slug}"
    return f"{base}/c/{group['stores'][0].slug}"


def _group_name(group):
    return group['org'].name if group['org'] is not None else group['stores'][0].name


def _rows(group):
    rows = []
    for store in group['stores']:
        n, noun = _count(store)
        rows.append({'name': group['labels'].get(store.id) or store.name, 'count': n, 'noun': noun,
                     'id': store.id})
    return rows


def _organizer_message(app, group, email, first_name):
    name = _group_name(group)
    url = _share_url(app, group)
    rows = _rows(group)
    plain = (
        f"Hi {first_name or 'there'},\n\n"
        f"Today is the last day to order for {name}.\n"
        f"Orders close tonight at 11:59 PM Central.\n\n"
        f"Please remind your group today. Anyone who has not ordered yet needs to do it before tonight.\n"
        f"Here is the link to share:\n{url}\n\n"
        + ''.join(f"  - {r['name']}: {r['count']} {r['noun']} so far\n" for r in rows)
        + "\nQuestions? Just reply to this email.\n\n"
          "Made with purpose, for you.\n— Purposefully Made KC"
    )
    html = _render(app, 'email/deadline_reminder.html', audience='organizer', group_name=name,
                   share_url=url, rows=rows, first_name=first_name, multi=group['org'] is not None,
                   admin_url=None, organizer_note=None)
    return Message(
        subject=f"Last day to order: {name}",
        recipients=[email], body=plain, html=html, reply_to=reply_to(app),
    )


def _admin_message(app, group, organizer_emails, you_are_organizer=False):
    name = _group_name(group)
    url = _share_url(app, group)
    rows = _rows(group)
    admin_url = f"{admin_base_url(app)}/admin/collections"
    if organizer_emails:
        note = 'The organizer was emailed: ' + ', '.join(organizer_emails) + '.'
    elif you_are_organizer:
        note = 'You are the organizer of this group, so this one reminder is for you. Please remind your group today.'
    else:
        note = 'No organizer email is on file for this group, so only you were reminded. You may want to nudge them yourself.'
    total = sum(r['count'] for r in rows)
    plain = (
        f"DEADLINE TODAY: {name}\n\n"
        f"Orders close tonight at 11:59 PM Central.\n"
        f"{note}\n\n"
        + ''.join(f"  - {r['name']}: {r['count']} {r['noun']} so far\n" for r in rows)
        + f"\nPublic link: {url}\nGroup orders in admin: {admin_url}\n"
    )
    html = _render(app, 'email/deadline_reminder.html', audience='admin', group_name=name,
                   share_url=url, rows=rows, first_name=None, multi=group['org'] is not None,
                   admin_url=admin_url, organizer_note=note)
    return Message(
        subject=f"Deadline today: {name} ({total} so far)",
        recipients=[admin_recipient(app)], body=plain, html=html, reply_to=reply_to(app),
    )


def send_deadline_reminders(app, today=None):
    """Email the organizer and the admin for every group closing today.

    Returns {'groups': n, 'emails': n}. Safe to run repeatedly: a store that was
    reminded today is skipped. A store is only marked once at least one email
    for its group actually went out, so a mail outage retries on the next run.
    """
    admin_email = (admin_recipient(app) or '').strip().lower()
    summary = {'groups': 0, 'emails': 0}
    for group in due_groups(today):
        everyone = _organizer_contacts(group['stores'], group['org'])
        contacts = [c for c in everyone if c[0].lower() != admin_email]
        you_are_organizer = bool(everyone) and not contacts
        sent_any = False
        for email, first_name in contacts:
            if send(app, _organizer_message(app, group, email, first_name),
                    description=f"deadline reminder to organizer {email}"):
                summary['emails'] += 1
                sent_any = True
        if send(app, _admin_message(app, group, [e for e, _ in contacts], you_are_organizer),
                description=f"deadline reminder to admin for {_group_name(group)}"):
            summary['emails'] += 1
            sent_any = True
        if sent_any:
            summary['groups'] += 1
            now = datetime.utcnow()
            for store in group['stores']:
                store.deadline_reminder_sent_at = now
            db.session.commit()
    return summary
