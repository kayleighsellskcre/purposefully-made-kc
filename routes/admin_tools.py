"""Admin helpers: one search box for everything, and the list of emails that did not go out.

Both live under /admin and share the admin blueprint (see the import at the bottom of routes/admin.py).
"""
from flask import flash, redirect, render_template, request, url_for

from models import EmailFailure, ManualInvoice, Order, User, db
from routes.admin import admin_bp, admin_required


def _plain_digits(column):
    """The phone column with the ( ) - . + and spaces taken out, so any way of typing a number matches."""
    for ch in ('(', ')', '-', '.', '+', ' '):
        column = db.func.replace(column, ch, '')
    return column


@admin_bp.route('/search')
@admin_required
def admin_search():
    """Find an order, an invoice or a customer by name, email, phone or number. One answer for the whole admin."""
    q = (request.args.get('q') or '').strip()
    orders = invoices = customers = []
    if q:
        like = f'%{q}%'
        digits = ''.join(ch for ch in q if ch.isdigit())
        order_match = db.or_(Order.order_number.ilike(like), Order.first_name.ilike(like), Order.last_name.ilike(like),
                             Order.email.ilike(like), (Order.first_name + ' ' + Order.last_name).ilike(like))
        invoice_match = db.or_(ManualInvoice.number.ilike(like), ManualInvoice.customer_name.ilike(like),
                               ManualInvoice.company.ilike(like), ManualInvoice.email.ilike(like))
        customer_match = db.or_(User.email.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like),
                                (User.first_name + ' ' + User.last_name).ilike(like))
        if len(digits) >= 4:                                   # a phone number, however it was typed
            order_match = db.or_(order_match, _plain_digits(Order.phone).like(f'%{digits}%'))
            invoice_match = db.or_(invoice_match, _plain_digits(ManualInvoice.phone).like(f'%{digits}%'))
            customer_match = db.or_(customer_match, _plain_digits(User.phone).like(f'%{digits}%'))
        orders = Order.query.filter(order_match).order_by(Order.created_at.desc()).limit(10).all()
        invoices = ManualInvoice.query.filter(invoice_match).order_by(ManualInvoice.id.desc()).limit(10).all()
        customers = User.query.filter(customer_match).order_by(User.id.desc()).limit(10).all()
        if len(orders) + len(invoices) + len(customers) == 1:   # one answer: go straight to it
            if orders:
                return redirect(url_for('admin.order_detail', order_id=orders[0].id))
            if invoices:
                return redirect(url_for('admin.invoice_view', invoice_id=invoices[0].id))
    return render_template('admin/search.html', q=q, orders=orders, invoices=invoices, customers=customers)


@admin_bp.route('/email-problems')
@admin_required
def email_problems():
    """Emails the site could not send, newest first, each with a Resend button."""
    rows = EmailFailure.query.filter_by(resolved=False).order_by(EmailFailure.created_at.desc()).limit(100).all()
    return render_template('admin/email_problems.html', rows=rows)


@admin_bp.route('/email-problems/<int:row_id>/resend', methods=['POST'])
@admin_required
def email_problem_resend(row_id):
    """Try the same email again. It leaves the list only once it really goes."""
    from flask import current_app
    from flask_mail import Message
    from utils import mailer
    row = EmailFailure.query.get_or_404(row_id)
    msg = Message(subject=row.subject or '', recipients=[a.strip() for a in (row.to_addr or '').split(',') if a.strip()],
                  html=row.html, body=row.body)
    if mailer.send(current_app._get_current_object(), msg, row.kind or 'email', record=False):
        row.resolved = True
        db.session.commit()
        note = ' It went without its attachments; use the order or invoice page to send it with them.' if row.had_attachments else ''
        flash(f'Sent to {row.to_addr}.{note}', 'success')
    else:
        flash('It still could not be sent. Check the email address, then try again.', 'error')
    return redirect(url_for('admin.email_problems'))


@admin_bp.route('/email-problems/<int:row_id>/dismiss', methods=['POST'])
@admin_required
def email_problem_dismiss(row_id):
    """Take it off the list without sending (you handled it another way)."""
    row = EmailFailure.query.get_or_404(row_id)
    row.resolved = True
    db.session.commit()
    flash('Removed from the list.', 'success')
    return redirect(url_for('admin.email_problems'))
