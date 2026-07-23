"""
Design upload routes - simple, reliable upload for product customizer.
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user
from werkzeug.utils import secure_filename
from pathlib import Path
import os
import time
import secrets

design_bp = Blueprint('design', __name__, url_prefix='/design')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'heic', 'heif'}


def _allowed_file(filename):
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _safe_ext(filename):
    """Get extension from filename, default to .png if invalid."""
    if not filename or '.' not in filename:
        return '.png'
    return '.' + filename.rsplit('.', 1)[1].lower()


def _remove_background(filepath, mode='auto'):
    """
    Produce a clean, true-transparent PNG cutout of the uploaded artwork.

    Uses the shared image-processing pipeline (algorithmic by default, optional
    rembg AI engine, defringe + anti-aliased edges, white-artwork detection and
    validation). Returns (new_filepath, new_filename, meta_dict). On any failure
    it falls back to leaving the original file in place.
    """
    try:
        from services.image_processing import process_artwork_file, issue_messages
        result = process_artwork_file(filepath, mode=mode)
        new_path = result.get('path') or filepath
        meta = {
            'engine': result.get('engine'),
            'white_artwork': bool(result.get('white_artwork')),
            'validation': result.get('validation') or {'ok': True, 'issues': [], 'metrics': {}},
            'messages': issue_messages(result.get('validation') or {}),
            'has_transparency': bool(result.get('has_transparency', True)),
        }
        return new_path, new_path.name, meta
    except Exception:
        return filepath, filepath.name, {
            'engine': 'none',
            'white_artwork': False,
            'validation': {'ok': True, 'issues': [], 'metrics': {}},
            'messages': [],
            'has_transparency': False,
        }


@design_bp.route('/upload', methods=['POST'])
def upload():
    """Upload design image - minimal processing, maximum reliability."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not _allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Use PNG, JPG, WEBP, or GIF'}), 400

        # Hard size limit before touching disk — prevents OOM kills on Railway.
        # Read just enough bytes to check; seek back so file.save() still works.
        file.stream.seek(0, 2)   # seek to end
        file_bytes = file.stream.tell()
        file.stream.seek(0)      # rewind
        MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # 10 MB
        if file_bytes > MAX_UPLOAD_BYTES:
            return jsonify({
                'error': f'File is too large ({file_bytes // (1024*1024)} MB). '
                         'Please resize to under 10 MB before uploading.'
            }), 413

        upload_folder = current_app.config.get('UPLOAD_FOLDER')
        if not upload_folder:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
        upload_dir = Path(upload_folder) / 'designs'
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = _safe_ext(file.filename)
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.heic', '.heif'):
            ext = '.png'
        unique_name = f"design_{int(time.time())}_{secrets.token_hex(8)}{ext}"
        filepath = upload_dir / unique_name
        file.save(str(filepath))

        # Background removal mode: 'auto' (default), 'aggressive' (reprocess),
        # or 'none' (keep the uploaded image as-is).
        mode = (request.form.get('bg_removal') or 'auto').strip().lower()
        if mode not in ('auto', 'aggressive', 'none'):
            mode = 'auto'

        # Produce a clean transparent-PNG cutout with crisp, print-ready edges.
        filepath, unique_name, art_meta = _remove_background(filepath, mode=mode)

        # Upload to R2 if configured; otherwise fall back to local static path
        from utils.cloud_storage import r2_configured, _upload_to_r2
        stored_path = f"uploads/designs/{unique_name}"
        if r2_configured(current_app._get_current_object()):
            try:
                with open(filepath, 'rb') as f_obj:
                    from werkzeug.datastructures import FileStorage
                    fs = FileStorage(stream=f_obj, filename=unique_name)
                    stored_path = _upload_to_r2(fs, current_app._get_current_object(), 'designs', 'design')
            except Exception:
                pass

        url = stored_path if stored_path.startswith('http') else f"/static/{stored_path}"
        width, height = None, None

        try:
            from PIL import Image
            with Image.open(filepath) as img:
                width, height = img.size
        except Exception:
            pass

        design_id = None
        submitted_to_gallery = False
        if current_user.is_authenticated:
            share_val = request.form.get('share_in_gallery', 'false').lower() == 'true'
            try:
                from models import Design, db
                from datetime import datetime
                import re as _re
                raw_stem = (file.filename or '').rsplit('.', 1)[0]
                # If the filename looks like a UUID or is just numbers/hex, use a friendly default
                _uuid_like = _re.fullmatch(r'[0-9a-fA-F\-]{20,}', raw_stem)
                _generic = _re.fullmatch(r'[Ii][Mm][Gg][\s_\-]?\d+', raw_stem)
                if _uuid_like or _generic or not raw_stem:
                    from models import Design as _D
                    count = _D.query.filter_by(uploaded_by_user_id=current_user.id).count()
                    title = f'My Design {count + 1}'
                else:
                    title = raw_stem.replace('_', ' ').replace('-', ' ').title()[:50]

                # Duplicate guard: if this user already has a design with the same
                # original filename uploaded in the last 30 seconds, return that one
                # instead of creating a second record (catches double-tap / form re-submit).
                from datetime import timedelta
                _cutoff = datetime.utcnow() - timedelta(seconds=30)
                _existing = Design.query.filter_by(
                    uploaded_by_user_id=current_user.id,
                    original_filename=file.filename,
                ).filter(Design.uploaded_at >= _cutoff).first()
                if _existing:
                    _ex_url = _existing.file_path if _existing.file_path.startswith('http') else f"/static/{_existing.file_path}"
                    return jsonify({
                        'success': True,
                        'url': _ex_url,
                        'width': _existing.width,
                        'height': _existing.height,
                        'design_id': _existing.id,
                        'engine': 'cached',
                        'white_artwork': False,
                        'background_removed': True,
                        'validation': {'ok': True, 'issues': [], 'metrics': {}},
                        'messages': [],
                        'submitted_to_gallery': False,
                        'gallery_status': None,
                    })

                design = Design(
                    filename=unique_name,
                    original_filename=file.filename,
                    file_path=stored_path,
                    # Customer submissions are NEVER published directly — they go
                    # into the admin approval queue. is_gallery stays False until
                    # an admin approves it.
                    is_gallery=False,
                    title=title,
                    uploaded_by_user_id=current_user.id,
                    width=width,
                    height=height,
                    has_transparency=bool(art_meta.get('has_transparency')),
                )
                if share_val:
                    design.gallery_submitted = True
                    design.gallery_status = 'pending'
                    design.gallery_submitted_at = datetime.utcnow()
                    submitted_to_gallery = True
                if filepath.exists():
                    design.file_size = filepath.stat().st_size
                db.session.add(design)
                db.session.commit()
                design_id = design.id
            except Exception:
                pass

        return jsonify({
            'success': True,
            'url': url,
            'width': width,
            'height': height,
            'design_id': design_id,
            'engine': art_meta.get('engine'),
            'white_artwork': art_meta.get('white_artwork', False),
            'background_removed': art_meta.get('engine') not in (None, 'none'),
            'validation': art_meta.get('validation', {'ok': True, 'issues': [], 'metrics': {}}),
            'messages': art_meta.get('messages', []),
            'submitted_to_gallery': submitted_to_gallery,
            'gallery_status': 'pending' if submitted_to_gallery else None,
        })

    except OSError as e:
        return jsonify({'error': f'Could not save file. Check folder permissions.'}), 500
    except Exception as e:
        if current_app.debug:
            current_app.logger.exception('Design upload failed')
        return jsonify({'error': str(e) or 'Upload failed'}), 500


@design_bp.route('/<int:design_id>/delete', methods=['POST'])
def delete(design_id):
    """Let an authenticated user permanently delete one of their own uploaded designs."""
    from flask_login import login_required
    from models import Design, db

    if not current_user.is_authenticated:
        return jsonify({'error': 'Login required'}), 401

    design = Design.query.get_or_404(design_id)

    # Only the owner (or an admin) may delete a design
    if design.uploaded_by_user_id != current_user.id and not getattr(current_user, 'is_admin', False):
        return jsonify({'error': 'Not authorised'}), 403

    # Guard against deleting designs that are part of existing orders
    try:
        attached = design.order_items.count() > 0
    except Exception:
        attached = False
    if attached:
        return jsonify({'error': 'This design is attached to an order and cannot be deleted'}), 400

    name = design.title or design.original_filename or 'Design'

    # Check whether this design was created by admin in response to a custom request.
    # If so, only unlink it from the customer — keep the design record so it can be
    # re-assigned later. The customer can always come back and use it again.
    try:
        from models import CustomDesignRequest
        linked_request = CustomDesignRequest.query.filter_by(
            created_design_id=design.id
        ).first()
    except Exception:
        linked_request = None

    if linked_request:
        # Soft-unlink: remove from "My Designs" view but preserve the design record
        design.uploaded_by_user_id = None
        db.session.commit()
        return jsonify({'ok': True, 'message': f'"{name}" removed from your designs'})

    # For customer-uploaded designs (no admin request), do a full hard delete.
    # Remove file from local disk (R2 objects are not purged to avoid breaking CDN links)
    if design.file_path:
        local = Path('static') / design.file_path
        if local.exists():
            try:
                local.unlink()
            except OSError:
                pass

    db.session.delete(design)
    db.session.commit()

    return jsonify({'ok': True, 'message': f'"{name}" deleted'})
