"""Morning-of-the-deadline reminder emails for group orders.

On the day a group order closes, each organizer gets a nudge to remind their
group, and the admin gets a heads-up with the numbers.

* An organizer only ever hears about the group (or the teams) they run.
* A multi-team organization is ONE group: its organizer gets one email listing
  their teams, never one per team. If different people run different teams,
  each gets only their own.
* With no organizer on file (or the admin is the organizer), the admin alone is
  reminded.
* Each store remembers the day its reminder went out, so running this more than
  once on the same morning (a late deploy, an hourly retry) never sends twice.
"""
from datetime import datetime
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


def _store_contacts(store, org):
    """[(email, first_name)] for whoever runs this store (falls back to the organization's organizer)."""
    found = []

    def add(email, name=None):
        email = (email or '').strip()
        if email and email.lower() not in {e.lower() for e, _ in found}:
            found.append((email, (name or '').strip() or None))

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


def _plan(group, admin_email):
    """Who hears about what: ({email: person}, stores with no organizer, stores the admin runs)."""
    people, unassigned, admin_runs = {}, [], []
    for store in group['stores']:
        contacts = _store_contacts(store, group['org'])
        others = [c for c in contacts if c[0].lower() != admin_email]
        if not contacts:
            unassigned.append(store)
        elif not others:
            admin_runs.append(store)
        for email, first_name in others:
            person = people.setdefault(email.lower(), {'email': email, 'first_name': first_name, 'stores': []})
            person['stores'].append(store)
    return list(people.values()), unassigned, admin_runs


def _labels(group, stores):
    return [group['labels'].get(s.id) or s.name for s in stores]


def _name_for(group, stores):
    """Group name; for someone who runs only some teams of an organization, just those teams."""
    if group['org'] is None:
        return group['stores'][0].name
    if len(stores) == len(group['stores']):
        return group['org'].name
    return f"{group['org'].name}: {' & '.join(_labels(group, stores))}"


def _share_url(app, group, stores):
    base = admin_base_url(app)
    if group['org'] is None:
        return f"{base}/c/{group['stores'][0].slug}"
    if len(stores) == 1 and len(group['stores']) > 1:
        return f"{base}/c/{stores[0].slug}"
    return f"{base}/org/{group['org'].slug}"


def _rows(group, stores):
    rows = []
    for store in stores:
        n, noun = _count(store)
        rows.append({'name': group['labels'].get(store.id) or store.name, 'count': n, 'noun': noun})
    return rows


def _organizer_message(app, group, person):
    stores = person['stores']
    name = _name_for(group, stores)
    url = _share_url(app, group, stores)
    rows = _rows(group, stores)
    first_name = person['first_name']
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
        recipients=[person['email']], body=plain, html=html, reply_to=reply_to(app),
    )


def _admin_note(group, people, unassigned, admin_runs):
    multi = group['org'] is not None
    parts = []
    if people:
        if multi:
            parts.append('Organizers emailed: ' + '; '.join(
                f"{p['email']} ({', '.join(_labels(group, p['stores']))})" for p in people) + '.')
        else:
            parts.append('The organizer was emailed: ' + ', '.join(p['email'] for p in people) + '.')
    if admin_runs:
        which = f" for {', '.join(_labels(group, admin_runs))}" if multi else ''
        parts.append(f"You are the organizer{which}, so that reminder is for you. Please remind your group today.")
    if unassigned:
        which = f" for {', '.join(_labels(group, unassigned))}" if multi else ' for this group'
        parts.append(f"No organizer email is on file{which}, so only you were reminded. "
                     "You may want to nudge them yourself.")
    return ' '.join(parts)


def _admin_message(app, group, people, unassigned, admin_runs):
    stores = group['stores']
    name = _name_for(group, stores)
    url = _share_url(app, group, stores)
    rows = _rows(group, stores)
    admin_url = f"{admin_base_url(app)}/admin/collections"
    note = _admin_note(group, people, unassigned, admin_runs)
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
    """Email the organizer(s) and the admin for every group closing today.

    Returns {'groups': n, 'emails': n}. Safe to run repeatedly: a store that was
    reminded today is skipped. A group is only marked once at least one email for
    it actually went out, so a mail outage retries on the next run.
    """
    admin_email = (admin_recipient(app) or '').strip().lower()
    summary = {'groups': 0, 'emails': 0}
    for group in due_groups(today):
        people, unassigned, admin_runs = _plan(group, admin_email)
        sent_any = False
        for person in people:
            if send(app, _organizer_message(app, group, person),
                    description=f"deadline reminder to organizer {person['email']}"):
                summary['emails'] += 1
                sent_any = True
        if send(app, _admin_message(app, group, people, unassigned, admin_runs),
                description=f"deadline reminder to admin for {_name_for(group, group['stores'])}"):
            summary['emails'] += 1
            sent_any = True
        if sent_any:
            summary['groups'] += 1
            now = datetime.utcnow()
            for store in group['stores']:
                store.deadline_reminder_sent_at = now
            db.session.commit()
    return summary
