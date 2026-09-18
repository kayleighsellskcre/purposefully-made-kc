"""Admin inbox for contact-form messages and design requests — not orders."""
from __future__ import annotations

from datetime import datetime

from models import AdminNotification, CustomDesignRequest, db

KIND_CONTACT = 'contact'
KIND_DESIGN_REQUEST = 'design_request'


def _preview(text, limit=180):
    cleaned = ' '.join((text or '').split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + '…'


def create_notification(*, kind, title, preview='', body='', from_name='',
                        from_email='', url='', related_id=None, commit=True):
    note = AdminNotification(
        kind=kind,
        title=(title or 'Notification')[:200],
        preview=_preview(preview) or None,
        body=body or None,
        from_name=(from_name or '')[:200] or None,
        from_email=(from_email or '')[:120] or None,
        url=(url or '')[:300] or None,
        related_id=related_id,
    )
    db.session.add(note)
    if commit:
        db.session.commit()
    return note


def notify_contact_message(name, email, subject, message):
    """Store a contact-form submission in the admin inbox."""
    title = f'Message from {name or "someone"}'
    preview = subject or message
    return create_notification(
        kind=KIND_CONTACT,
        title=title,
        preview=preview,
        body=message,
        from_name=name,
        from_email=email,
        related_id=None,
    )


def notify_design_request(req, customer_name, commit=True):
    """Store a recreate-request alert in the admin inbox."""
    name = customer_name or 'a customer'
    return create_notification(
        kind=KIND_DESIGN_REQUEST,
        title=f'Design request from {name}',
        preview=req.description or '',
        from_name=name,
        url=f'/admin/custom-design-requests/{req.id}',
        related_id=req.id,
        commit=commit,
    )


def unread_count():
    return (
        AdminNotification.query
        .filter(AdminNotification.read_at.is_(None))
        .count()
    )


def mark_read(note):
    if note and note.read_at is None:
        note.read_at = datetime.utcnow()


def mark_all_read():
    now = datetime.utcnow()
    (
        AdminNotification.query
        .filter(AdminNotification.read_at.is_(None))
        .update({AdminNotification.read_at: now}, synchronize_session=False)
    )
    db.session.commit()


def backfill_pending_design_requests():
    """Pending recreate requests from before this inbox still get a bell."""
    existing = {
        row[0]
        for row in db.session.query(AdminNotification.related_id)
        .filter(
            AdminNotification.kind == KIND_DESIGN_REQUEST,
            AdminNotification.related_id.isnot(None),
        )
        .all()
    }
    pending = CustomDesignRequest.query.filter_by(status='pending').all()
    created = False
    for req in pending:
        if req.id in existing:
            continue
        name = (req.user.full_name if req.user else None) or 'Customer'
        notify_design_request(req, name, commit=False)
        created = True
    if created:
        db.session.commit()
    return created
