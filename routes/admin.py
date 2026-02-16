from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from sqlalchemy import or_
from flask_login import login_required, current_user
from functools import wraps
from models import (db, Product, Collection, Order, OrderItem, Design, User, ProductColorVariant,
                    Vendor, ApparelInventory, TransferInventory, Supply, GrowthMetric, FinancialEntry,
                    CustomDesignRequest)
from werkzeug.utils import secure_filename
from datetime import datetime
import json
import os
import csv
from io import StringIO, BytesIO
from pathlib import Path

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Only this email is allowed to access admin. All other users get customer portals only.
ADMIN_EMAIL = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').lower()

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to continue.', 'error')
            return redirect(url_for('auth.login'))
        # Restrict admin to the single admin email only; no one else can use admin.
        if (current_user.email or '').lower() != ADMIN_EMAIL or not getattr(current_user, 'is_admin', False):
            flash('Access denied. Admin access is restricted.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def _save_uploaded_design(file, user_id):
    """Save an uploaded file to the Design gallery. Returns Design or None."""
    if not file or not file.filename:
        return None
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return None
    name, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in ['.png', '.jpg', '.jpeg', '.webp']:
        return None
    upload_dir = Path('static/uploads/designs')
    upload_dir.mkdir(parents=True, exist_ok=True)
    import time
    timestamp = int(time.time())
    unique_name = f"gallery_{name}_{timestamp}{ext}"
    filepath = upload_dir / unique_name
    file.save(str(filepath))
    title = name.replace('_', ' ').title()
    design = Design(
        filename=unique_name,
        original_filename=file.filename,
        file_path=f"uploads/designs/{unique_name}",
        is_gallery=True,
        title=title,
        folder='custom_orders',
        uploaded_by_user_id=user_id
    )
    try:
        from PIL import Image
        img = Image.open(filepath)
        design.width, design.height = img.size
        design.file_size = filepath.stat().st_size
    except Exception:
        pass
    db.session.add(design)
    db.session.flush()
    return design


def _save_design_for_user(file, user_id, title=None, design_fee=0):
    """Save an uploaded file as a design for a specific user (not gallery). Returns Design or None."""
    if not file or not file.filename:
        return None
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return None
    name, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in ['.png', '.jpg', '.jpeg', '.webp']:
        return None
    upload_dir = Path('static/uploads/designs')
    upload_dir.mkdir(parents=True, exist_ok=True)
    import time
    timestamp = int(time.time())
    unique_name = f"user_{user_id}_{name}_{timestamp}{ext}"
    filepath = upload_dir / unique_name
    file.save(str(filepath))
    design = Design(
        filename=unique_name,
        original_filename=file.filename,
        file_path=f"uploads/designs/{unique_name}",
        is_gallery=False,
        title=title or name.replace('_', ' ').title(),
        folder='custom_orders',
        uploaded_by_user_id=user_id,
        design_fee=float(design_fee or 0)
    )
    try:
        from PIL import Image
        img = Image.open(filepath)
        design.width, design.height = img.size
        design.file_size = filepath.stat().st_size
    except Exception:
        pass
    db.session.add(design)
    db.session.flush()
    return design


@admin_bp.route('/')
@admin_required
def index():
    """Admin dashboard"""
    # Statistics
    total_orders = Order.query.count()
    pending_orders = Order.query.filter(Order.status.in_(['new', 'paid'])).count()
    in_production = Order.query.filter_by(status='in_production').count()
    total_revenue = db.session.query(db.func.sum(Order.total)).filter(
        Order.payment_status == 'paid'
    ).scalar() or 0
    pending_design_requests = CustomDesignRequest.query.filter_by(status='pending').count()
    
    # Recent orders
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    
    return render_template('admin/dashboard.html',
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         in_production=in_production,
                         total_revenue=total_revenue,
                         recent_orders=recent_orders,
                         pending_design_requests=pending_design_requests)


# ===== ORDERS =====

@admin_bp.route('/orders')
@admin_required
def orders():
    """Manage orders - Master Order Log"""
    status = request.args.get('status')
    collection_id = request.args.get('collection')
    order_type = request.args.get('order_type')
    page = request.args.get('page', 1, type=int)
    
    # Default to 'new' tab when no status filter (shows new + paid orders - most relevant)
    if status is None or status == '':
        redirect_args = {'status': 'new'}
        if collection_id:
            redirect_args['collection'] = collection_id
        if order_type:
            redirect_args['order_type'] = order_type
        return redirect(url_for('admin.orders', **redirect_args))
    
    query = Order.query
    
    if status and status != 'all':
        # "New" tab shows both new and paid (orders not yet in production)
        if status == 'new':
            query = query.filter(Order.status.in_(['new', 'paid']))
        else:
            query = query.filter_by(status=status)
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    if order_type:
        if order_type == 'retail':
            query = query.filter(or_(Order.order_type == 'retail', Order.order_type == None))
        else:
            query = query.filter_by(order_type=order_type)
    
    orders = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    collections = Collection.query.all()
    
    return render_template('admin/orders.html', 
                         orders=orders,
                         collections=collections,
                         selected_status=status,
                         selected_collection=collection_id,
                         selected_order_type=order_type)


@admin_bp.route('/orders/completed')
@admin_required
def orders_completed():
    """All completed/shipped orders — organized by month and year (removed from workflow)"""
    from collections import OrderedDict
    orders = Order.query.filter(
        Order.status.in_(['completed', 'shipped', 'picked_up'])
    ).order_by(Order.updated_at.desc()).all()
    # Group by (year, month)
    by_month = OrderedDict()
    for order in orders:
        # Use updated_at or created_at for grouping
        dt = order.updated_at or order.created_at
        key = (dt.year, dt.month)
        if key not in by_month:
            by_month[key] = []
        by_month[key].append(order)
    return render_template('admin/orders_completed.html', by_month=by_month)


@admin_bp.route('/orders/<int:order_id>')
@admin_required
def order_detail(order_id):
    """View order details"""
    from utils.print_sizes import get_print_width_for_size
    order = Order.query.get_or_404(order_id)
    def get_print_width(size, product=None):
        return get_print_width_for_size(size, product)
    def get_display_print_width(item):
        """Always use correct youth dimensions for display (fixes stored wrong values)."""
        return get_print_width_for_size(item.size, item.product) or item.print_width
    return render_template('admin/order_detail.html', order=order, get_print_width=get_print_width, get_display_print_width=get_display_print_width)


@admin_bp.route('/orders/<int:order_id>/update-status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    """Update order status and production stage"""
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    admin_notes = request.form.get('admin_notes')
    
    # Map status to production stage
    stage_map = {'new': 'order_received', 'paid': 'order_received', 'in_production': 'ready_to_press',
                 'ready': 'packaged_ready', 'shipped': 'packaged_ready', 'completed': 'packaged_ready'}
    order.status = new_status
    order.production_stage = stage_map.get(new_status, order.production_stage)
    
    if admin_notes:
        order.admin_notes = admin_notes
    
    # Update tracking info if shipped
    if new_status == 'shipped':
        tracking_number = request.form.get('tracking_number')
        carrier = request.form.get('carrier')
        if tracking_number:
            order.tracking_number = tracking_number
        if carrier:
            order.carrier = carrier
    
    db.session.commit()
    flash(f'Order status updated to {new_status}', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/update-details', methods=['POST'])
@admin_required
def update_order_details(order_id):
    """Update order details: due_date, order_type, cost_of_goods, profit"""
    order = Order.query.get_or_404(order_id)
    order.due_date = None
    if request.form.get('due_date'):
        try:
            order.due_date = datetime.fromisoformat(request.form.get('due_date'))
        except ValueError:
            pass
    order.order_type = request.form.get('order_type') or 'retail'
    order.cost_of_goods = float(request.form.get('cost_of_goods') or 0) or None
    if order.cost_of_goods is not None and order.total:
        order.profit = order.total - order.cost_of_goods
    else:
        order.profit = float(request.form.get('profit') or 0) or None
    order.is_refunded = request.form.get('is_refunded') == 'on'
    order.refund_notes = request.form.get('refund_notes')
    db.session.commit()
    flash('Order details updated', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/update-item/<int:item_id>', methods=['POST'])
@admin_required
def update_order_item(order_id, item_id):
    """Update order item: print_type, design_file_name"""
    item = OrderItem.query.filter_by(id=item_id, order_id=order_id).first_or_404()
    item.print_type = request.form.get('print_type') or item.print_type
    item.design_file_name = request.form.get('design_file_name') or item.design_file_name
    if item.design:
        item.design_file_name = item.design_file_name or item.design.filename
    db.session.commit()
    flash('Item updated', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


# ===== PRODUCTS =====

@admin_bp.route('/products')
@admin_required
def products():
    """Manage products"""
    import os
    products = Product.query.order_by(Product.style_number).all()

    # Compute size/color counts - use ProductColorVariant for colors (authoritative for display)
    for p in products:
        try:
            p.size_count = len(json.loads(p.available_sizes)) if p.available_sizes else 0
        except (TypeError, ValueError):
            p.size_count = 0
        # Color count: prefer ProductColorVariant count (what we actually show); fallback to JSON
        variant_count = ProductColorVariant.query.filter_by(product_id=p.id).count()
        try:
            parsed = json.loads(p.available_colors) if p.available_colors else []
            json_count = len(parsed) if isinstance(parsed, list) else 0
        except (TypeError, ValueError):
            json_count = 0
        p.color_count = variant_count if variant_count > 0 else min(json_count, 200)

    # Check if S&S API is configured - check environment variable directly
    api_key = os.getenv('SSACTIVEWEAR_API_KEY')
    api_configured = bool(api_key) and api_key != 'your_ss_activewear_api_key_here'

    return render_template('admin/products.html',
                         products=products,
                         api_configured=api_configured)


@admin_bp.route('/products/link-mockups', methods=['POST'])
@admin_required
def link_mockup_images():
    """Create missing products from mockup folders and link all color images. No S&S API needed."""
    from utils.mockups import create_products_from_mockup_folders, ensure_variant_mockup_urls
    try:
        created = create_products_from_mockup_folders(current_app)
        db.session.commit()
        ensure_variant_mockup_urls(current_app)
        db.session.commit()
        msg = f'Linked mockup images for all products.'
        if created:
            msg = f'Created {created} products from mockup folders. ' + msg
        flash(msg, 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/sync-api', methods=['POST'])
@admin_required
def sync_api():
    """Sync products from S&S Activewear API with color variants and inventory"""
    import sys
    
    print("="*80, file=sys.stderr, flush=True)
    print("ADMIN: STARTING S&S API SYNC WITH COLOR VARIANTS & INVENTORY", file=sys.stderr, flush=True)
    print("="*80, file=sys.stderr, flush=True)
    
    try:
        from services.ssactivewear_api import SSActivewearAPI
        from models import ProductColorVariant
        import os
        
        # Debug: Check environment
        api_key = os.getenv('SSACTIVEWEAR_API_KEY')
        account = os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER')
        print(f"ENV CHECK - API Key exists: {bool(api_key)}", file=sys.stderr, flush=True)
        print(f"ENV CHECK - Account: {account}", file=sys.stderr, flush=True)
        
        api = SSActivewearAPI()
        print("API CLIENT INITIALIZED", file=sys.stderr, flush=True)
        
        
        # Use mockup-styles sync: only syncs styles that have mockup folders in uploads/mockups
        # Works even when full catalog returns nothing (fetches each style directly)
        print("CALLING sync_mockup_styles...", file=sys.stderr, flush=True)
        try:
            products_data = api.sync_mockup_styles()
        except ValueError as e:
            flash(f'S&S API: {str(e)}. Creating products from mockup folders only.', 'warning')
            products_data = []
        print(f"PRODUCTS DATA RETURNED: {len(products_data) if products_data else 0}", file=sys.stderr, flush=True)

        if not products_data:
            print("No products from S&S - will create from mockup folders only", file=sys.stderr, flush=True)
        
        added = 0
        updated = 0
        color_variants_added = 0
        
        print(f"PROCESSING {len(products_data)} PRODUCTS FROM S&S...", file=sys.stderr, flush=True)
        for product_data in (products_data or []):
            # Extract color variants before saving product
            color_variants_data = product_data.pop('color_variants', [])
            
            style_num = product_data.get('style_number')
            existing = Product.query.filter_by(style_number=style_num).first()
            
            if existing:
                # Update existing
                existing.name = product_data['name']
                existing.category = product_data['category']
                existing.description = product_data['description']
                existing.base_price = product_data['base_price']
                existing.wholesale_cost = product_data.get('wholesale_cost', 0)
                existing.available_sizes = product_data['available_sizes']
                existing.available_colors = product_data['available_colors']
                existing.brand = product_data.get('brand', 'Bella+Canvas')
                existing.api_data = product_data.get('api_data')
                # Update sizing and fabric details
                existing.size_chart = product_data.get('size_chart')
                existing.fit_guide = product_data.get('fit_guide')
                existing.fabric_details = product_data.get('fabric_details')
                # Update images if provided
                if product_data.get('front_mockup_template'):
                    existing.front_mockup_template = product_data['front_mockup_template']
                if product_data.get('back_mockup_template'):
                    existing.back_mockup_template = product_data['back_mockup_template']
                product = existing
                updated += 1
                print(f"  UPDATED: {style_num}", file=sys.stderr, flush=True)
            else:
                # Add new
                product = Product(**product_data)
                db.session.add(product)
                added += 1
                print(f"  ADDED: {style_num}", file=sys.stderr, flush=True)
            
            # Flush to get product ID
            db.session.flush()
            
            # Save color variants with mockup images and inventory
            for variant_data in color_variants_data:
                existing_variant = ProductColorVariant.query.filter_by(
                    product_id=product.id,
                    color_name=variant_data['color_name']
                ).first()
                
                if existing_variant:
                    # Update existing variant
                    existing_variant.front_image_url = variant_data.get('front_image')
                    existing_variant.back_image_url = variant_data.get('back_image')
                    existing_variant.side_image_url = variant_data.get('side_image')
                    existing_variant.size_inventory = variant_data.get('size_inventory')
                    existing_variant.ss_color_id = variant_data.get('color_id')
                    existing_variant.last_synced = datetime.utcnow()
                else:
                    # Create new variant
                    new_variant = ProductColorVariant(
                        product_id=product.id,
                        color_name=variant_data['color_name'],
                        front_image_url=variant_data.get('front_image'),
                        back_image_url=variant_data.get('back_image'),
                        side_image_url=variant_data.get('side_image'),
                        size_inventory=variant_data.get('size_inventory'),
                        ss_color_id=variant_data.get('color_id')
                    )
                    db.session.add(new_variant)
                    color_variants_added += 1
            
            print(f"    {len(color_variants_data)} color variants synced", file=sys.stderr, flush=True)
        
        db.session.commit()

        # Create products from mockup folders when S&S doesn't have them
        from utils.mockups import create_products_from_mockup_folders
        created_from_mockups = create_products_from_mockup_folders(current_app)
        if created_from_mockups:
            db.session.commit()
            print(f"  CREATED {created_from_mockups} PRODUCTS FROM MOCKUP FOLDERS", file=sys.stderr, flush=True)

        from utils.mockups import ensure_variant_mockup_urls
        ensure_variant_mockup_urls(current_app)
        db.session.commit()

        print(f"COMMIT SUCCESSFUL! Added: {added}, Updated: {updated}, Color Variants: {color_variants_added}, From mockups: {created_from_mockups}", file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        msg = f'✅ Synced {len(products_data)} products with {color_variants_added} color variants!'
        if created_from_mockups:
            msg += f' Created {created_from_mockups} products from mockup folders.'
        flash(msg, 'success')
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        print("="*80, file=sys.stderr, flush=True)
        print("ERROR DURING SYNC:", file=sys.stderr, flush=True)
        print(error_details, file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        flash(f'Error syncing from API: {str(e)}', 'error')
    
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/add', methods=['GET', 'POST'])
@admin_required
def add_product():
    """Add new product"""
    if request.method == 'POST':
        product = Product(
            style_number=request.form.get('style_number'),
            name=request.form.get('name'),
            category=request.form.get('category'),
            description=request.form.get('description'),
            base_price=float(request.form.get('base_price')),
            wholesale_cost=float(request.form.get('wholesale_cost') or 0),
            is_active=request.form.get('is_active') == 'on',
            available_sizes=request.form.get('available_sizes'),  # JSON string
            available_colors=request.form.get('available_colors'),  # JSON string
            print_area_config=request.form.get('print_area_config')  # JSON string
        )
        
        db.session.add(product)
        db.session.commit()
        
        flash('Product added successfully', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/add_product.html')


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    """Edit product"""
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        from werkzeug.utils import secure_filename
        import os
        
        product.style_number = request.form.get('style_number')
        product.name = request.form.get('name')
        product.brand = request.form.get('brand')
        product.category = request.form.get('category')
        product.description = request.form.get('description')
        product.base_price = float(request.form.get('base_price'))
        product.wholesale_cost = float(request.form.get('wholesale_cost') or 0)
        product.is_active = request.form.get('is_active') == 'on'
        product.available_sizes = request.form.get('available_sizes')
        product.available_colors = request.form.get('available_colors')
        product.print_area_config = request.form.get('print_area_config')
        
        # Sizing and fabric details
        product.fit_guide = request.form.get('fit_guide')
        product.fabric_details = request.form.get('fabric_details')
        
        # Handle front image upload
        if 'front_image' in request.files:
            front_file = request.files['front_image']
            if front_file and front_file.filename:
                filename = secure_filename(f"{product.style_number}_front_{front_file.filename}")
                upload_path = os.path.join('static/uploads/products', filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                front_file.save(upload_path)
                product.front_mockup_template = f"uploads/products/{filename}"
        
        # Handle back image upload
        if 'back_image' in request.files:
            back_file = request.files['back_image']
            if back_file and back_file.filename:
                filename = secure_filename(f"{product.style_number}_back_{back_file.filename}")
                upload_path = os.path.join('static/uploads/products', filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                back_file.save(upload_path)
                product.back_mockup_template = f"uploads/products/{filename}"
        
        db.session.commit()
        flash('Product updated successfully', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/edit_product.html', product=product)


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    """Delete product"""
    product = Product.query.get_or_404(product_id)
    
    # Check if product has orders
    if product.order_items.count() > 0:
        flash('Cannot delete product with existing orders. Deactivate instead.', 'error')
        return redirect(url_for('admin.products'))
    
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted', 'success')
    return redirect(url_for('admin.products'))


# ===== COLLECTIONS =====

@admin_bp.route('/collections')
@admin_required
def collections():
    """Manage collections"""
    collections = Collection.query.order_by(Collection.created_at.desc()).all()
    return render_template('admin/collections.html', collections=collections)


@admin_bp.route('/collections/add', methods=['GET', 'POST'])
@admin_required
def add_collection():
    """Add new collection"""
    if request.method == 'POST':
        from slugify import slugify
        from sqlalchemy.exc import IntegrityError
        
        name = request.form.get('name')
        slug = (request.form.get('slug') or slugify(name)).strip() or slugify(name)
        # Ensure slug is unique - append number if taken
        base_slug = slug
        n = 1
        while Collection.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{n}"
            n += 1
        if slug != base_slug:
            flash(f'URL slug adjusted to "{slug}" (original was already in use).', 'info')
        
        collection = Collection(
            name=name,
            slug=slug,
            description=request.form.get('description'),
            is_active=request.form.get('is_active') == 'on',
            pickup_address=request.form.get('pickup_address'),
            pickup_instructions=request.form.get('pickup_instructions'),
            shipping_enabled=request.form.get('shipping_enabled') == 'on',
            tax_rate=float(request.form.get('tax_rate') or 0)
        )
        
        # Organizer's choices
        collection.restrict_options = request.form.get('restrict_options') == 'on'
        collection.allow_custom_upload = True  # Team can always upload their own designs
        allowed_colors = request.form.getlist('allowed_colors')
        collection.allowed_colors = json.dumps(allowed_colors) if allowed_colors else None
        allowed_placements = request.form.getlist('allowed_placements')
        collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None
        allowed_design_ids = list(request.form.getlist('allowed_designs'))
        upload_count = 0
        # Process uploaded design files
        for f in request.files.getlist('design_uploads'):
            if f and f.filename:
                design = _save_uploaded_design(f, current_user.id)
                if design:
                    allowed_design_ids.append(str(design.id))
                    upload_count += 1
        if allowed_design_ids:
            collection.allowed_design_ids = json.dumps([int(x) for x in allowed_design_ids])
        collection.back_design_font = request.form.get('back_design_font') or None
        
        # Set password if provided
        password = request.form.get('password')
        if password:
            collection.set_password(password)
        
        # Set deadline if provided
        deadline_str = request.form.get('order_deadline')
        if deadline_str:
            collection.order_deadline = datetime.fromisoformat(deadline_str)
        
        db.session.add(collection)
        db.session.flush()
        
        # Add products to collection
        product_ids = request.form.getlist('products')
        for product_id in product_ids:
            product = Product.query.get(int(product_id))
            if product:
                collection.products.append(product)
        
        try:
            db.session.commit()
            msg = 'Collection created successfully'
            if upload_count:
                msg += f' with {upload_count} design(s) uploaded'
            flash(msg + '.', 'success')
            return redirect(url_for('admin.collections'))
        except IntegrityError:
            db.session.rollback()
            flash('A collection with that name or URL already exists. Try a different name.', 'error')
            return redirect(url_for('admin.add_collection'))
    
    products = Product.query.filter_by(is_active=True).order_by(Product.style_number).all()
    try:
        from models import Design, ProductColorVariant
        gallery_designs = Design.query.filter_by(is_gallery=True).order_by(Design.uploaded_at.desc()).all()
        # All unique colors from active products (for color selection on create)
        all_colors = set()
        for p in products:
            for v in ProductColorVariant.query.filter_by(product_id=p.id).all():
                all_colors.add(v.color_name)
        all_colors = sorted(all_colors)
    except Exception:
        gallery_designs = []
        all_colors = []
    back_design_fonts = [
        ('Bebas Neue', 'Bebas Neue — Classic jersey'),
        ('Oswald', 'Oswald — Bold athletic'),
        ('Anton', 'Anton — Strong block'),
        ('Teko', 'Teko — College jersey'),
    ]
    return render_template('admin/add_collection.html', products=products, gallery_designs=gallery_designs or [], all_colors=all_colors, back_design_fonts=back_design_fonts)


@admin_bp.route('/collections/<int:collection_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_collection(collection_id):
    """Edit collection"""
    from models import ProductColorVariant, Design
    import json

    collection = Collection.query.get_or_404(collection_id)
    
    if request.method == 'POST':
        from sqlalchemy.exc import IntegrityError
        
        collection.name = request.form.get('name')
        new_slug = (request.form.get('slug') or '').strip()
        if new_slug:
            existing = Collection.query.filter_by(slug=new_slug).first()
            if existing and existing.id != collection.id:
                flash(f'URL slug "{new_slug}" is already used by another collection. Choose a different slug.', 'error')
                return redirect(url_for('admin.edit_collection', collection_id=collection.id))
            collection.slug = new_slug
        collection.description = request.form.get('description')
        collection.is_active = request.form.get('is_active') == 'on'
        collection.pickup_address = request.form.get('pickup_address')
        collection.pickup_instructions = request.form.get('pickup_instructions')
        collection.shipping_enabled = request.form.get('shipping_enabled') == 'on'
        collection.tax_rate = float(request.form.get('tax_rate') or 0)
        
        # Organizer's choices - restrict what team can order
        collection.restrict_options = request.form.get('restrict_options') == 'on'
        collection.allow_custom_upload = True  # Team can always upload their own designs
        allowed_colors = request.form.getlist('allowed_colors')
        collection.allowed_colors = json.dumps(allowed_colors) if allowed_colors else None
        allowed_placements = request.form.getlist('allowed_placements')
        collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None
        allowed_design_ids = list(request.form.getlist('allowed_designs'))
        upload_count = 0
        # Process uploaded design files
        for f in request.files.getlist('design_uploads'):
            if f and f.filename:
                design = _save_uploaded_design(f, current_user.id)
                if design:
                    allowed_design_ids.append(str(design.id))
                    upload_count += 1
        collection.allowed_design_ids = json.dumps([int(x) for x in allowed_design_ids]) if allowed_design_ids else None
        collection.back_design_font = request.form.get('back_design_font') or None
        
        # Update password if provided
        password = request.form.get('password')
        if password:
            collection.set_password(password)
        elif request.form.get('remove_password') == 'on':
            collection.is_password_protected = False
            collection.password_hash = None
        
        # Update deadline
        deadline_str = request.form.get('order_deadline')
        if deadline_str:
            collection.order_deadline = datetime.fromisoformat(deadline_str)
        else:
            collection.order_deadline = None
        
        # Update products
        collection.products = []
        product_ids = request.form.getlist('products')
        for product_id in product_ids:
            product = Product.query.get(int(product_id))
            if product:
                collection.products.append(product)
        
        try:
            db.session.commit()
            msg = 'Collection updated successfully'
            if upload_count:
                msg += f' with {upload_count} new design(s) uploaded'
            flash(msg + '.', 'success')
            return redirect(url_for('admin.collections'))
        except IntegrityError:
            db.session.rollback()
            flash('A collection with that URL slug already exists. Choose a different slug.', 'error')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))
    
    products = Product.query.filter_by(is_active=True).order_by(Product.style_number).all()
    gallery_designs = Design.query.filter_by(is_gallery=True).order_by(Design.uploaded_at.desc()).all()
    # All unique colors from products in this collection
    collection_color_names = set()
    for p in collection.products:
        for v in ProductColorVariant.query.filter_by(product_id=p.id).all():
            collection_color_names.add(v.color_name)
    collection_color_names = sorted(collection_color_names)
    allowed_colors_list = json.loads(collection.allowed_colors) if collection.allowed_colors else []
    allowed_design_ids_list = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    allowed_placements_list = json.loads(collection.allowed_placements) if collection.allowed_placements else ['center_chest', 'left_chest', 'right_chest', 'center_back']
    back_design_fonts = [
        ('Bebas Neue', 'Bebas Neue — Classic jersey'),
        ('Oswald', 'Oswald — Bold athletic'),
        ('Anton', 'Anton — Strong block'),
        ('Teko', 'Teko — College jersey'),
    ]
    
    return render_template('admin/edit_collection.html', 
                         collection=collection,
                         products=products,
                         gallery_designs=gallery_designs,
                         collection_colors=collection_color_names,
                         allowed_colors_list=allowed_colors_list,
                         allowed_design_ids_list=allowed_design_ids_list,
                         allowed_placements_list=allowed_placements_list,
                         back_design_fonts=back_design_fonts)


@admin_bp.route('/collections/<int:collection_id>/delete', methods=['POST'])
@admin_required
def delete_collection(collection_id):
    """Delete a collection"""
    collection = Collection.query.get_or_404(collection_id)
    db.session.delete(collection)
    db.session.commit()
    flash('Collection deleted', 'success')
    return redirect(url_for('admin.collections'))


# ===== PRODUCTION CENTER =====

@admin_bp.route('/production/master')
@admin_required
def production_master():
    """Master copy: all blanks + designs from new/paid orders. Order everything at once, then move to production."""
    from utils.print_sizes import get_print_width_for_size
    
    status_filter = request.args.getlist('status') or ['new', 'paid']
    collection_id = request.args.get('collection')
    
    query = Order.query.filter(Order.status.in_(status_filter))
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    
    orders = query.order_by(Order.created_at).all()
    
    # Blank apparel totals
    apparel_totals = {}
    for order in orders:
        for item in order.items:
            key = (item.style_number, item.product_name, item.color, item.size)
            if key not in apparel_totals:
                apparel_totals[key] = {
                    'style_number': item.style_number,
                    'product_name': item.product_name,
                    'color': item.color,
                    'size': item.size,
                    'quantity': 0
                }
            apparel_totals[key]['quantity'] += item.quantity
    
    apparel_list = sorted(apparel_totals.values(), key=lambda x: (x['style_number'], x['color'], x['size']))
    
    # Design/logo totals (grouped by design, placement, print size)
    # Always use get_print_width_for_size so youth gets correct 7.5" etc.
    design_groups = {}
    for order in orders:
        for item in order.items:
            if not item.design_id:
                continue
            pw = get_print_width_for_size(item.size, item.product) or item.print_width
            ph = item.print_height or pw
            key = (item.design_id, item.placement or '', pw, ph)
            if key not in design_groups:
                design_groups[key] = {
                    'design': item.design,
                    'placement': item.placement or '-',
                    'print_width': pw,
                    'print_height': ph,
                    'quantity': 0
                }
            design_groups[key]['quantity'] += item.quantity
    
    design_list = sorted(design_groups.values(), key=lambda x: (getattr(x['design'], 'filename', '') or '', x['placement']))
    
    collections = Collection.query.all()
    
    return render_template('admin/production_master.html',
                         orders=orders,
                         apparel_list=apparel_list,
                         design_list=design_list,
                         collections=collections,
                         selected_status=status_filter,
                         selected_collection=collection_id)


@admin_bp.route('/production/master/move-to-production', methods=['POST'])
@admin_required
def production_master_move():
    """Bulk move all new/paid orders to in_production"""
    status_filter = request.form.getlist('status') or ['new', 'paid']
    collection_id = request.form.get('collection')
    
    query = Order.query.filter(Order.status.in_(status_filter))
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    
    orders = query.all()
    count = 0
    for order in orders:
        order.status = 'in_production'
        order.production_stage = 'ready_to_press'
        count += 1
    
    db.session.commit()
    flash(f'Moved {count} order(s) to In Production', 'success')
    return redirect(url_for('admin.production_master'))


@admin_bp.route('/production')
@admin_required
def production():
    """Production center dashboard"""
    # Get orders in production or ready for production
    orders = Order.query.filter(
        Order.status.in_(['paid', 'in_production'])
    ).order_by(Order.created_at).all()
    
    return render_template('admin/production.html', orders=orders)


@admin_bp.route('/production/blank-apparel-list')
@admin_required
def blank_apparel_list():
    """Generate blank apparel purchase order list"""
    collection_id = request.args.get('collection')
    status_filter = request.args.getlist('status') or ['paid', 'in_production']
    
    query = Order.query.filter(Order.status.in_(status_filter))
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    
    orders = query.all()
    
    # Aggregate by style/color/size
    apparel_totals = {}
    
    for order in orders:
        for item in order.items:
            key = (item.style_number, item.product_name, item.color, item.size)
            if key not in apparel_totals:
                apparel_totals[key] = {
                    'style_number': item.style_number,
                    'product_name': item.product_name,
                    'color': item.color,
                    'size': item.size,
                    'quantity': 0
                }
            apparel_totals[key]['quantity'] += item.quantity
    
    # Sort by style, color, size
    apparel_list = sorted(apparel_totals.values(), 
                         key=lambda x: (x['style_number'], x['color'], x['size']))
    
    # Export as CSV if requested
    if request.args.get('format') == 'csv':
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=['style_number', 'product_name', 'color', 'size', 'quantity'])
        writer.writeheader()
        writer.writerows(apparel_list)
        
        response = BytesIO(output.getvalue().encode('utf-8'))
        return send_file(
            response,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'blank_apparel_list_{datetime.now().strftime("%Y%m%d")}.csv'
        )
    
    collections = Collection.query.all()
    return render_template('admin/blank_apparel_list.html',
                         apparel_list=apparel_list,
                         collections=collections)


@admin_bp.route('/orders/print-labels')
@admin_required
def print_labels():
    """Generate printable order labels for sticker paper (3 columns × 10 rows = 30 per sheet)"""
    collection_id = request.args.get('collection')
    status_filter = request.args.getlist('status') or ['paid', 'in_production']
    
    query = Order.query.filter(Order.status.in_(status_filter))
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    
    orders = query.order_by(Order.created_at).all()
    collections = Collection.query.all()
    
    return render_template('admin/print_labels.html',
                         orders=orders,
                         collections=collections,
                         selected_status=status_filter,
                         selected_collection=collection_id)


@admin_bp.route('/production/bulk-sheet')
@admin_required
def production_bulk_sheet():
    """Bulk production sheet - ONLY orders marked 'in_production'. Drops off when marked ready/shipped/completed."""
    from utils.print_sizes import get_print_width_for_size
    
    orders = Order.query.filter_by(status='in_production').order_by(Order.created_at).all()
    
    # Group by design + placement, aggregate by (size, print_width) so youth vs adult are separate
    groups = {}
    for order in orders:
        for item in order.items:
            if not item.design_id:
                continue
            key = (item.design_id, item.placement or '')
            if key not in groups:
                groups[key] = {
                    'design': item.design,
                    'placement': item.placement or '-',
                    'size_qty': {},  # (size, print_width) -> qty
                    'items': [],
                    'total_qty': 0
                }
            size = item.size or 'One Size'
            pw = get_print_width_for_size(size, item.product) or item.print_width
            size_key = (size, pw)
            groups[key]['size_qty'][size_key] = groups[key]['size_qty'].get(size_key, 0) + item.quantity
            groups[key]['items'].append(item)
            groups[key]['total_qty'] += item.quantity
    
    bulk_list = list(groups.values())
    
    return render_template('admin/production_bulk_sheet.html',
                         bulk_list=bulk_list,
                         get_print_width=get_print_width_for_size)


@admin_bp.route('/production/dtf-batch-sheets')
@admin_required
def dtf_batch_sheets():
    """Generate DTF transfer batch sheets"""
    from utils.print_sizes import get_print_width_for_size
    collection_id = request.args.get('collection')
    status_filter = request.args.getlist('status') or ['paid', 'in_production']
    
    query = Order.query.filter(Order.status.in_(status_filter))
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    
    orders = query.all()
    
    # Group by design + placement + size
    batch_groups = {}
    
    for order in orders:
        for item in order.items:
            if not item.design_id:
                continue
            pw = get_print_width_for_size(item.size, item.product) or item.print_width
            ph = item.print_height or pw
            key = (item.design_id, item.placement, pw, ph)
            if key not in batch_groups:
                batch_groups[key] = {
                    'design': item.design,
                    'placement': item.placement,
                    'print_width': pw,
                    'print_height': ph,
                    'quantity': 0,
                    'items': []
                }
            batch_groups[key]['quantity'] += item.quantity
            batch_groups[key]['items'].append(item)
    
    batch_list = list(batch_groups.values())
    
    collections = Collection.query.all()
    return render_template('admin/dtf_batch_sheets.html',
                         batch_list=batch_list,
                         collections=collections)


# ===== DESIGNS =====

@admin_bp.route('/designs')
@admin_required
def designs():
    """Artwork library - customer uploads"""
    designs = Design.query.filter_by(is_gallery=False).order_by(Design.uploaded_at.desc()).all()
    return render_template('admin/designs.html', designs=designs)


# ===== DESIGN GALLERY (for customers to use) =====

@admin_bp.route('/design-gallery')
@admin_required
def design_gallery():
    """Upload and manage designs for customer gallery"""
    gallery_designs = Design.query.filter_by(is_gallery=True).order_by(Design.uploaded_at.desc()).all()
    return render_template('admin/design_gallery.html', designs=gallery_designs)


@admin_bp.route('/design-gallery/upload', methods=['POST'])
@admin_required
def design_gallery_upload():
    """Upload a design to the customer gallery"""
    if 'file' not in request.files:
        flash('No file provided', 'error')
        return redirect(url_for('admin.design_gallery'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('admin.design_gallery'))
    
    from werkzeug.utils import secure_filename
    import time
    filename = secure_filename(file.filename)
    if '.' not in filename:
        flash('File must have an extension (PNG, JPG, etc.)', 'error')
        return redirect(url_for('admin.design_gallery'))
    
    name, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in ['.png', '.jpg', '.jpeg', '.webp']:
        flash('Use PNG, JPG, or WEBP format', 'error')
        return redirect(url_for('admin.design_gallery'))
    
    upload_dir = Path('static/uploads/designs')
    upload_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    unique_name = f"gallery_{name}_{timestamp}{ext}"
    filepath = upload_dir / unique_name
    file.save(str(filepath))
    
    title = request.form.get('title') or name.replace('_', ' ').title()
    folder = request.form.get('folder') or 'custom_orders'
    sku = request.form.get('sku')
    
    design = Design(
        filename=unique_name,
        original_filename=file.filename,
        file_path=f"uploads/designs/{unique_name}",
        is_gallery=True,
        title=title,
        folder=folder,
        sku=sku,
        uploaded_by_user_id=current_user.id
    )
    try:
        from PIL import Image
        img = Image.open(filepath)
        design.width, design.height = img.size
        design.file_size = filepath.stat().st_size
    except Exception:
        pass
    
    db.session.add(design)
    db.session.commit()
    flash(f'Design "{title}" added to gallery!', 'success')
    return redirect(url_for('admin.design_gallery'))


@admin_bp.route('/design-gallery/<int:design_id>/remove', methods=['POST'])
@admin_required
def design_gallery_remove(design_id):
    """Remove design from gallery (does not delete file)"""
    design = Design.query.get_or_404(design_id)
    if design.is_gallery:
        design.is_gallery = False
        db.session.commit()
        flash('Design removed from gallery', 'success')
    return redirect(url_for('admin.design_gallery'))


@admin_bp.route('/design-gallery/<int:design_id>/delete', methods=['POST'])
@admin_required
def design_gallery_delete(design_id):
    """Permanently delete a design and its file (admin only)"""
    design = Design.query.get_or_404(design_id)
    _delete_design_file(design)
    db.session.delete(design)
    db.session.commit()
    flash('Design deleted permanently', 'success')
    return redirect(url_for('admin.design_gallery'))


# ===== CUSTOM DESIGN REQUESTS (Have Us Recreate) =====

@admin_bp.route('/custom-design-requests')
@admin_required
def custom_design_requests():
    """List all custom design requests from customers"""
    status_filter = request.args.get('status', 'pending')
    query = CustomDesignRequest.query.order_by(CustomDesignRequest.created_at.desc())
    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)
    requests = query.all()
    return render_template('admin/custom_design_requests.html', requests=requests, status_filter=status_filter)


@admin_bp.route('/custom-design-requests/<int:request_id>', methods=['GET', 'POST'])
@admin_required
def custom_design_request_detail(request_id):
    """View request and upload completed design for customer"""
    req = CustomDesignRequest.query.get_or_404(request_id)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'upload_design':
            file = request.files.get('design_file')
            title = request.form.get('title', '').strip() or (req.description[:50] + '...' if len(req.description or '') > 50 else req.description)
            design_fee = request.form.get('design_fee', '0')
            if file and file.filename:
                design = _save_design_for_user(file, req.user_id, title=title or None, design_fee=design_fee)
                if design:
                    req.created_design_id = design.id
                    req.status = 'completed'
                    req.design_fee = float(design_fee or 0)
                    req.admin_notes = (req.admin_notes or '') + f"\n[Design uploaded: {design.filename}, fee: ${design.design_fee:.0f}]"
                    db.session.commit()
                    flash(f'Design uploaded to {req.user.full_name}\'s profile! They can now order any style/color.', 'success')
                else:
                    flash('Invalid file. Use PNG, JPG, or WEBP.', 'error')
            else:
                flash('Please select a design file to upload.', 'error')
        elif action == 'add_notes':
            req.admin_notes = request.form.get('admin_notes', '')
            db.session.commit()
            flash('Notes saved', 'success')
        elif action == 'decline':
            req.status = 'declined'
            req.admin_notes = (req.admin_notes or '') + '\n' + (request.form.get('decline_reason') or 'Declined')
            db.session.commit()
            flash('Request declined', 'info')
        return redirect(url_for('admin.custom_design_request_detail', request_id=request_id))
    
    return render_template('admin/custom_design_request_detail.html', req=req)


@admin_bp.route('/designs/<int:design_id>/delete', methods=['POST'])
@admin_required
def design_delete(design_id):
    """Permanently delete a design (admin only) - used for Designs Library"""
    design = Design.query.get_or_404(design_id)
    _delete_design_file(design)
    db.session.delete(design)
    db.session.commit()
    flash('Design deleted permanently', 'success')
    return redirect(url_for('admin.designs'))


def _delete_design_file(design):
    """Remove design file from disk if it exists"""
    if design and design.file_path:
        full_path = Path('static') / design.file_path
        if full_path.exists():
            try:
                full_path.unlink()
            except OSError:
                pass


# ===== OPERATIONS: INVENTORY =====

@admin_bp.route('/operations/inventory')
@admin_required
def inventory():
    """Inventory management - apparel, transfers, supplies"""
    apparel = ApparelInventory.query.order_by(ApparelInventory.brand, ApparelInventory.color).all()
    transfers = TransferInventory.query.order_by(TransferInventory.design_name).all()
    supplies = Supply.query.order_by(Supply.category, Supply.name).all()
    vendors = Vendor.query.order_by(Vendor.name).all()
    return render_template('admin/operations/inventory.html',
                         apparel=apparel, transfers=transfers, supplies=supplies, vendors=vendors)


@admin_bp.route('/operations/inventory/apparel/add', methods=['POST'])
@admin_required
def add_apparel_inventory():
    inv = ApparelInventory(brand=request.form.get('brand'), color=request.form.get('color'),
                           size=request.form.get('size'), quantity=int(request.form.get('quantity') or 0),
                           cost_per_unit=float(request.form.get('cost_per_unit') or 0) or None,
                           reorder_threshold=int(request.form.get('reorder_threshold') or 5))
    db.session.add(inv)
    db.session.commit()
    flash('Apparel added', 'success')
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory/apparel/<int:id>/update', methods=['POST'])
@admin_required
def update_apparel_inventory(id):
    inv = ApparelInventory.query.get_or_404(id)
    inv.quantity = int(request.form.get('quantity') or 0)
    inv.cost_per_unit = float(request.form.get('cost_per_unit') or 0) or None
    inv.reorder_threshold = int(request.form.get('reorder_threshold') or 5)
    db.session.commit()
    flash('Apparel updated', 'success')
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory/supply/add', methods=['POST'])
@admin_required
def add_supply():
    s = Supply(category=request.form.get('category'), name=request.form.get('name'),
               quantity=int(request.form.get('quantity') or 0), unit=request.form.get('unit') or 'ea',
               cost_per_unit=float(request.form.get('cost_per_unit') or 0) or None,
               reorder_threshold=int(request.form.get('reorder_threshold') or 0))
    db.session.add(s)
    db.session.commit()
    flash('Supply added', 'success')
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory/supply/<int:id>/update', methods=['POST'])
@admin_required
def update_supply(id):
    s = Supply.query.get_or_404(id)
    s.quantity = int(request.form.get('quantity') or 0)
    s.cost_per_unit = float(request.form.get('cost_per_unit') or 0) or None
    s.reorder_threshold = int(request.form.get('reorder_threshold') or 0)
    db.session.commit()
    flash('Supply updated', 'success')
    return redirect(url_for('admin.inventory'))


@admin_bp.route('/operations/inventory/transfer/add', methods=['POST'])
@admin_required
def add_transfer_inventory():
    t = TransferInventory(design_name=request.form.get('design_name'), size=request.form.get('size'),
                          quantity=int(request.form.get('quantity') or 0),
                          cost_per_sheet=float(request.form.get('cost_per_sheet') or 0) or None,
                          vendor_id=int(request.form.get('vendor_id')) if request.form.get('vendor_id') else None,
                          delivery_time=request.form.get('delivery_time'))
    db.session.add(t)
    db.session.commit()
    flash('Transfer added', 'success')
    return redirect(url_for('admin.inventory'))


# ===== OPERATIONS: VENDORS =====

@admin_bp.route('/operations/vendors')
@admin_required
def vendors():
    vendors_list = Vendor.query.order_by(Vendor.name).all()
    return render_template('admin/operations/vendors.html', vendors=vendors_list)


@admin_bp.route('/operations/vendors/add', methods=['GET', 'POST'])
@admin_required
def add_vendor():
    if request.method == 'POST':
        v = Vendor(name=request.form.get('name'), contact_name=request.form.get('contact_name'),
                   contact_email=request.form.get('contact_email'), contact_phone=request.form.get('contact_phone'),
                   website=request.form.get('website'), website_login=request.form.get('website_login'),
                   lead_time_days=int(request.form.get('lead_time_days') or 0) or None,
                   moq=int(request.form.get('moq') or 0) or None,
                   pricing_tier=request.form.get('pricing_tier'),
                   quality_rating=int(request.form.get('quality_rating') or 0) or None,
                   notes=request.form.get('notes'))
        db.session.add(v)
        db.session.commit()
        flash('Vendor added', 'success')
        return redirect(url_for('admin.vendors'))
    return render_template('admin/operations/vendor_form.html', vendor=None)


@admin_bp.route('/operations/vendors/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_vendor(id):
    v = Vendor.query.get_or_404(id)
    if request.method == 'POST':
        v.name = request.form.get('name')
        v.contact_name = request.form.get('contact_name')
        v.contact_email = request.form.get('contact_email')
        v.contact_phone = request.form.get('contact_phone')
        v.website = request.form.get('website')
        v.website_login = request.form.get('website_login')
        v.lead_time_days = int(request.form.get('lead_time_days') or 0) or None
        v.moq = int(request.form.get('moq') or 0) or None
        v.pricing_tier = request.form.get('pricing_tier')
        v.quality_rating = int(request.form.get('quality_rating') or 0) or None
        v.notes = request.form.get('notes')
        db.session.commit()
        flash('Vendor updated', 'success')
        return redirect(url_for('admin.vendors'))
    return render_template('admin/operations/vendor_form.html', vendor=v)


# ===== OPERATIONS: PRODUCTION WORKFLOW (KANBAN) =====

@admin_bp.route('/operations/workflow')
@admin_required
def production_workflow():
    """5-stage Kanban: Order Received → Waiting Supplies → Ready to Press → Pressed → Packaged Ready"""
    stages = [
        ('order_received', 'Order Received', 'All new/paid orders'),
        ('waiting_supplies', 'Waiting on Supplies', 'Awaiting blanks or transfers'),
        ('ready_to_press', 'Ready to Press', 'Supplies in, ready to heat'),
        ('pressed', 'Pressed', 'Print applied'),
        ('packaged_ready', 'Packaged & Ready', 'Ready for pickup/ship')
    ]
    orders_by_stage = {}
    # order_received: new/paid with no stage or order_received
    orders_by_stage['order_received'] = Order.query.filter(
        Order.status.in_(['new', 'paid']),
        or_(Order.production_stage == None, Order.production_stage == '', Order.production_stage == 'order_received')
    ).order_by(Order.created_at).all()
    # waiting_supplies, ready_to_press, pressed
    for sid in ['waiting_supplies', 'ready_to_press', 'pressed']:
        orders_by_stage[sid] = Order.query.filter(
            Order.status.in_(['new', 'paid', 'in_production']),
            Order.production_stage == sid
        ).order_by(Order.created_at).all()
    # packaged_ready: only "ready" (awaiting pickup) — shipped/completed are in All Completed
    orders_by_stage['packaged_ready'] = Order.query.filter(
        Order.status == 'ready'
    ).order_by(Order.created_at).all()
    return render_template('admin/operations/workflow.html', stages=stages, orders_by_stage=orders_by_stage)


@admin_bp.route('/orders/<int:order_id>/update-stage', methods=['POST'])
@admin_required
def update_order_stage(order_id):
    order = Order.query.get_or_404(order_id)
    stage = request.form.get('stage')
    order.production_stage = stage
    if stage == 'packaged_ready':
        order.status = 'ready'
    elif stage == 'ready_to_press':
        order.status = 'in_production'
    db.session.commit()
    flash('Stage updated', 'success')
    return redirect(request.referrer or url_for('admin.production_workflow'))


# ===== OPERATIONS: FINANCIAL =====

@admin_bp.route('/operations/financial')
@admin_required
def financial():
    orders = Order.query.filter(Order.payment_status == 'paid').all()
    total_revenue = sum(o.total for o in orders if not getattr(o, 'is_refunded', False))
    total_profit = sum(o.profit or 0 for o in orders if o.profit)
    entries = FinancialEntry.query.order_by(FinancialEntry.entry_date.desc()).limit(100).all()
    return render_template('admin/operations/financial.html',
                         total_revenue=total_revenue, total_profit=total_profit,
                         entries=entries)


@admin_bp.route('/operations/financial/entry/add', methods=['POST'])
@admin_required
def add_financial_entry():
    e = FinancialEntry(category=request.form.get('category'), amount=float(request.form.get('amount')),
                       description=request.form.get('description'))
    db.session.add(e)
    db.session.commit()
    flash('Entry added', 'success')
    return redirect(url_for('admin.financial'))


# ===== OPERATIONS: EQUIPMENT =====

# ===== OPERATIONS: GROWTH DASHBOARD =====

@admin_bp.route('/operations/growth')
@admin_required
def growth():
    metrics = GrowthMetric.query.order_by(GrowthMetric.week_start.desc()).limit(12).all()
    return render_template('admin/operations/growth.html', metrics=metrics)


@admin_bp.route('/operations/growth/sync', methods=['POST'])
@admin_required
def sync_growth_metrics():
    """Auto-sync weekly metrics from orders & collections"""
    try:
        from services.growth_sync import sync_all_recent_weeks
        results = sync_all_recent_weeks(weeks=4)
        updated = sum(1 for _, a in results if a == 'updated')
        created = sum(1 for _, a in results if a == 'created')
        flash(f'Auto-synced: {created} new, {updated} updated (units, revenue, events, wholesale from your data)', 'success')
    except Exception as e:
        flash(f'Sync failed: {str(e)}', 'error')
    return redirect(url_for('admin.growth'))


@admin_bp.route('/operations/growth/add', methods=['POST'])
@admin_required
def add_growth_metric():
    m = GrowthMetric(week_start=datetime.fromisoformat(request.form.get('week_start')),
                     units_sold=int(request.form.get('units_sold') or 0),
                     revenue=float(request.form.get('revenue') or 0),
                     website_traffic=int(request.form.get('website_traffic') or 0),
                     events_booked=int(request.form.get('events_booked') or 0),
                     wholesale_inquiries=int(request.form.get('wholesale_inquiries') or 0),
                     social_reach=int(request.form.get('social_reach') or 0),
                     notes=request.form.get('notes'))
    db.session.add(m)
    db.session.commit()
    flash('Weekly metric added', 'success')
    return redirect(url_for('admin.growth'))


@admin_bp.route('/operations/growth/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_growth_metric(id):
    m = GrowthMetric.query.get_or_404(id)
    if request.method == 'POST':
        m.week_start = datetime.fromisoformat(request.form.get('week_start'))
        m.units_sold = int(request.form.get('units_sold') or 0)
        m.revenue = float(request.form.get('revenue') or 0)
        m.website_traffic = int(request.form.get('website_traffic') or 0)
        m.events_booked = int(request.form.get('events_booked') or 0)
        m.wholesale_inquiries = int(request.form.get('wholesale_inquiries') or 0)
        m.social_reach = int(request.form.get('social_reach') or 0)
        m.notes = request.form.get('notes') or None
        db.session.commit()
        flash('Weekly metric updated', 'success')
        return redirect(url_for('admin.growth'))
    return render_template('admin/operations/growth_edit.html', metric=m)


# ===== OPERATIONS: PACKAGING SOP =====

@admin_bp.route('/operations/packaging-sop')
@admin_required
def packaging_sop():
    """Packaging & Fulfillment SOP checklist - printable"""
    return render_template('admin/operations/packaging_sop.html')


# ===== OPERATIONS: CUSTOMERS & MARKETING =====

@admin_bp.route('/operations/customers')
@admin_required
def customers():
    """Customer & marketing tracker - repeat customers, collections (school/team/event)"""
    from sqlalchemy import func
    # Repeat customers: users with 2+ orders
    repeat_query = db.session.query(User, func.count(Order.id).label('order_count')).join(
        Order, User.id == Order.user_id
    ).group_by(User.id).having(func.count(Order.id) >= 2).all()
    repeat_customers = [{'user': u, 'order_count': c} for u, c in repeat_query]
    # Collections (school/team/event)
    collections = Collection.query.filter_by(is_active=True).order_by(Collection.name).all()
    return render_template('admin/operations/customers.html',
                         repeat_customers=repeat_customers,
                         collections=collections)
