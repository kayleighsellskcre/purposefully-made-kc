from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Order, Address, Design
from datetime import datetime

account_bp = Blueprint('account', __name__, url_prefix='/account')

@account_bp.route('/')
@login_required
def index():
    """Account dashboard"""
    return redirect(url_for('account.orders'))


@account_bp.route('/orders')
@login_required
def orders():
    """View order history"""
    page = request.args.get('page', 1, type=int)
    orders = current_user.orders.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )
    return render_template('account/orders.html', orders=orders)


@account_bp.route('/orders/<order_number>')
@login_required
def order_detail(order_number):
    """View order details"""
    order = Order.query.filter_by(
        order_number=order_number,
        user_id=current_user.id
    ).first_or_404()
    return render_template('account/order_detail.html', order=order)


@account_bp.route('/reorder/<order_number>', methods=['POST'])
@login_required
def reorder(order_number):
    """Reorder - add all items from previous order to cart"""
    order = Order.query.filter_by(
        order_number=order_number,
        user_id=current_user.id
    ).first_or_404()
    
    from flask import session
    
    cart = session.get('cart', [])
    
    # Add each order item to cart
    for item in order.items:
        cart_item = {
            'product_id': item.product_id,
            'size': item.size,
            'color': item.color,
            'quantity': item.quantity,
            'unit_price': item.product.base_price,  # Use current price
            'design_id': item.design_id,
            'placement': item.placement,
            'print_width': item.print_width,
            'print_height': item.print_height,
            'position_x': item.position_x,
            'position_y': item.position_y,
            'rotation': item.rotation,
            'proof_image': item.proof_image
        }
        cart.append(cart_item)
    
    session['cart'] = cart
    session['cart_owner_id'] = current_user.id
    session.modified = True
    
    flash(f'Added {len(order.items.all())} items to cart', 'success')
    return redirect(url_for('cart.index'))


@account_bp.route('/addresses')
@login_required
def addresses():
    """Manage shipping addresses"""
    addresses = current_user.addresses.all()
    return render_template('account/addresses.html', addresses=addresses)


@account_bp.route('/addresses/add', methods=['GET', 'POST'])
@login_required
def add_address():
    """Add new address"""
    if request.method == 'POST':
        label = request.form.get('label')
        recipient_name = request.form.get('recipient_name')
        street_address = request.form.get('street_address')
        street_address_2 = request.form.get('street_address_2')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        is_default = request.form.get('is_default') == 'on'
        
        # If setting as default, unset other defaults
        if is_default:
            Address.query.filter_by(user_id=current_user.id, is_default=True).update({'is_default': False})
        
        address = Address(
            user_id=current_user.id,
            label=label,
            recipient_name=recipient_name,
            street_address=street_address,
            street_address_2=street_address_2,
            city=city,
            state=state,
            zip_code=zip_code,
            is_default=is_default
        )
        
        db.session.add(address)
        db.session.commit()
        
        flash('Address added successfully', 'success')
        return redirect(url_for('account.addresses'))
    
    return render_template('account/add_address.html')


@account_bp.route('/addresses/<int:address_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_address(address_id):
    """Edit address"""
    address = Address.query.filter_by(id=address_id, user_id=current_user.id).first_or_404()
    
    if request.method == 'POST':
        address.label = request.form.get('label')
        address.recipient_name = request.form.get('recipient_name')
        address.street_address = request.form.get('street_address')
        address.street_address_2 = request.form.get('street_address_2')
        address.city = request.form.get('city')
        address.state = request.form.get('state')
        address.zip_code = request.form.get('zip_code')
        
        is_default = request.form.get('is_default') == 'on'
        if is_default and not address.is_default:
            # Unset other defaults
            Address.query.filter_by(user_id=current_user.id, is_default=True).update({'is_default': False})
            address.is_default = True
        elif not is_default:
            address.is_default = False
        
        db.session.commit()
        flash('Address updated successfully', 'success')
        return redirect(url_for('account.addresses'))
    
    return render_template('account/edit_address.html', address=address)


@account_bp.route('/addresses/<int:address_id>/delete', methods=['POST'])
@login_required
def delete_address(address_id):
    """Delete address"""
    address = Address.query.filter_by(id=address_id, user_id=current_user.id).first_or_404()
    db.session.delete(address)
    db.session.commit()
    flash('Address deleted', 'success')
    return redirect(url_for('account.addresses'))


@account_bp.route('/designs')
@login_required
def my_designs():
    """My Designs - designs created for this customer (from custom requests) + their uploads"""
    designs = Design.query.filter(
        Design.uploaded_by_user_id == current_user.id,
        Design.is_gallery == False
    ).order_by(Design.uploaded_at.desc()).all()
    return render_template('account/my_designs.html', designs=designs)


@account_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Edit profile"""
    if request.method == 'POST':
        current_user.first_name = request.form.get('first_name')
        current_user.last_name = request.form.get('last_name')
        current_user.phone = request.form.get('phone')
        
        # Change password if provided
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if current_password and new_password:
            if not current_user.check_password(current_password):
                flash('Current password is incorrect', 'error')
                return redirect(url_for('account.profile'))
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'error')
                return redirect(url_for('account.profile'))
            
            if len(new_password) < 8:
                flash('Password must be at least 8 characters long', 'error')
                return redirect(url_for('account.profile'))
            
            current_user.set_password(new_password)
            flash('Password updated successfully', 'success')
        
        db.session.commit()
        flash('Profile updated successfully', 'success')
        return redirect(url_for('account.profile'))
    
    return render_template('account/profile.html')
