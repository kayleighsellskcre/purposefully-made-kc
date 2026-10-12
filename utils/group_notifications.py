"""Tell the admin every time someone sets up a group order.

Two things happen, both on the spot: a "New group order" item lands in the admin
inbox, and an email goes to the admin with who set it up, the dates, who can
see it and a direct link. A mail problem is logged and swallowed: it must never
get in the way of someone creating their group.
"""
from flask import render_template
from flask_mail import Message

from utils.admin_notifications import create_notification
from utils.group_orders import schedule_date_input
from utils.mailer import admin_base_url, admin_recipient, reply_to, send

KIND_GROUP_ORDER = 'group_order'

_KINDS = {'school': 'School', 'team': 'Team or club', 'other': 'Other group'}


def _person(user):
    if user is None:
        return None, None
    name = ' '.join(filter(None, [getattr(user, 'first_name', None), getattr(user, 'last_name', None)])).strip()
    return (name or None), (getattr(user, 'email', None) or None)


def _nice_date(dt):
    """'October 15, 2026' in Kansas City time, or None."""
    from datetime import datetime
    day = schedule_date_input(dt) if dt else ''
    if not day:
        return None
    d = datetime.strptime(day, '%Y-%m-%d')
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _visibility(collection):
    if collection.is_password_protected:
        return 'Password protected'
    return 'Public (listed on Group Orders)' if collection.show_in_directory else 'Link only'


def _details(app, collection, creator, team_names):
    from utils.group_roster import payment_mode_label
    base = admin_base_url(app)
    name, email = _person(creator)
    organizer = (collection.pending_organizer_email or '').strip() or None
    return {
        'group_name': collection.name,
        'kind': _KINDS.get(collection.group_kind or '', 'Group'),
        'created_by': name or email or 'Someone',
        'created_by_email': email,
        'organizer_email': organizer,
        'payment': payment_mode_label(collection),
        'opens': _nice_date(collection.order_opens_at),
        'deadline': _nice_date(collection.order_deadline),
        'visibility': _visibility(collection),
        'teams': list(team_names or []),
        'store_url': f"{base}/c/{collection.slug}",
        'admin_url': f"{base}/admin/collections/{collection.id}/edit",
    }


def _plain(d):
    lines = [
        f"NEW GROUP ORDER: {d['group_name']}",
        '',
        f"Set up by   : {d['created_by']}" + (f" <{d['created_by_email']}>" if d['created_by_email'] else ''),
        f"Type        : {d['kind']}",
        f"Payment     : {d['payment']}",
        f"Opens       : {d['opens'] or 'Right away'}",
        f"Deadline    : {d['deadline'] or 'No deadline'}",
        f"Who sees it : {d['visibility']}",
    ]
    if d['organizer_email']:
        lines.append(f"Organizer   : {d['organizer_email']} (invited by email)")
    if d['teams']:
        lines.append('Teams       : ' + ', '.join(d['teams']))
    lines += ['', f"Store link  : {d['store_url']}", f"Edit in admin: {d['admin_url']}"]
    return '\n'.join(lines)


def notify_group_created(app, collection, creator, team_names=None):
    """Admin inbox item + email for one new group order. Never raises."""
    try:
        d = _details(app, collection, creator, team_names)
        summary = f"{d['kind']} · {d['payment']} · " + (f"closes {d['deadline']}" if d['deadline'] else 'no deadline')
        if d['teams']:
            summary = f"{len(d['teams'])} teams ({', '.join(d['teams'])}) · " + summary
        create_notification(
            kind=KIND_GROUP_ORDER,
            title=f"New group order: {d['group_name']}",
            preview=summary,
            body=_plain(d),
            from_name=d['created_by'],
            from_email=d['created_by_email'] or '',
            url=f"/admin/collections/{collection.id}/edit",
            related_id=collection.id,
        )
    except Exception:
        app.logger.exception('could not add the new-group notification for %s', getattr(collection, 'id', '?'))
    try:
        d = _details(app, collection, creator, team_names)
        with app.test_request_context(base_url=admin_base_url(app)):
            html = render_template('email/group_created_admin.html', **d)
        msg = Message(
            subject=f"New group order: {d['group_name']}",
            recipients=[admin_recipient(app)],
            body=_plain(d),
            html=html,
            reply_to=d['created_by_email'] or reply_to(app),
        )
        return send(app, msg, description=f"new group order alert for {d['group_name']}")
    except Exception:
        app.logger.exception('could not email the new-group alert for %s', getattr(collection, 'id', '?'))
        return False
