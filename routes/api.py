from flask import Blueprint, request, jsonify, current_app, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename
from models import db, Design, Product, ProductColorVariant
from PIL import Image
from utils.mockups import get_mockup_url_for_variant, _find_mockup_file
import os
import secrets
import json

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/cron/sync-ss', methods=['GET', 'POST'])
def cron_sync_ss():
    """
    Daily S&S Activewear sync. Call from cron-job.org or similar.
    Requires SYNC_CRON_TOKEN in env and ?token=XXX in request.
    Syncs full catalog (styles, colors, sizes, inventory) from S&S.
    """
    token = request.args.get('token') or (request.get_json() or {}).get('token')
    expected = os.environ.get('SYNC_CRON_TOKEN')
    if not expected or token != expected:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from services.ssactivewear_api import SSActivewearAPI
        from models import Product

        api = SSActivewearAPI()
        # Sync only styles that have mockup folders - fetches each directly from S&S Products API
        products_data = api.sync_mockup_styles()

        if not products_data:
            return jsonify({'ok': False, 'error': 'No products returned from S&S API'}), 200

        added = updated = color_variants_added = 0
        for product_data in products_data:
            color_variants_data = product_data.pop('color_variants', [])
            style_num = product_data.get('style_number')
            existing = Product.query.filter_by(style_number=style_num).first()

            if existing:
                existing.name = product_data['name']
                existing.category = product_data['category']
                existing.description = product_data['description']
                existing.base_price = product_data['base_price']
                existing.wholesale_cost = product_data.get('wholesale_cost', 0)
                existing.available_sizes = product_data['available_sizes']
                existing.available_colors = product_data['available_colors']
                existing.brand = product_data.get('brand', 'Bella+Canvas')
                existing.api_data = product_data.get('api_data')
                existing.front_mockup_template = product_data.get('front_mockup_template') or existing.front_mockup_template
                existing.back_mockup_template = product_data.get('back_mockup_template') or existing.back_mockup_template
                updated += 1
            else:
                existing = Product(**product_data)
                db.session.add(existing)
                db.session.flush()
                added += 1

            for variant_data in color_variants_data:
                cv = ProductColorVariant.query.filter_by(
                    product_id=existing.id, color_name=variant_data['color_name']
                ).first()
                if cv:
                    cv.front_image_url = variant_data.get('front_image') or cv.front_image_url
                    cv.back_image_url = variant_data.get('back_image') or cv.back_image_url
                    cv.size_inventory = variant_data.get('size_inventory')
                else:
                    db.session.add(ProductColorVariant(
                        product_id=existing.id,
                        color_name=variant_data['color_name'],
                        color_hex=variant_data.get('color_hex'),
                        front_image_url=variant_data.get('front_image'),
                        back_image_url=variant_data.get('back_image'),
                        size_inventory=variant_data.get('size_inventory'),
                        ss_color_id=variant_data.get('color_id'),
                    ))
                    color_variants_added += 1

        db.session.commit()
        return jsonify({
            'ok': True,
            'products_added': added,
            'products_updated': updated,
            'color_variants_added': color_variants_added,
            'total': len(products_data),
        })
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 200
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

def analyze_image(file_path):
    """Analyze image properties"""
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            
            # Check for transparency
            has_transparency = False
            if img.mode in ('RGBA', 'LA', 'P'):
                if img.mode == 'P':
                    # Check if palette has transparency
                    has_transparency = 'transparency' in img.info
                else:
                    # Check alpha channel
                    alpha = img.getchannel('A') if 'A' in img.getbands() else None
                    if alpha and alpha.getextrema()[0] < 255:
                        has_transparency = True
            
            # Get DPI
            dpi = img.info.get('dpi', (72, 72))[0] if 'dpi' in img.info else 72
            
            return {
                'width': width,
                'height': height,
                'has_transparency': has_transparency,
                'dpi': int(dpi)
            }
    except Exception as e:
        print(f"Error analyzing image: {e}")
        return None

@api_bp.route('/upload-design', methods=['POST'])
def upload_design():
    """Upload design artwork"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, SVG, PDF'}), 400
    
    # Generate unique filename
    original_filename = secure_filename(file.filename)
    extension = original_filename.rsplit('.', 1)[1].lower()
    filename = f"{secrets.token_hex(16)}.{extension}"
    
    # Save file
    upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'designs', filename)
    file.save(upload_path)
    
    # Get file size
    file_size = os.path.getsize(upload_path)
    
    # Analyze image (if it's an image)
    image_info = None
    if extension in ['png', 'jpg', 'jpeg']:
        image_info = analyze_image(upload_path)
    
    # Create design record
    design = Design(
        filename=filename,
        original_filename=original_filename,
        file_path=f"uploads/designs/{filename}",
        file_size=file_size,
        uploaded_by_user_id=current_user.id if current_user.is_authenticated else None
    )
    
    if image_info:
        design.width = image_info['width']
        design.height = image_info['height']
        design.has_transparency = image_info['has_transparency']
        design.dpi = image_info['dpi']
    
    db.session.add(design)
    db.session.commit()
    
    # Prepare warnings
    warnings = []
    if image_info:
        if image_info['dpi'] < 150:
            warnings.append('Low resolution detected. Image may not print clearly.')
        if not image_info['has_transparency']:
            warnings.append('No transparent background detected. Consider removing background for best results.')
    
    return jsonify({
        'success': True,
        'design': {
            'id': design.id,
            'filename': design.filename,
            'file_path': design.file_path,
            'width': design.width,
            'height': design.height,
            'has_transparency': design.has_transparency,
            'dpi': design.dpi
        },
        'warnings': warnings
    })


@api_bp.route('/generate-proof', methods=['POST'])
def generate_proof():
    """Generate proof image of design on product"""
    data = request.get_json()
    
    product_id = data.get('product_id')
    design_id = data.get('design_id')
    color = data.get('color')
    placement = data.get('placement')
    specs = data.get('specs', {})
    
    # TODO: Implement actual mockup generation
    # This would use PIL or a service to composite the design onto the mockup
    
    # For now, return placeholder
    proof_filename = f"proof_{secrets.token_hex(8)}.png"
    proof_path = f"uploads/proofs/{proof_filename}"
    
    return jsonify({
        'success': True,
        'proof_image': proof_path
    })


@api_bp.route('/products/<int:product_id>/mockup')
def get_product_mockup(product_id):
    """Get product mockup data; when color is provided, use color-specific mockup from variant or uploads/mockups."""
    product = Product.query.get_or_404(product_id)
    
    color = request.args.get('color')
    view = request.args.get('view', 'front')  # front or back
    
    mockup_path = None
    if color:
        variant = ProductColorVariant.query.filter_by(
            product_id=product.id, color_name=color
        ).first()
        if variant:
            mockup_path = get_mockup_url_for_variant(product, variant, view, current_app)
        if not mockup_path:
            rel = _find_mockup_file(current_app, product.style_number, color, view)
            if rel:
                mockup_path = url_for('main.serve_mockup', path=rel)
    if not mockup_path:
        mockup_path = product.front_mockup_template if view == 'front' else product.back_mockup_template
    
    # Get print area configuration
    print_area_config = json.loads(product.print_area_config) if product.print_area_config else {}
    
    return jsonify({
        'mockup_path': mockup_path,
        'print_area_config': print_area_config
    })


@api_bp.route('/validate-design', methods=['POST'])
def validate_design():
    """Validate design specifications"""
    data = request.get_json()
    
    design_id = data.get('design_id')
    print_width = data.get('print_width')  # inches
    print_height = data.get('print_height')  # inches
    
    design = Design.query.get(design_id)
    if not design:
        return jsonify({'error': 'Design not found'}), 404
    
    warnings = []
    errors = []
    
    # Calculate DPI at print size
    if design.width and design.height and print_width and print_height:
        dpi_width = design.width / print_width
        dpi_height = design.height / print_height
        min_dpi = min(dpi_width, dpi_height)
        
        if min_dpi < 150:
            warnings.append(f'Print resolution will be {int(min_dpi)} DPI. Recommended minimum is 150 DPI.')
        elif min_dpi < 200:
            warnings.append(f'Print resolution is {int(min_dpi)} DPI. Higher resolution recommended for best quality.')
    
    # Check transparency
    if not design.has_transparency:
        warnings.append('Design does not have a transparent background. White areas will print as white.')
    
    # Check file size
    if design.file_size and design.file_size > 10 * 1024 * 1024:  # 10MB
        warnings.append('Large file size may slow down processing.')
    
    return jsonify({
        'valid': len(errors) == 0,
        'warnings': warnings,
        'errors': errors
    })


@api_bp.route('/collections/check-slug', methods=['POST'])
def check_collection_slug():
    """Check if collection slug is available"""
    from models import Collection
    
    slug = request.get_json().get('slug')
    collection_id = request.get_json().get('collection_id')
    
    query = Collection.query.filter_by(slug=slug)
    if collection_id:
        query = query.filter(Collection.id != collection_id)
    
    exists = query.first() is not None
    
    return jsonify({
        'available': not exists
    })
