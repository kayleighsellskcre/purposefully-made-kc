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

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


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


def _make_white_transparent(filepath, threshold=240):
    """
    Make white/near-white pixels transparent so designs blend with shirt.
    Saves as PNG. Returns (new_filepath, new_filename) or (original, original_name) on failure.
    """
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            img = img.convert("RGBA")
            data = img.getdata()
            new_data = []
            for item in data:
                r, g, b, a = item
                if r >= threshold and g >= threshold and b >= threshold:
                    new_data.append((r, g, b, 0))
                else:
                    new_data.append(item)
            img.putdata(new_data)
            png_name = filepath.stem + '.png'
            png_path = filepath.parent / png_name
            img.save(str(png_path), 'PNG')
            if png_path != filepath and filepath.exists():
                filepath.unlink()
            return png_path, png_name
    except Exception:
        return filepath, filepath.name


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

        upload_folder = current_app.config.get('UPLOAD_FOLDER')
        if not upload_folder:
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
        upload_dir = Path(upload_folder) / 'designs'
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = _safe_ext(file.filename)
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
            ext = '.png'
        unique_name = f"design_{int(time.time())}_{secrets.token_hex(8)}{ext}"
        filepath = upload_dir / unique_name
        file.save(str(filepath))

        # Make white/near-white backgrounds transparent for shirt mockups
        filepath, unique_name = _make_white_transparent(filepath)

        url = f"/static/uploads/designs/{unique_name}"
        width, height = None, None

        try:
            from PIL import Image
            with Image.open(filepath) as img:
                width, height = img.size
        except Exception:
            pass

        design_id = None
        if current_user.is_authenticated:
            share_val = request.form.get('share_in_gallery', 'false').lower() == 'true'
            try:
                from models import Design, db
                title = (file.filename or 'Design').rsplit('.', 1)[0].replace('_', ' ').title()[:50]
                design = Design(
                    filename=unique_name,
                    original_filename=file.filename,
                    file_path=f"uploads/designs/{unique_name}",
                    is_gallery=share_val,
                    title=title,
                    uploaded_by_user_id=current_user.id,
                    width=width,
                    height=height,
                )
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
        })

    except OSError as e:
        return jsonify({'error': f'Could not save file. Check folder permissions.'}), 500
    except Exception as e:
        if current_app.debug:
            current_app.logger.exception('Design upload failed')
        return jsonify({'error': str(e) or 'Upload failed'}), 500
