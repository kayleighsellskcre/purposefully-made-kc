"""Custom design requests - customers upload reference images for recreation"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from models import db, CustomDesignRequest, Design
import secrets

custom_request_bp = Blueprint('custom_request', __name__, url_prefix='/custom-design')


def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in {'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif'}


@custom_request_bp.route('/')
def index():
    """Landing page - explain the service, require login to submit"""
    return render_template('custom_request/index.html')


@custom_request_bp.route('/submit', methods=['GET', 'POST'])
@login_required
def submit():
    """Submit a custom design request - reference image + description"""
    if request.method == 'POST':
        description = request.form.get('description', '').strip()
        file = request.files.get('reference_image')
        
        if not description:
            flash('Please describe what you want us to create.', 'error')
            return redirect(url_for('custom_request.submit'))
        
        if not file or not file.filename:
            flash('Please upload a reference image (screenshot or saved image).', 'error')
            return redirect(url_for('custom_request.submit'))
        
        if not allowed_file(file.filename):
            flash('Please upload a PNG, JPG, WEBP, or HEIC image.', 'error')
            return redirect(url_for('custom_request.submit'))

        # Save reference image.
        # Strategy: save locally first (instant), then promote to R2 in background.
        # This keeps the response under Railway's 30-second timeout even when R2 is slow.
        from utils.cloud_storage import _save_locally, r2_configured
        app_obj = current_app._get_current_object()
        prefix = f'request_{secrets.token_hex(8)}'
        relative_path = None
        try:
            relative_path = _save_locally(file, app_obj, 'custom_requests', prefix)
        except Exception as e:
            current_app.logger.exception(
                'Custom request local save failed for user %s: %s', current_user.id, e,
            )

        if not relative_path:
            flash('We could not save your image. Please try a different photo or file.', 'error')
            return redirect(url_for('custom_request.submit'))

        # Kick off R2 upload in background so the response returns immediately.
        if r2_configured(app_obj):
            import threading, io as _io
            from utils.cloud_storage import _upload_to_r2, _make_key
            from werkzeug.datastructures import FileStorage as _FileStorage
            try:
                file.stream.seek(0)
                file_bytes = file.stream.read()
            except Exception:
                file_bytes = None

            def _bg_upload(file_bytes, filename, content_type, local_path, prefix, app):
                if not file_bytes:
                    return
                try:
                    with app.app_context():
                        fs = _FileStorage(
                            stream=_io.BytesIO(file_bytes),
                            filename=filename,
                            content_type=content_type,
                        )
                        r2_url = _upload_to_r2(fs, app, 'custom_requests', prefix)
                        if r2_url:
                            # Update any matching request rows to the R2 URL
                            reqs = CustomDesignRequest.query.filter_by(
                                reference_file_path=local_path
                            ).all()
                            for r in reqs:
                                r.reference_file_path = r2_url
                            db.session.commit()
                except Exception as ex:
                    app.logger.warning('Background R2 upload failed for %s: %s', local_path, ex)

            t = threading.Thread(
                target=_bg_upload,
                args=(file_bytes, file.filename, file.content_type, relative_path, prefix, app_obj),
                daemon=True,
            )
            t.start()

        try:
            req = CustomDesignRequest(
                user_id=current_user.id,
                reference_file_path=relative_path,
                reference_original_filename=file.filename,
                description=description,
                status='pending'
            )
            db.session.add(req)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception(
                'Failed to save custom design request for user %s: %s',
                current_user.id, e,
            )
            flash('Your image uploaded, but we could not save your request. Please try again.', 'error')
            return redirect(url_for('custom_request.submit'))

        # Notify admin via SMS (non-critical — never affects success messaging)
        try:
            from utils.sms import send_design_request_alert
            send_design_request_alert(current_app, current_user.full_name, req.id)
        except Exception:
            pass

        return redirect(url_for('custom_request.confirmation', req_id=req.id))
    
    return render_template('custom_request/submit.html')


@custom_request_bp.route('/confirmation/<int:req_id>')
@login_required
def confirmation(req_id):
    """Thank-you page so the customer can see their request went through."""
    req = CustomDesignRequest.query.get_or_404(req_id)
    if req.user_id != current_user.id and not getattr(current_user, 'is_admin', False):
        flash('Request not found', 'error')
        return redirect(url_for('custom_request.my_requests'))
    return render_template('custom_request/confirmation.html', req=req)


@custom_request_bp.route('/my-requests')
@login_required
def my_requests():
    """View customer's own design requests — excludes soft-deleted cards."""
    reqs = (
        CustomDesignRequest.query
        .filter_by(user_id=current_user.id)
        .filter(CustomDesignRequest.is_deleted != True)
        .order_by(CustomDesignRequest.created_at.desc())
        .all()
    )
    return render_template('custom_request/my_requests.html', requests=reqs)


@custom_request_bp.route('/requests/<int:req_id>/delete', methods=['POST'])
@login_required
def delete_request(req_id):
    """Soft-delete a request card. The reference image and any linked design stay
    in the customer's account — only the request entry is hidden."""
    req = CustomDesignRequest.query.get_or_404(req_id)
    if req.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    req.is_deleted = True
    db.session.commit()
    return jsonify({'ok': True, 'message': 'Request removed from your list'})
