from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from models import db, Order, Address, Design, Collection
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
    from utils.group_orders import group_pickup_details, group_pickup_heading
    coll = getattr(order, 'collection', None)
    return render_template(
        'account/order_detail.html',
        order=order,
        pickup_heading=group_pickup_heading(coll),
        pickup_details=group_pickup_details(coll),
    )


@account_bp.route('/reorder/<order_number>', methods=['POST'])
@login_required
def reorder(order_number):
    """Order again: put the same items, sizes and artwork back in the cart."""
    from utils.cart_store import get_cart, save_cart
    from utils.reorder import add_order_to_cart

    order = Order.query.filter_by(
        order_number=order_number,
        user_id=current_user.id
    ).first_or_404()

    cart = list(get_cart())
    added, skipped, note = add_order_to_cart(order, cart)
    if added:
        save_cart(cart)
        flash(f'Added {added} item{"s" if added != 1 else ""} from order {order.order_number} to your cart.', 'success')
    else:
        flash('None of the items from that order can be ordered again right now.', 'error')
    if note:
        flash(note, 'info')
    for name, reason in skipped:
        flash(f'{name} was left out because {reason}.', 'info')
    if not added:
        return redirect(url_for('account.order_detail', order_number=order.order_number))
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
    search_query = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int)
    try:
        query = Design.query.filter(
            Design.uploaded_by_user_id == current_user.id,
            Design.is_gallery == False
        )
        if search_query:
            # title is the friendly name when set; original_filename covers
            # designs that never got one (the template falls back to a
            # cleaned-up version of it too, so search matches what's shown).
            needle = f'%{search_query}%'
            query = query.filter(
                db.or_(Design.title.ilike(needle), Design.original_filename.ilike(needle))
            )
        designs = query.order_by(Design.uploaded_at.desc()).paginate(
            page=page, per_page=24, error_out=False
        )
        return render_template('account/my_designs.html', designs=designs, search_query=search_query)
    except Exception as e:
        # Defensive: a transient DB error should never look like an upload
        # failure. Log full detail for troubleshooting and render an empty list.
        current_app.logger.exception('Error loading My Designs for user %s: %s', current_user.id, e)
        return render_template('account/my_designs.html', designs=None, search_query=search_query)


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


@account_bp.route('/group-orders/delete', methods=['POST'])
@login_required
def delete_group_orders():
    """Delete several of your own group orders at once. Anything with orders or sign-ups is turned off and kept."""
    from utils.group_delete import remove_stores, summary
    ids = [int(i) for i in request.form.getlist('store_id') if i.isdigit()]
    owned = Collection.created_by_user_id == current_user.id
    if getattr(current_user, 'is_admin', False):
        owned = owned | Collection.created_by_user_id.is_(None)
    stores = Collection.query.filter(Collection.id.in_(ids), owned).all() if ids else []
    deleted, kept = remove_stores(stores)
    flash(summary(deleted, kept, 'group order'), 'success' if deleted or kept else 'info')
    return redirect(url_for('account.my_group_orders'))


@account_bp.route('/group-orders')
@login_required
def my_group_orders():
    """View group orders created by this user"""
    from utils.group_orders import is_deadline_passed, is_not_yet_open
    owned = Collection.created_by_user_id == current_user.id
    if getattr(current_user, 'is_admin', False):
        # Stores made from Admin -> Collections never recorded a creator
        # before this fix, so they belonged to no one's "My Group Orders" -
        # not even the admin who runs the shop. Since there is only ever
        # one admin account, any creator-less store is effectively hers.
        # (`.in_([current_user.id, None])` was tried first, but SQL's IN
        # never matches NULL even when None is literally in the list.)
        owned = owned | Collection.created_by_user_id.is_(None)
    collections = (
        Collection.query
        .filter(owned)
        .order_by(Collection.created_at.desc())
        .all()
    )
    from models import OrgSection
    from utils import districts as DS
    sections = {sec.collection_id: sec.organization for sec in
                OrgSection.query.filter(OrgSection.collection_id.in_([c.id for c in collections] or [0])).all()
                if sec.organization is not None}
    groups, by_org, standalone = [], {}, []
    for c in collections:
        c.deadline_passed = is_deadline_passed(c)
        c.not_yet_open = is_not_yet_open(c)
        org = sections.get(c.id)
        c.share_kit = DS.share_info(c, org if org is not None and org.district_id else None)
        if org is None:
            standalone.append(c)
            continue
        group = by_org.get(org.id)
        if group is None:
            group = by_org[org.id] = {'title': org.name, 'kind': 'School' if org.district_id else 'Organization', 'stores': []}
            groups.append(group)
        group['stores'].append(c)
    return render_template('account/my_group_orders.html', collections=collections, groups=groups,
                           standalone=standalone)
