"""Custom design requests - customers upload reference images for recreation"""
from pathlib import Path
import re
import secrets
import threading
import time
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from models import db, CustomDesignRequest
from utils.rate_limit import post_only, rate_limit

# ── AI job store ─────────────────────────────────────────────────────────────
# In-memory dict keyed by job UUID. Safe with a single Gunicorn worker (Railway
# default). Each entry: {status, image_url, revised_prompt, error, created_at}
_ai_jobs: dict = {}
_ai_jobs_lock = threading.Lock()
_JOB_TTL = 600  # seconds — jobs older than 10 min are discarded


def _cleanup_old_jobs() -> None:
    """Remove jobs older than _JOB_TTL. Call while holding _ai_jobs_lock."""
    cutoff = time.time() - _JOB_TTL
    stale = [jid for jid, j in _ai_jobs.items() if j.get('created_at', 0) < cutoff]
    for jid in stale:
        del _ai_jobs[jid]


def _run_image_generation(app, job_id: str, api_key: str, enhanced_prompt: str) -> None:
    """Background thread: call OpenAI and write result into _ai_jobs."""
    with app.app_context():
        try:
            import requests as req_lib
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }
            body = {
                'model': 'gpt-image-1',
                'prompt': enhanced_prompt,
                'n': 1,
                'size': '1024x1024',
                'quality': 'high',          # full ChatGPT-quality output
                'background': 'transparent',  # native transparent PNG
                'output_format': 'png',
            }
            resp = req_lib.post(
                'https://api.openai.com/v1/images/generations',
                headers=headers,
                json=body,
                timeout=120,  # OpenAI can take up to ~90s for hd; give headroom
            )
            if resp.status_code != 200:
                api_err = resp.text[:400]
                app.logger.warning('AI image error %s: %s', resp.status_code, api_err)
                try:
                    err_msg = (resp.json().get('error') or {}).get('message', api_err)
                except Exception:
                    err_msg = api_err
                with _ai_jobs_lock:
                    if job_id in _ai_jobs:
                        _ai_jobs[job_id]['status'] = 'error'
                        _ai_jobs[job_id]['error'] = f'Generation failed: {err_msg}'
                return

            item = resp.json()['data'][0]
            if 'b64_json' in item:
                image_url = f"data:image/png;base64,{item['b64_json']}"
            else:
                image_url = item.get('url', '')
            revised = item.get('revised_prompt', '')

            with _ai_jobs_lock:
                if job_id in _ai_jobs:
                    _ai_jobs[job_id]['status'] = 'done'
                    _ai_jobs[job_id]['image_url'] = image_url
                    _ai_jobs[job_id]['revised_prompt'] = revised

        except Exception as e:
            app.logger.exception('AI background generation error: %s', e)
            with _ai_jobs_lock:
                if job_id in _ai_jobs:
                    _ai_jobs[job_id]['status'] = 'error'
                    _ai_jobs[job_id]['error'] = 'Something went wrong. Please try again.'

custom_request_bp = Blueprint('custom_request', __name__, url_prefix='/custom-design')

_MAX_REFERENCE_BYTES = 12 * 1024 * 1024


def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in {'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif'}


def _finish_request_in_background(app, file_bytes, filename, local_path, prefix, req_id, customer_name):
    """Promote the image to R2, email both parties, and text the admin.

    Runs after the customer already has their confirmation page, so none of
    this can slow down or fail their submission.
    """
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

        # Emails come after the R2 promotion so the artwork link in the business
        # notification points at the permanent URL rather than local disk.
        try:
            from utils.design_request_mail import send_design_request_emails
            send_design_request_emails(app, req_id)
        except Exception as ex:
            app.logger.warning('Design-request emails failed for request %s: %s', req_id, ex)

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
# Each accepted request emails the customer, emails the business, and sends an
# SMS. Sign-in already bounds who can do this, so the cap only needs to stop one
# account from flooding those three channels.
@post_only("10 per hour")
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

    follow_up_args = (
        app_obj,
        file_bytes,
        original_name,
        relative_path,
        prefix,
        req.id,
        current_user.full_name,
    )
    if app_obj.config.get('TESTING'):
        # Inline under test so email assertions are deterministic.
        _finish_request_in_background(*follow_up_args)
    else:
        threading.Thread(
            target=_finish_request_in_background,
            args=follow_up_args,
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


# ── AI Design Generator ──────────────────────────────────────────

@custom_request_bp.route('/ai-design')
def ai_design():
    """AI design generator landing page."""
    api_key = current_app.config.get('OPENAI_API_KEY') or ''
    available = bool(api_key and api_key.startswith('sk-'))
    return render_template('custom_request/ai_design.html', ai_available=available)


@custom_request_bp.route('/ai-design/generate', methods=['POST'])
@rate_limit('5 per hour')   # 5 AI images per IP per hour
@rate_limit('20 per day')   # 20 per IP per day hard cap
def ai_design_generate():
    """Kick off a background image generation job, return the job ID immediately.

    The client polls /ai-design/status/<job_id> until status == 'done' or 'error'.
    This avoids holding an HTTP connection open for 60-90 seconds (which would
    time out at Cloudflare's proxy layer).
    """
    api_key = current_app.config.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        return jsonify({'ok': False, 'error': 'AI design is not configured yet. Please try again soon.'})

    payload = request.get_json(silent=True) or {}
    prompt = payload.get('prompt', '').strip() if request.is_json else request.form.get('prompt', '').strip()
    if not prompt:
        return jsonify({'ok': False, 'error': 'Please describe the design you want.'})
    if len(prompt) > 800:
        return jsonify({'ok': False, 'error': 'Description is too long (800 character limit).'})

    enhanced_prompt = (
        f'{prompt}. '
        'Design for DTF heat-transfer printing on a t-shirt. Transparent background. '
        'Subtle natural texture (slight grain or worn feel) for depth and warmth. '
        'Bold, high-contrast colors. Clean crisp edges. No text unless specifically requested.'
    )

    job_id = str(uuid.uuid4())
    with _ai_jobs_lock:
        _cleanup_old_jobs()
        _ai_jobs[job_id] = {
            'status': 'pending',
            'image_url': None,
            'revised_prompt': '',
            'error': None,
            'created_at': time.time(),
        }

    app_obj = current_app._get_current_object()
    threading.Thread(
        target=_run_image_generation,
        args=(app_obj, job_id, api_key, enhanced_prompt),
        daemon=True,
    ).start()

    return jsonify({'ok': True, 'job_id': job_id})


@custom_request_bp.route('/ai-design/status/<job_id>')
def ai_design_status(job_id):
    """Poll endpoint: returns {status, image_url, revised_prompt, error}."""
    if not re.match(r'^[0-9a-f\-]{36}$', job_id):
        return jsonify({'status': 'error', 'error': 'Invalid job ID.'})

    with _ai_jobs_lock:
        job = dict(_ai_jobs.get(job_id) or {})

    if not job:
        return jsonify({'status': 'error', 'error': 'Job not found. Please try again.'})

    return jsonify({
        'status': job['status'],
        'image_url': job.get('image_url'),
        'revised_prompt': job.get('revised_prompt', ''),
        'error': job.get('error'),
    })
