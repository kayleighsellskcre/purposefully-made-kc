"""Admin design queues: the public gallery approval queue, the notifications inbox, and "Have Us Draw It" requests.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
from datetime import datetime
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import current_user
from models import db, Design, CustomDesignRequest, AdminNotification

from routes.admin import (  # noqa: E402
    DesignUploadError, _email_design_request_decision, _promote_design_to_r2, _save_design_for_user,
    admin_bp, admin_required,
)


# ===== PUBLIC GALLERY APPROVAL QUEUE =====

def _design_validation_meta(design):
    """Best-effort transparency/background check for a queued design, used to
    help admins verify the cutout before publishing. Reads the local file when
    available; otherwise falls back to the stored transparency flag."""
    meta = {
        'has_transparency': bool(getattr(design, 'has_transparency', False)),
        'validation': None,
    }
    try:
        fp = design.file_path or ''
        data = None
        if not fp.startswith('http'):
            p = Path('static') / fp
            if p.exists():
                data = p.read_bytes()
        if data:
            from services.image_processing import process_artwork_bytes, issue_messages
            res = process_artwork_bytes(data, mode='none')
            meta['has_transparency'] = bool(res.get('has_transparency'))
            v = res.get('validation') or {}
            meta['validation'] = {
                'issues': v.get('issues', []),
                'messages': issue_messages(v),
                'metrics': v.get('metrics', {}),
            }
    except Exception:
        from utils.quiet_errors import report_quiet
        report_quiet('checking the print quality of a design')
    return meta


@admin_bp.route('/gallery-queue')
@admin_required
def gallery_queue():
    """Review queue: customer designs awaiting approval before publication."""
    try:
        pending = (Design.query
                   .filter(Design.gallery_status.in_(['pending', 'changes_requested']))
                   .order_by(Design.uploaded_at.desc())
                   .all())
        recent = (Design.query
                  .filter(Design.gallery_status.in_(['approved', 'rejected']))
                  .order_by(Design.uploaded_at.desc())
                  .limit(24).all())
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to load gallery approval queue: %s', e)
        flash('We could not load the approval queue (a database issue). '
              'If this persists, a database migration may be pending.', 'error')
        pending, recent = [], []

    # Build per-design validation metadata defensively — a single bad record or
    # unreadable image must never crash the whole queue.
    queue = []
    for d in pending:
        try:
            meta = _design_validation_meta(d)
        except Exception as e:
            current_app.logger.exception('Validation meta failed for design %s: %s', getattr(d, 'id', '?'), e)
            meta = {'has_transparency': False, 'validation': None}
        queue.append({'design': d, 'meta': meta})
    return render_template('admin/gallery_queue.html', queue=queue, recent=recent)


def _review_design(design_id):
    design = Design.query.get_or_404(design_id)
    return design


def _commit_review(design, success_msg):
    """Commit a review action, returning a JSON/redirect response. Handles
    failures gracefully so a single bad action never 500s the admin."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Gallery review action failed for design %s: %s',
                                     getattr(design, 'id', '?'), e)
        err = 'Could not save this action due to a server issue. Please try again.'
        if is_ajax:
            return jsonify({'ok': False, 'error': err}), 500
        flash(err, 'error')
        return redirect(url_for('admin.gallery_queue'))
    if is_ajax:
        return jsonify({'ok': True, 'message': success_msg})
    flash(success_msg, 'success')
    return redirect(url_for('admin.gallery_queue'))


@admin_bp.route('/gallery-queue/<int:design_id>/approve', methods=['POST'])
@admin_required
def gallery_approve(design_id):
    """Approve a submitted design and publish it to the public gallery."""
    design = _review_design(design_id)
    design.gallery_status = 'approved'
    design.gallery_submitted = True
    design.is_gallery = True            # now visible on public-facing pages
    design.gallery_rejection_reason = None
    design.gallery_reviewed_at = datetime.utcnow()
    design.gallery_reviewed_by_id = current_user.id
    if not design.folder:
        design.folder = request.form.get('folder') or 'custom_orders'
    name = design.title or design.original_filename or 'Design'
    return _commit_review(design, f'"{name}" approved and published to the gallery.')


@admin_bp.route('/gallery-queue/<int:design_id>/reject', methods=['POST'])
@admin_required
def gallery_reject(design_id):
    """Reject a submitted design. It stays hidden from the public gallery."""
    design = _review_design(design_id)
    reason = (request.form.get('reason') or '').strip()
    design.gallery_status = 'rejected'
    design.is_gallery = False           # ensure it is not public
    design.gallery_rejection_reason = reason or 'Did not meet gallery guidelines.'
    design.gallery_reviewed_at = datetime.utcnow()
    design.gallery_reviewed_by_id = current_user.id
    name = design.title or design.original_filename or 'Design'
    return _commit_review(design, f'"{name}" rejected and kept hidden.')


@admin_bp.route('/gallery-queue/<int:design_id>/request-changes', methods=['POST'])
@admin_required
def gallery_request_changes(design_id):
    """Ask the submitter for changes. Design stays hidden until re-reviewed."""
    design = _review_design(design_id)
    reason = (request.form.get('reason') or '').strip()
    design.gallery_status = 'changes_requested'
    design.is_gallery = False
    design.gallery_rejection_reason = reason or 'Changes requested before publication.'
    design.gallery_reviewed_at = datetime.utcnow()
    design.gallery_reviewed_by_id = current_user.id
    name = design.title or design.original_filename or 'Design'
    return _commit_review(design, f'Changes requested for "{name}".')


@admin_bp.context_processor
def _inject_gallery_pending_count():
    """Expose pending-review and unread-inbox counts to admin templates."""
    count = 0
    unread = 0
    try:
        count = (Design.query
                 .filter(Design.gallery_status.in_(['pending', 'changes_requested']))
                 .count())
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        count = 0
    try:
        from utils.admin_notifications import unread_count
        unread = unread_count()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        unread = 0
    return {
        'gallery_pending_count': count,
        'admin_unread_notifications': unread,
    }


@admin_bp.route('/notifications')
@admin_required
def notifications():
    """Inbox for contact-form messages and design requests — not orders."""
    from utils.admin_notifications import backfill_pending_design_requests
    try:
        backfill_pending_design_requests()
    except Exception:
        from utils.quiet_errors import report_quiet
        report_quiet('catching up pending design requests')
        try:
            db.session.rollback()
        except Exception:
            pass
    notes = (
        AdminNotification.query
        .order_by(AdminNotification.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
        'admin/notifications.html',
        notifications=notes,
    )


@admin_bp.route('/notifications/mark-all-read', methods=['POST'])
@admin_required
def notifications_mark_all_read():
    from utils.admin_notifications import mark_all_read
    mark_all_read()
    return redirect(url_for('admin.notifications'))


@admin_bp.route('/notifications/<int:note_id>/open', methods=['GET', 'POST'])
@admin_required
def notifications_open(note_id):
    """Mark one notification read, then go to the design request (or stay here)."""
    from utils.admin_notifications import mark_read
    note = AdminNotification.query.get_or_404(note_id)
    mark_read(note)
    db.session.commit()
    if note.url:
        return redirect(note.url)
    return redirect(url_for('admin.notifications'))


# ===== RECREATE REQUESTS (Have Us Recreate) =====

@admin_bp.route('/custom-design-requests')
@admin_required
def custom_design_requests():
    """List all custom design requests from customers"""
    status_filter = request.args.get('status', 'pending')
    query = CustomDesignRequest.query.order_by(CustomDesignRequest.created_at.desc())
    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)
    requests = query.all()
    return render_template('admin/custom_design_requests.html', requests=requests, status_filter=status_filter)


@admin_bp.route('/custom-design-requests/<int:request_id>', methods=['GET', 'POST'])
@admin_required
def custom_design_request_detail(request_id):
    """View request and upload completed design for customer"""
    req = CustomDesignRequest.query.get_or_404(request_id)

    if request.method == 'POST':
        try:
            return _handle_design_request_post(req)
        except Exception as e:
            current_app.logger.exception(
                'custom design request %s POST failed: %s', request_id, e,
            )
            try:
                db.session.rollback()
            except Exception:
                pass
            flash('Something went wrong. Please refresh and try again.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=request_id))

    try:
        return render_template('admin/custom_design_request_detail.html', req=req)
    except Exception as e:
        current_app.logger.exception(
            'custom design request %s GET render failed: %s', request_id, e,
        )
        flash('The design was saved. Refresh this page to see it.', 'info')
        return redirect(url_for('admin.custom_design_requests'))


def _handle_design_request_post(req):
    action = request.form.get('action')
    if action == 'upload_design':
        if req.status == 'completed' and req.created_design_id:
            flash('This request already has a design on the customer profile.', 'info')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        file = request.files.get('design_file')
        title = request.form.get('title', '').strip() or (
            req.description[:50] + '...' if len(req.description or '') > 50 else req.description
        )
        design_fee = request.form.get('design_fee', '0')
        if not file or not file.filename:
            flash('Please select a design file to upload.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        try:
            design, local_path, r2_prefix = _save_design_for_user(
                file, req.user_id, title=title or None, design_fee=design_fee,
            )
        except DesignUploadError:
            db.session.rollback()
            flash('The image could not be stored. Please try uploading it again.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        if design is None:
            flash('Unsupported file type. Use PNG, JPG, WEBP, or HEIC.', 'error')
            return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

        req.created_design_id = design.id
        req.status = 'completed'
        req.design_fee = float(design_fee or 0)
        req.admin_notes = (req.admin_notes or '') + (
            f"\n[Design uploaded: {design.filename}, fee: ${design.design_fee:.0f}]"
        )
        customer_name = getattr(getattr(req, 'user', None), 'full_name', None) or 'the customer'
        db.session.commit()

        try:
            from utils.background import run_in_background
            app_obj = current_app._get_current_object()
            run_in_background(app_obj, _promote_design_to_r2, design.id, local_path, r2_prefix)
            run_in_background(app_obj, _email_design_request_decision, req.id, 'completed')
        except Exception:
            current_app.logger.exception('background follow-up failed after design upload')
        flash(
            f"Image added to {customer_name}'s profile. It's in their My Designs now.",
            'success',
        )
        return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))

    if action == 'add_notes':
        req.admin_notes = request.form.get('admin_notes', '')
        db.session.commit()
        flash('Notes saved', 'success')
    elif action == 'start':
        if req.status == 'pending' and not req.started_at:
            req.started_at = datetime.utcnow()
            db.session.commit()
            from utils.background import run_in_background
            run_in_background(current_app._get_current_object(), _email_design_request_decision, req.id, 'started')
            flash('Marked in progress and the customer was emailed.', 'success')
        else:
            flash('That request is already underway or finished.', 'info')
    elif action == 'decline':
        reason = (request.form.get('decline_reason') or '').strip()
        req.status = 'declined'
        req.admin_notes = (req.admin_notes or '') + '\n' + (reason or 'Declined')
        db.session.commit()
        from utils.background import run_in_background
        run_in_background(
            current_app._get_current_object(),
            _email_design_request_decision,
            req.id, 'declined', reason or None,
        )
        flash('Request declined and customer notified by email.', 'info')
    elif action == 'delete':
        db.session.delete(req)
        db.session.commit()
        flash('Request permanently deleted.', 'info')
        return redirect(url_for('admin.custom_design_requests'))
    return redirect(url_for('admin.custom_design_request_detail', request_id=req.id))


def _send_design_request_decision_email(req, decision, reason=None):
    """Email the customer when their design request is approved or declined."""
    try:
        from flask_mail import Message as MailMessage
        mail = current_app.extensions.get('mail')
        if not mail:
            return False
        cfg = current_app.config
        if not (cfg.get('MAIL_SERVER') and cfg.get('MAIL_USERNAME') and cfg.get('MAIL_PASSWORD')):
            current_app.logger.warning('design request email skipped — mail not configured')
            return False

        user = req.user
        email = getattr(user, 'email', None)
        if not email:
            return False

        from utils.mailer import sender as _sender_tuple
        app_obj = current_app._get_current_object()
        first = getattr(user, 'first_name', None) or 'there'
        sender = _sender_tuple(app_obj)

        if decision == 'started':
            subject = "We've started on your design, Purposefully Made KC"
            body = (
                f"Hi {first},\n\n"
                f"Good news: Kayleigh has started working on your design request.\n\n"
                f"Most designs take 1 to 2 business days. We will email you the moment it is ready in your My Designs.\n\n"
                f"Questions? Reply here or email purposefullymadekc@gmail.com\n\n"
                f"— Purposefully Made KC"
            )
        elif decision == 'completed':
            subject = "Your custom design is ready! — Purposefully Made KC"
            body = (
                f"Hi {first},\n\n"
                f"Great news — your custom design request has been completed!\n\n"
                f"Your design is now in your My Designs. Log in and head to "
                f"My Account → My Designs to find it. From there you can apply "
                f"it to any shirt style, color, or size.\n\n"
                f"https://purposefullymadekc.com/account\n\n"
                f"Questions? Reply here or email purposefullymadekc@gmail.com\n\n"
                f"— Purposefully Made KC"
            )
        else:
            subject = "Update on your design request — Purposefully Made KC"
            reason_line = f"\n\nReason: {reason}" if reason else ""
            body = (
                f"Hi {first},\n\n"
                f"Unfortunately we're unable to complete your design request at this time.{reason_line}\n\n"
                f"If you have questions or would like to submit a different request, "
                f"feel free to reach out at purposefullymadekc@gmail.com or submit a new request "
                f"at https://purposefullymadekc.com/custom-design/submit\n\n"
                f"— Purposefully Made KC"
            )

        from utils.mailer import send as _send_mail
        msg = MailMessage(
            subject=subject,
            recipients=[email],
            body=body,
            sender=sender,
            reply_to='purposefullymadekc@gmail.com',
        )
        return _send_mail(
            app_obj, msg,
            description=f'design request {decision} notice for request {req.id}',
        )
    except Exception as e:
        current_app.logger.exception('design request decision email failed for request %s: %s', req.id, e)
        return False


@admin_bp.route('/designs/<int:design_id>/delete', methods=['POST'])
@admin_required
def design_delete(design_id):
    """Remove a design from the admin Design Library.

    Customer-owned designs are soft-hidden so My Designs (and the file) stay
    intact. Orphan / admin-only designs with no order or request links are
    hard-deleted. Always returns quickly with JSON for the AJAX modal.
    """
    design = Design.query.get_or_404(design_id)
    name = design.title or design.original_filename or 'Design'
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _json_or_redirect(payload, *, ok=True, flash_msg=None, flash_cat='success'):
        if flash_msg:
            flash(flash_msg, flash_cat)
        if is_ajax:
            status = 200 if ok else 400
            return jsonify(payload), status
        return redirect(url_for('admin.designs', tab='library'))

    try:
        # Customer copy must survive admin cleanup of the library list.
        if design.uploaded_by_user_id:
            design.hidden_from_admin = True
            db.session.commit()
            return _json_or_redirect(
                {
                    'ok': True,
                    'message': f'"{name}" removed from admin library. Customer still has their copy.',
                },
                flash_msg='Removed from admin library (customer copy kept)',
            )

        # Linked to orders or recreate requests — never destroy the file/row.
        try:
            in_orders = design.order_items.count() > 0
        except Exception:
            in_orders = False
        linked_request = None
        try:
            from models import CustomDesignRequest
            linked_request = CustomDesignRequest.query.filter_by(
                created_design_id=design.id
            ).first()
        except Exception:
            linked_request = None

        if in_orders or linked_request:
            design.hidden_from_admin = True
            db.session.commit()
            reason = 'linked to orders' if in_orders else 'linked to a recreate request'
            return _json_or_redirect(
                {
                    'ok': True,
                    'message': f'"{name}" hidden from admin library ({reason}; file kept).',
                },
                flash_msg=f'Hidden from library ({reason})',
            )

        # Safe hard delete for orphan admin uploads
        file_path = design.file_path
        db.session.delete(design)
        db.session.commit()
        # Unlink after commit so a stuck disk op never blocks the UI response path
        # for future soft-hides; for hard delete we still try briefly.
        if file_path:
            try:
                full_path = Path('static') / file_path
                if full_path.exists():
                    full_path.unlink()
            except OSError:
                pass

        return _json_or_redirect(
            {'ok': True, 'message': f'"{name}" permanently deleted'},
            flash_msg='Design deleted permanently',
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to delete design %s: %s', design_id, e)
        return _json_or_redirect(
            {'ok': False, 'error': 'Could not delete the design. Please try again.'},
            ok=False,
            flash_msg='Could not delete the design. Please try again.',
            flash_cat='error',
        )


def _delete_design_file(design):
    """Remove design file from disk if it exists"""
    if design and design.file_path:
        full_path = Path('static') / design.file_path
        if full_path.exists():
            try:
                full_path.unlink()
            except OSError:
                pass
