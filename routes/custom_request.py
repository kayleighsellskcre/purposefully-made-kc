"""Custom design requests - customers upload reference images for recreation"""
from pathlib import Path
import secrets
import threading

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from models import db, CustomDesignRequest

custom_request_bp = Blueprint('custom_request', __name__, url_prefix='/custom-design')

_MAX_REFERENCE_BYTES = 12 * 1024 * 1024


def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in {'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif'}


def _finish_request_in_background(app, file_bytes, filename, local_path, prefix, req_id, customer_name):
    """Promote the image to R2 and text the admin. Never blocks the customer response."""
    with app.app_context():
        if file_bytes:
            try:
                from utils.cloud_storage import r2_configured, upload_bytes
                if r2_configured(app):
                    r2_url = upload_bytes(
                        file_bytes, app, filename,
                        subfolder='custom_requests',
                        public_id_prefix=prefix,
                    )
                    if r2_url:
                        req = CustomDesignRequest.query.get(req_id)
                        if req and req.reference_file_path == local_path:
                            req.reference_file_path = r2_url
                            db.session.commit()
            except Exception as ex:
                app.logger.warning('Background R2 upload failed for request %s: %s', req_id, ex)
                try:
                    db.session.rollback()
                except Exception:
                    pass
        try:
            from utils.sms import send_design_request_alert
            send_design_request_alert(app, customer_name, req_id)
        except Exception as ex:
            app.logger.warning('Design-request SMS failed for request %s: %s', req_id, ex)


@custom_request_bp.route('/')
def index():
    """Landing page - explain the service, require login to submit"""
    return render_template('custom_request/index.html')


@custom_request_bp.route('/submit', methods=['GET', 'POST'])
@login_required
def submit():
    """Submit a custom design request - reference image + description"""
    if request.method == 'POST':
        try:
            return _handle_submit_post()
        except Exception as e:
            current_app.logger.exception('custom_request submit unhandled error: %s', e)
            try:
                db.session.rollback()
            except Exception:
                pass
            flash('Something went wrong saving your request. Please try again.', 'error')
            return redirect(url_for('custom_request.submit'))
    try:
        return render_template('custom_request/submit.html')
    except Exception as e:
        current_app.logger.exception('custom_request submit GET render failed: %s', e)
        flash('We had trouble loading the form. Please refresh and try again.', 'error')
        return redirect(url_for('custom_request.index'))


def _handle_submit_post():
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

    try:
        file.stream.seek(0)
    except Exception:
        pass
    file_bytes = file.read()
    if not file_bytes:
        flash('We could not read that image. Please try a different photo.', 'error')
        return redirect(url_for('custom_request.submit'))
    if len(file_bytes) > _MAX_REFERENCE_BYTES:
        flash('That image is too large (limit 12 MB). Please send a screenshot or a smaller photo.', 'error')
        return redirect(url_for('custom_request.submit'))

    original_name = (file.filename or 'upload.jpg')[:500]
    safe_name = secure_filename(original_name) or 'upload.jpg'
    name_base = safe_name.rsplit('.', 1)[0][:50]
    ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else 'jpg'
    prefix = f'request_{secrets.token_hex(8)}'
    unique_name = f'{prefix}_{name_base}.{ext}'

    app_obj = current_app._get_current_object()
    upload_dir = Path(app_obj.config['UPLOAD_FOLDER']) / 'custom_requests'
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / unique_name).write_bytes(file_bytes)
    except Exception as e:
        current_app.logger.exception(
            'Custom request local save failed for user %s: %s', current_user.id, e,
        )
        flash('We could not save your image. Please try a different photo or file.', 'error')
        return redirect(url_for('custom_request.submit'))

    relative_path = f'uploads/custom_requests/{unique_name}'

    try:
        req = CustomDesignRequest(
            user_id=current_user.id,
            reference_file_path=relative_path,
            reference_original_filename=original_name,
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

    threading.Thread(
        target=_finish_request_in_background,
        args=(
            app_obj,
            file_bytes,
            original_name,
            relative_path,
            prefix,
            req.id,
            current_user.full_name,
        ),
        daemon=True,
    ).start()

    return redirect(url_for('custom_request.confirmation', req_id=req.id))


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
