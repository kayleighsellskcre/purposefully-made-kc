"""Admin side of design proof approval: send a proof from an order, approve for the customer, and the list of proofs out.

On the admin blueprint like the rest of the admin, so url_for('admin.proofs') and friends work everywhere.
"""
from flask import flash, redirect, render_template, request, url_for

from models import Order, OrderProof, db
from routes.admin import admin_bp, admin_required


@admin_bp.route('/operations/proofs')
@admin_required
def proofs():
    """Every proof out and every answer waiting for the shop."""
    from utils import proofs as P
    return render_template('admin/operations/proofs.html', waiting=P.waiting_proofs(), changes=P.changes_proofs(),
                           days=P.REMINDER_AFTER_DAYS)


@admin_bp.route('/orders/<int:order_id>/proof', methods=['POST'])
@admin_required
def order_proof(order_id):
    """send, resend, or approve for the customer (they said yes by phone or text)."""
    from utils import proofs as P
    order = Order.query.get_or_404(order_id)
    action = request.form.get('action')
    current = P.latest(order.id)
    try:
        if action == 'send':
            sent = P.send_proof(order, request.form.get('message', ''))
            if sent.emailed:
                flash(f'Proof sent to {order.email}. The order now shows Waiting on approval.', 'success')
            else:
                flash('The proof is saved, but the email could not be sent. Use "Email the link again" once email is working.', 'error')
        elif action == 'resend' and current is not None:
            if P.resend(current):
                flash('The proof link was emailed again.', 'success')
            else:
                flash('The email could not be sent. Check that email is set up.', 'error')
        elif action == 'approve' and current is not None and current.status == 'waiting':
            P.approve(current, by='shop')
            flash('Marked as approved. The order can go to the press.', 'success')
        else:
            flash('Nothing to do there.', 'info')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('admin.order_detail', order_id=order.id))
