"""Custom design requests - customers upload reference images for recreation"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from models import db, CustomDesignRequest, Design

custom_request_bp = Blueprint('custom_request', __name__, url_prefix='/custom-design')


def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in {'png', 'jpg', 'jpeg', 'webp'}


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
            flash('Please upload a PNG, JPG, or WEBP image.', 'error')
            return redirect(url_for('custom_request.submit'))
        
        # Save reference image (Cloudinary if configured, local fallback for dev)
        from utils.cloud_storage import upload_image
        relative_path = upload_image(
            file,
            current_app._get_current_object(),
            subfolder='custom_requests',
            public_id_prefix=f'request_{current_user.id}',
        )
        
        req = CustomDesignRequest(
            user_id=current_user.id,
            reference_file_path=relative_path,
            reference_original_filename=file.filename,
            description=description,
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
        
        # Notify admin via SMS
        try:
            from utils.sms import send_design_request_alert
            send_design_request_alert(current_app, current_user.full_name, req.id)
        except Exception:
            pass
        
        flash('Your request has been submitted! We\'ll recreate your design and add it to your profile. You\'ll be able to order any style, color, or shirt you want.', 'success')
        return redirect(url_for('account.my_designs'))
    
    return render_template('custom_request/submit.html')


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
