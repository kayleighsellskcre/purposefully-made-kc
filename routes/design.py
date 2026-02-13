"""
Design upload and processing routes
Handles background removal and image optimization
"""
from flask import Blueprint, request, jsonify
from flask_login import current_user
from werkzeug.utils import secure_filename
from pathlib import Path
import os
import time

design_bp = Blueprint('design', __name__, url_prefix='/design')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _create_design_record_if_requested(final_filename, original_filename, width, height):
    """Create Design record when user is logged in and share_in_gallery preference is set."""
    if not current_user.is_authenticated:
        return None
    share_val = request.form.get('share_in_gallery', '').lower()
    if share_val not in ('true', 'false'):
        return None
    from models import Design, db
    is_gallery = share_val == 'true'
    title = (original_filename or 'Design').rsplit('.', 1)[0].replace('_', ' ').title()
    design = Design(
        filename=final_filename,
        original_filename=original_filename,
        file_path=f"uploads/designs/{final_filename}",
        is_gallery=is_gallery,
        title=title,
        uploaded_by_user_id=current_user.id,
        width=width,
        height=height,
    )
    try:
        full_path = Path('static/uploads/designs') / final_filename
        if full_path.exists():
            design.file_size = full_path.stat().st_size
    except Exception:
        pass
    db.session.add(design)
    db.session.commit()
    return design.id

@design_bp.route('/upload', methods=['POST'])
def upload():
    """Upload and process design image"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Use PNG, JPG, or WEBP'}), 400
    
    # Save original file
    filename = secure_filename(file.filename)
    timestamp = int(time.time())
    name, ext = os.path.splitext(filename)
    
    upload_dir = Path('static/uploads/designs')
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    original_filename = f"{name}_{timestamp}_original{ext}"
    original_path = upload_dir / original_filename
    file.save(str(original_path))
    
    # Process background removal if requested
    remove_bg = request.form.get('remove_background', 'true').lower() == 'true'
    final_filename = None
    width, height = None, None
    
    if remove_bg:
        try:
            from rembg import remove
            from PIL import Image
            
            # Remove background
            input_image = Image.open(original_path)
            output_image = remove(input_image)
            
            # Save processed image
            processed_filename = f"{name}_{timestamp}_nobg.png"
            processed_path = upload_dir / processed_filename
            output_image.save(str(processed_path))
            
            width, height = output_image.size
            final_filename = processed_filename
            url = f"/static/uploads/designs/{processed_filename}"
            
            design_id = _create_design_record_if_requested(processed_filename, file.filename, width, height)
            
            return jsonify({
                'success': True,
                'original_url': f"/static/uploads/designs/{original_filename}",
                'processed_url': url,
                'url': url,
                'width': width,
                'height': height,
                'background_removed': True,
                'design_id': design_id
            })
        except Exception as e:
            # If background removal fails, return original
            from PIL import Image
            img = Image.open(original_path)
            width, height = img.size
            final_filename = original_filename
            url = f"/static/uploads/designs/{original_filename}"
            
            design_id = _create_design_record_if_requested(original_filename, file.filename, width, height)
            
            return jsonify({
                'success': True,
                'url': url,
                'width': width,
                'height': height,
                'background_removed': False,
                'note': 'Background removal failed, using original image',
                'design_id': design_id
            })
    else:
        # No background removal
        from PIL import Image
        img = Image.open(original_path)
        width, height = img.size
        final_filename = original_filename
        url = f"/static/uploads/designs/{original_filename}"
        
        design_id = _create_design_record_if_requested(original_filename, file.filename, width, height)
        
        return jsonify({
            'success': True,
            'url': url,
            'width': width,
            'height': height,
            'background_removed': False,
            'design_id': design_id
        })
