from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import current_user
from models import Product, Design
from utils.order_artwork import FRONT_PLACEMENTS, mockup_urls
from werkzeug.utils import secure_filename
from utils.cloud_storage import image_url as _resolve_image_url
import json
import os
from pathlib import Path

cart_bp = Blueprint('cart', __name__, url_prefix='/cart')


def _back_overlay_class(meta):
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    if meta.get('name') or meta.get('number'):
        return 'back_name_number'
    return 'center_back'

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
        if not isinstance(item, dict) or not item.get('product_id'):
            continue
        product = Product.query.get(item.get('product_id'))
        if product:
            try:
                qty = int(item.get('quantity') or 0)
                unit_price = float(item.get('unit_price') or 0)
            except (TypeError, ValueError):
                continue
            item_total = qty * unit_price
            front_image, back_image = mockup_urls(product, item.get('color'))
            placement = item.get('placement') or 'center_chest'
            front_design = item.get('design_url') if (item.get('design_url') and placement in FRONT_PLACEMENTS) else None

            cart_items.append({
                **item,
                'product': product,
                'item_total': item_total,
                'image_url': front_image or None,
                'front_image': front_image,
                'back_image': back_image,
                'display_image': front_image,
                'design_overlay': front_design,
                'back_overlay': item.get('back_design_url'),
                'back_overlay_class': _back_overlay_class(item.get('back_design_meta')),
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
    _up = data.get('unit_price')
    unit_price_override = float(_up) if _up is not None else None
    print_specs = json.loads(data.get('print_specs', '{}')) if isinstance(data.get('print_specs'), str) else data.get('print_specs', {})
    
    # Validate
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    
    if not size or not color:
        return jsonify({'error': 'Size and color are required'}), 400

    from utils.group_orders import (
        design_allowed_for_collection,
        get_active_collection,
        ordering_blocked,
    )
    collection = get_active_collection()
    if collection:
        blocked = ordering_blocked(collection, product_id)
        if blocked:
            return jsonify({'error': blocked}), 400
    
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
            try:
                from services.image_processing import process_artwork_file
                _res = process_artwork_file(filepath, mode='auto')
                if _res.get('path') is not None:
                    unique_filename = _res['path'].name
            except Exception:
                pass
            design_url = f"/static/uploads/designs/{unique_filename}"
    elif design_id:
        # Gallery design, collection design, or user's own design
        from models import Design
        design = Design.query.get(int(design_id))
        if design:
            is_gallery = getattr(design, 'is_gallery', False)
            is_own = current_user.is_authenticated and design.uploaded_by_user_id == current_user.id
            is_collection_design = collection and design_allowed_for_collection(design, collection)
            if is_gallery or is_own or is_collection_design:
                design_url = _resolve_image_url(design.file_path)
    
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
            # Generated name/number transfers are already transparent production
            # art. Background-cut would eat white letters and collapse spacing.
            is_name_number = bool(
                (data.get('back_design_name') or '').strip()
                or (data.get('back_design_number') or '').strip()
            )
            if not is_name_number:
                try:
                    from services.image_processing import process_artwork_file
                    _res = process_artwork_file(filepath, mode='auto')
                    if _res.get('path') is not None:
                        unique_filename = _res['path'].name
                except Exception:
                    pass
            back_design_url = f"/static/uploads/designs/{unique_filename}"
    elif data.get('back_design_url'):
        back_design_url = data.get('back_design_url')

    # Capture readable back-design details (name/number/colors) so they appear
    # in the order record and production sheet, not just baked into the image.
    back_design_meta = None
    _bd_name = (data.get('back_design_name') or '').strip()
    _bd_number = (data.get('back_design_number') or '').strip()
    if _bd_name or _bd_number:
        def _meta_float(key):
            raw = data.get(key)
            if raw in (None, ''):
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        back_design_meta = {
            'name': _bd_name,
            'number': _bd_number,
            'font': (data.get('back_design_font') or '').strip(),
            'font_weight': 'bold',
            'font_style': 'normal',
            'text_color': (data.get('back_design_text_color') or '').strip(),
            'outline': (data.get('back_design_outline') or '').strip().lower() == 'true',
            'outline_color': (data.get('back_design_outline_color') or '').strip(),
            'name_letter_spacing_em': _meta_float('name_letter_spacing_em'),
            'number_tracking_em': _meta_float('number_tracking_em'),
            'condense': _meta_float('name_condense'),
            'number_scale': _meta_float('number_condense'),
            'layout_version': 2,
        }
    
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
    
    # Determine whether this item is blank (no design / transfer)
    has_design = bool(design_url or design_id or
                      'design' in request.files and request.files['design'].filename)
    is_blank = not has_design

    # Unit price: use override from customizer (includes placement discount, back design fee, size upcharge) or calculate
    if unit_price_override is not None:
        unit_price = float(unit_price_override)
        # If blank, subtract $12 from whatever the customizer sent (customizer may not know about this discount)
        if is_blank:
            unit_price = max(0.0, unit_price - 12.0)
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
        # Blank item discount — no design/transfer ordered
        if is_blank:
            unit_price = max(0.0, unit_price - 12.0)
    # Add custom design fee ($4 or $20) when design was created from "Have Us Recreate"
    if design_id:
        design = Design.query.get(design_id)
        if design and getattr(design, 'design_fee', 0):
            unit_price += float(design.design_fee)
    
    # Transfer production — one source of truth (utils.print_sizes)
    from utils.print_sizes import build_item_production
    from PIL import Image as _PILImage

    aspect_w = None
    aspect_h = None
    try:
        aw = data.get('design_width')
        ah = data.get('design_height')
        if aw and ah:
            aspect_w, aspect_h = float(aw), float(ah)
    except (TypeError, ValueError):
        pass
    if (not aspect_w or not aspect_h) and design_id:
        _d = Design.query.get(int(design_id)) if str(design_id).isdigit() else None
        if _d and _d.width and _d.height:
            aspect_w, aspect_h = float(_d.width), float(_d.height)
    if (not aspect_w or not aspect_h) and design_url and design_url.startswith('/static/'):
        try:
            _p = Path(design_url[len('/static/'):])
            if not _p.is_absolute():
                _p = Path('static') / _p
            with _PILImage.open(_p) as _im:
                aspect_w, aspect_h = float(_im.size[0]), float(_im.size[1])
        except Exception:
            pass

    design_name = None
    if design_id:
        _d = Design.query.get(int(design_id)) if str(design_id).isdigit() else None
        if _d:
            design_name = _d.title or _d.original_filename or _d.filename
    if not design_name and design_url:
        design_name = design_url.split('/')[-1]

    # Natural (pre-squeeze) widths. Falling back to a stored final width keeps
    # older carts working; the squeeze rules live in print_sizes.
    measured_name_w = (data.get('name_width_in')
                       or (back_design_meta or {}).get('name_width_natural')
                       or (back_design_meta or {}).get('name_width'))
    measured_number_w = (data.get('number_width_in')
                         or (back_design_meta or {}).get('number_width_natural')
                         or (back_design_meta or {}).get('number_width'))
    try:
        measured_name_w = float(measured_name_w) if measured_name_w not in (None, '') else None
    except (TypeError, ValueError):
        measured_name_w = None
    try:
        measured_number_w = float(measured_number_w) if measured_number_w not in (None, '') else None
    except (TypeError, ValueError):
        measured_number_w = None

    customer_name = None
    if current_user.is_authenticated:
        customer_name = (getattr(current_user, 'name', None) or getattr(current_user, 'full_name', None)
                         or getattr(current_user, 'email', None))

    has_front = bool(design_url or design_id)
    transfer_production = build_item_production(
        product=product,
        size=size,
        color=color,
        placement=placement,
        quantity=quantity,
        design_name=design_name,
        design_id=int(design_id) if design_id and str(design_id).isdigit() else None,
        aspect_w=aspect_w,
        aspect_h=aspect_h,
        has_front=has_front,
        back_name=(back_design_meta or {}).get('name'),
        back_number=(back_design_meta or {}).get('number'),
        back_font=(back_design_meta or {}).get('font'),
        back_text_color=(back_design_meta or {}).get('text_color'),
        back_outline=(back_design_meta or {}).get('outline'),
        back_outline_color=(back_design_meta or {}).get('outline_color'),
        customer_name=customer_name,
        measured_name_width=measured_name_w,
        measured_number_width=measured_number_w,
    )

    if back_design_meta and transfer_production.get('back'):
        from utils.personalization_layout import enrich_back_snapshot
        back = transfer_production.get('back') or {}
        transfer_production['back'] = enrich_back_snapshot(back, extra=back_design_meta)
        back = transfer_production['back']
        back_design_meta.update({
            'name_width': back.get('name_width'),
            'name_width_natural': back.get('name_width_natural'),
            'name_height': back.get('name_height'),
            'number_width': back.get('number_width'),
            'number_width_natural': back.get('number_width_natural'),
            'number_height': back.get('number_height'),
            'number_digits': back.get('number_digits'),
            'number_scale': back.get('number_scale'),
            'number_scale_percent': back.get('number_scale_percent'),
            'gap': back.get('gap'),
            'combined_width': back.get('combined_width'),
            'combined_height': back.get('combined_height'),
            'condense': back.get('condense'),
            'condense_percent': back.get('condense_percent'),
            'age_group': back.get('age_group'),
            'category': back.get('category'),
            'layout_version': back.get('layout_version'),
            'font_file': back.get('font_file'),
            'name_letter_spacing_em': back.get('name_letter_spacing_em'),
            'number_tracking_em': back.get('number_tracking_em'),
        })

    front = (transfer_production or {}).get('front') or {}
    print_width = front.get('width')
    print_height = front.get('height')
    if print_width is None and transfer_production.get('back'):
        print_width = transfer_production['back'].get('combined_width')
        print_height = transfer_production['back'].get('combined_height')
    
    # Create cart item
    cart_item = {
        'product_id': product_id,
        'size': size,
        'color': color,
        'quantity': quantity,
        'unit_price': unit_price,
        'is_blank': is_blank,
        'design_id': design_id,
        'design_url': design_url,
        'placement': placement,
        'back_design_url': back_design_url,
        'back_design_meta': back_design_meta,
        'proof_front_url': proof_front_url,
        'proof_back_url': proof_back_url,
        'print_width': print_width,
        'print_height': print_height,
        'transfer_production': transfer_production,
        'position_x': print_specs.get('x'),
        'position_y': print_specs.get('y'),
        'rotation': print_specs.get('rotation', 0),
        'proof_image': print_specs.get('proof_image'),
        'collection_id': collection.id if collection else None,
    }

    # Don't mix a group order with regular shop items (or another group)
    new_cid = cart_item['collection_id']
    mixed = [
        item for item in cart
        if isinstance(item, dict) and (item.get('collection_id') or None) != new_cid
    ]
    if mixed:
        cart[:] = [item for item in cart if isinstance(item, dict) and (item.get('collection_id') or None) == new_cid]
    
    # Check if identical item exists
    found = False
    for item in cart:
        if (item['product_id'] == product_id and 
            item['size'] == size and 
            item['color'] == color and
            item.get('design_id') == design_id and
            item.get('placement') == placement and
            item.get('back_design_url') == back_design_url and
            item.get('back_design_meta') == back_design_meta):
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
