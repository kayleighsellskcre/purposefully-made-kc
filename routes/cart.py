from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import current_user
from models import Product, ProductColorVariant, Design
from werkzeug.utils import secure_filename
import json
import os
from pathlib import Path

cart_bp = Blueprint('cart', __name__, url_prefix='/cart')

def get_cart():
    """Get cart from session. Isolate per user - clear if cart belongs to different user."""
    owner = session.get('cart_owner_id')
    if current_user.is_authenticated:
        if owner != current_user.id:
            session['cart'] = []
            session['cart_owner_id'] = current_user.id
            session.modified = True
    else:
        if owner not in (None, 'guest'):
            session['cart'] = []
            session['cart_owner_id'] = 'guest'
            session.modified = True
    if 'cart' not in session:
        session['cart'] = []
        session['cart_owner_id'] = current_user.id if current_user.is_authenticated else 'guest'
        session.modified = True
    return session['cart']

def save_cart(cart):
    """Save cart to session"""
    session['cart'] = cart
    session['cart_owner_id'] = current_user.id if current_user.is_authenticated else 'guest'
    session.modified = True

@cart_bp.route('/')
def index():
    """View cart"""
    cart = get_cart()
    
    # Enrich cart items with product details
    cart_items = []
    subtotal = 0
    
    for item in cart:
        product = Product.query.get(item['product_id'])
        if product:
            item_total = item['quantity'] * item['unit_price']
            # Get color-specific front and back images for cart display
            front_image = None
            back_image = None
            variant = ProductColorVariant.query.filter_by(
                product_id=product.id,
                color_name=item['color']
            ).first()
            if variant:
                if variant.front_image_url:
                    front_image = variant.front_image_url if variant.front_image_url.startswith(('/', 'http')) else f"/static/{variant.front_image_url}"
                if variant.back_image_url:
                    back_image = variant.back_image_url if variant.back_image_url.startswith(('/', 'http')) else f"/static/{variant.back_image_url}"
            # Front of shirt only, with design overlay when placement is front
            placement = item.get('placement') or 'center_chest'
            front_placements = ('center_chest', 'left_chest', 'right_chest')
            front_design = item.get('design_url') if (item.get('design_url') and placement in front_placements) else None

            cart_items.append({
                **item,
                'product': product,
                'item_total': item_total,
                'image_url': front_image or None,
                'front_image': front_image,
                'back_image': back_image,
                'display_image': front_image,
                'design_overlay': front_design,
                'placement': placement
            })
            subtotal += item_total
    
    return render_template('cart/index.html', 
                         cart_items=cart_items,
                         subtotal=subtotal)


@cart_bp.route('/add', methods=['POST'])
def add():
    """Add item to cart"""
    # Handle both JSON and FormData (for file uploads)
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    
    product_id = int(data.get('product_id'))
    size = data.get('size')
    color = data.get('color')
    quantity = int(data.get('quantity', 1))
    design_id = data.get('design_id')
    placement = data.get('placement')
    unit_price_override = data.get('unit_price', type=float)
    print_specs = json.loads(data.get('print_specs', '{}')) if isinstance(data.get('print_specs'), str) else data.get('print_specs', {})
    
    # Validate
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    
    if not size or not color:
        return jsonify({'error': 'Size and color are required'}), 400
    
    cart = get_cart()
    
    # Handle design: uploaded file or gallery design_id
    design_url = None
    if 'design' in request.files:
        design_file = request.files['design']
        if design_file and design_file.filename:
            # Save uploaded design
            filename = secure_filename(design_file.filename)
            upload_dir = Path('static/uploads/designs')
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            # Add timestamp to avoid conflicts
            import time
            timestamp = int(time.time())
            name, ext = os.path.splitext(filename)
            unique_filename = f"{name}_{timestamp}{ext}"
            
            filepath = upload_dir / unique_filename
            design_file.save(str(filepath))
            design_url = f"/static/uploads/designs/{unique_filename}"
    elif design_id:
        # Gallery design or user's own design - get URL from Design model
        from models import Design
        from flask_login import current_user
        design = Design.query.get(int(design_id))
        if design:
            # Allow: gallery design, or user's own design (profile-only)
            is_gallery = getattr(design, 'is_gallery', False)
            is_own = current_user.is_authenticated and design.uploaded_by_user_id == current_user.id
            if is_gallery or is_own:
                design_url = f"/static/{design.file_path}"
    
    # Handle back design: uploaded file or URL (from prior upload)
    import time as _t
    back_design_url = None
    if 'back_design' in request.files:
        back_file = request.files['back_design']
        if back_file and back_file.filename:
            filename = secure_filename(back_file.filename)
            upload_dir = Path('static/uploads/designs')
            upload_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(_t.time())
            name, ext = os.path.splitext(filename)
            unique_filename = f"back_{name}_{timestamp}{ext}"
            filepath = upload_dir / unique_filename
            back_file.save(str(filepath))
            back_design_url = f"/static/uploads/designs/{unique_filename}"
    elif data.get('back_design_url'):
        back_design_url = data.get('back_design_url')
    
    # Save proof images (design composited on shirt) for cart display
    proof_front_url = None
    proof_back_url = None
    if 'proof_front' in request.files:
        pf = request.files['proof_front']
        if pf and pf.filename:
            upload_dir = Path('static/uploads/proofs')
            upload_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(_t.time())
            pf_name = f"proof_front_{timestamp}.png"
            pf.save(str(upload_dir / pf_name))
            proof_front_url = f"/static/uploads/proofs/{pf_name}"
    if 'proof_back' in request.files:
        pb = request.files['proof_back']
        if pb and pb.filename:
            upload_dir = Path('static/uploads/proofs')
            upload_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(_t.time())
            pb_name = f"proof_back_{timestamp}.png"
            pb.save(str(upload_dir / pb_name))
            proof_back_url = f"/static/uploads/proofs/{pb_name}"
    
    # Unit price: use override from customizer (includes placement discount, back design fee, size upcharge) or calculate
    if unit_price_override is not None:
        unit_price = float(unit_price_override)
    else:
        unit_price = product.base_price
        if placement in ('left_chest', 'right_chest'):
            unit_price -= 2.0
        # Size upcharge for adult 2XL+ ($2, $3, $4)
        if size and 'youth' not in (product.name or '').lower():
            s = str(size).upper()
            if s in ('2XL', '2X', 'XXL'):
                unit_price += 2
            elif s in ('3XL', '3X', 'XXXL'):
                unit_price += 3
            elif s in ('4XL', '4X'):
                unit_price += 4
    # Add custom design fee ($4 or $20) when design was created from "Have Us Recreate"
    if design_id:
        design = Design.query.get(design_id)
        if design and getattr(design, 'design_fee', 0):
            unit_price += float(design.design_fee)
    
    # Calculate correct print dimensions for size (youth vs adult)
    from utils.print_sizes import get_print_width_for_size
    print_width = print_specs.get('width')
    print_height = print_specs.get('height')
    is_youth_product = product and (
        'youth' in (product.name or '').lower() or
        (getattr(product, 'category', '') or '').lower() == 'youth'
    )
    if print_width is None or is_youth_product:
        pw = get_print_width_for_size(size, product)
        if pw is not None:
            print_width = pw
            print_height = print_height or pw  # Square logo when calculated from size
    elif print_height is None and print_width:
        print_height = print_width
    
    # Create cart item
    cart_item = {
        'product_id': product_id,
        'size': size,
        'color': color,
        'quantity': quantity,
        'unit_price': unit_price,
        'design_id': design_id,
        'design_url': design_url,
        'placement': placement,
        'back_design_url': back_design_url,
        'proof_front_url': proof_front_url,
        'proof_back_url': proof_back_url,
        'print_width': print_width,
        'print_height': print_height,
        'position_x': print_specs.get('x'),
        'position_y': print_specs.get('y'),
        'rotation': print_specs.get('rotation', 0),
        'proof_image': print_specs.get('proof_image')
    }
    
    # Check if identical item exists
    found = False
    for item in cart:
        if (item['product_id'] == product_id and 
            item['size'] == size and 
            item['color'] == color and
            item.get('design_id') == design_id and
            item.get('placement') == placement and
            item.get('back_design_url') == back_design_url):
            item['quantity'] += quantity
            found = True
            break
    
    if not found:
        cart.append(cart_item)
    
    save_cart(cart)
    
    cart_count = sum(item['quantity'] for item in cart)
    
    return jsonify({
        'success': True,
        'message': 'Added to cart',
        'cart_count': cart_count
    })


@cart_bp.route('/update/<int:index>', methods=['POST'])
def update(index):
    """Update cart item quantity"""
    data = request.get_json()
    quantity = data.get('quantity', 1)
    
    if quantity < 1:
        return jsonify({'error': 'Invalid quantity'}), 400
    
    cart = get_cart()
    
    if index < 0 or index >= len(cart):
        return jsonify({'error': 'Item not found'}), 404
    
    cart[index]['quantity'] = quantity
    save_cart(cart)
    
    return jsonify({'success': True})


@cart_bp.route('/remove/<int:index>', methods=['POST'])
def remove(index):
    """Remove item from cart"""
    cart = get_cart()
    
    if index < 0 or index >= len(cart):
        return jsonify({'error': 'Item not found'}), 404
    
    cart.pop(index)
    save_cart(cart)
    
    return jsonify({'success': True})


@cart_bp.route('/clear', methods=['POST'])
def clear():
    """Clear cart"""
    session['cart'] = []
    session.modified = True
    return jsonify({'success': True})
