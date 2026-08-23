"""Emails for the "Have Us Recreate It" design-request flow.

Before this existed a design request produced only an SMS to the owner: the
customer got no written confirmation, and there was no emailed record of the
request with the artwork attached.

Both messages are sent as a pair and stamped on the request row, so a refresh
or a repeated submit cannot send them twice.
"""
from datetime import datetime

from flask import render_template
from flask_mail import Message

from models import db, CustomDesignRequest
from utils.mailer import admin_base_url, admin_recipient, reply_to, send

RESPONSE_TIME = 'within 1–2 business days'


def _render(app, template, **context):
    """Render with a request context, since this runs from a background thread."""
    with app.test_request_context(base_url=admin_base_url(app)):
        return render_template(template, **context)


def _reference_url(app, req):
    path = req.reference_file_path or ''
    if path.startswith('http'):
        return path
    if not path:
        return None
    return f'{admin_base_url(app)}/static/{path.lstrip("/")}'


def _customer_message(app, req, customer_name, recipient):
    submitted = req.created_at or datetime.utcnow()
    plain = (
        f"Hi {customer_name},\n\n"
        f"We received your custom design request. Here's what you sent us:\n\n"
        f"Request number : #{req.id}\n"
        f"Submitted       : {submitted.strftime('%B %d, %Y at %I:%M %p')} UTC\n"
        f"Reference file  : {req.reference_original_filename or 'your uploaded image'}\n\n"
        f"What you asked for:\n{req.description}\n\n"
        f"We'll review it and get back to you {RESPONSE_TIME}. Once your design "
        f"is ready it will appear under My Designs in your account, and you can "
        f"put it on any garment in the shop.\n\n"
        f"Questions? Just reply to this email or reach us at "
        f"purposefullymadekc@gmail.com\n\n"
        f"Made with purpose, for you.\n"
        f"— Purposefully Made KC"
    )
    html = _render(
        app, 'email/design_request_customer.html',
        req=req, customer_name=customer_name, submitted=submitted,
        response_time=RESPONSE_TIME,
        my_requests_url=f'{admin_base_url(app)}/custom-design/my-requests',
    )
    return Message(
        subject=f'We got your design request — #{req.id} | Purposefully Made KC',
        recipients=[recipient],
        body=plain,
        html=html,
        reply_to=reply_to(app),
    )


def _admin_message(app, req, customer_name, customer_email, customer_phone):
    submitted = req.created_at or datetime.utcnow()
    reference = _reference_url(app, req)
    link = f'{admin_base_url(app)}/admin/custom-design-requests/{req.id}'
    plain = (
        f"NEW DESIGN REQUEST — #{req.id}\n\n"
        f"Customer  : {customer_name}\n"
        f"Email     : {customer_email or 'not provided'}\n"
        f"Phone     : {customer_phone or 'not provided'}\n"
        f"Submitted : {submitted.strftime('%B %d, %Y at %I:%M %p')} UTC\n\n"
        f"What they want:\n{req.description}\n\n"
        f"Reference file : {req.reference_original_filename or 'unnamed'}\n"
        f"Reference link : {reference or 'not available'}\n\n"
        f"Open the request: {link}"
    )
    html = _render(
        app, 'email/design_request_admin.html',
        req=req, customer_name=customer_name, customer_email=customer_email,
        customer_phone=customer_phone, submitted=submitted,
        reference_url=reference, request_url=link,
    )
    return Message(
        subject=f'New Design Request — #{req.id} from {customer_name}',
        recipients=[admin_recipient(app)],
        body=plain,
        html=html,
        reply_to=customer_email or None,
    )


def send_design_request_emails(app, req_id, force=False):
    """Send the customer confirmation and the business notification.

    Returns True when at least one message went out. Never raises, so a mail
    outage cannot lose a request that is already saved.
    """
    try:
        req = CustomDesignRequest.query.get(req_id)
        if req is None:
            app.logger.error('design request emails skipped — request %s not found', req_id)
            return False
        if req.emails_sent_at and not force:
            return True

        user = req.user
        customer_name = (getattr(user, 'full_name', None) or 'there')
        customer_email = getattr(user, 'email', None)
        customer_phone = getattr(user, 'phone', None)

        sent_any = False
        if customer_email:
            sent_any = send(
                app, _customer_message(app, req, customer_name, customer_email),
                description=f'design request confirmation #{req.id}',
            ) or sent_any
        else:
            app.logger.error(
                'design request %s has no customer email to confirm to', req.id,
            )

        sent_any = send(
            app, _admin_message(app, req, customer_name, customer_email, customer_phone),
            description=f'design request business alert #{req.id}',
        ) or sent_any

        if sent_any:
            try:
                req.emails_sent_at = datetime.utcnow()
                db.session.commit()
            except Exception:
                db.session.rollback()
        return sent_any
    except Exception:
        app.logger.exception('design request emails failed for %s', req_id)
        return False
