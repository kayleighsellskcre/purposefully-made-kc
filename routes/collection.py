from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import current_user, login_required
from models import db, Collection, Product, ProductColorVariant, Design
from utils.mockups import get_carousel_colors_for_product
from sqlalchemy.orm import joinedload
import json

collection_bp = Blueprint('collection', __name__, url_prefix='/c')

@collection_bp.route('/<slug>')
def view(slug):
    """View collection landing page - design board of available items"""
    collection = Collection.query.options(
        joinedload(Collection.products)
    ).filter_by(slug=slug, is_active=True).first_or_404()
    
    # Check password if protected
    if collection.is_password_protected:
        if not session.get(f'collection_{collection.id}_access'):
            return redirect(url_for('collection.password', slug=slug))
    
    # Set collection in session for checkout
    session['collection_id'] = collection.id
    
    # Get allowed colors when organizer restricted options
    allowed_colors = None
    if collection.restrict_options and collection.allowed_colors:
        allowed_colors = set(json.loads(collection.allowed_colors))
    
    # Get products in this collection with carousel colors (DB + mockup folder)
    all_products = collection.products
    products = []
    unavailable_products = []  # Products that don't have any of the chosen colors
    for product in all_products:
        variants = get_carousel_colors_for_product(product, current_app, allowed_colors=allowed_colors)
        product.carousel_colors = variants
        product.available_sizes_list = json.loads(product.available_sizes) if product.available_sizes else []
        # When colors are restricted: only show products that have at least one matching color
        if allowed_colors:
            if variants:
                products.append(product)
            else:
                unavailable_products.append(product.name)
        else:
            products.append(product)
    
    return render_template('collection/view.html', 
                         collection=collection,
                         products=products,
                         unavailable_products=unavailable_products)


@collection_bp.route('/<slug>/password', methods=['GET', 'POST'])
def password(slug):
    """Password protection for collection"""
    collection = Collection.query.filter_by(slug=slug, is_active=True).first_or_404()
    
    if not collection.is_password_protected:
        return redirect(url_for('collection.view', slug=slug))
    
    if request.method == 'POST':
        password = request.form.get('password')
        
        if collection.check_password(password):
            session[f'collection_{collection.id}_access'] = True
            return redirect(url_for('collection.view', slug=slug))
        else:
            flash('Incorrect password', 'error')
    
    return render_template('collection/password.html', collection=collection)


@collection_bp.route('/<slug>/share')
def share(slug):
    """Collection share page (shows share link and QR code)"""
    collection = Collection.query.filter_by(slug=slug, is_active=True).first_or_404()

    # Check password if protected
    if collection.is_password_protected:
        if not session.get(f'collection_{collection.id}_access'):
            return redirect(url_for('collection.password', slug=slug))

    # Resolve designs for this collection so the share page can show them
    designs = []
    if collection.allowed_design_ids:
        try:
            ids = json.loads(collection.allowed_design_ids)
            if ids:
                designs = Design.query.filter(Design.id.in_(ids)).all()
        except Exception:
            designs = []

    # Determine if the current user can manage (delete) designs
    can_manage = (
        current_user.is_authenticated and (
            getattr(current_user, 'is_admin', False) or
            current_user.id == collection.created_by_user_id
        )
    )

    return render_template('collection/share.html', collection=collection,
                           designs=designs, can_manage=can_manage)


@collection_bp.route('/<slug>/design/<int:design_id>/delete', methods=['POST'])
@login_required
def delete_design(slug, design_id):
    """Remove a design from a group order's allowed list.

    Only the collection creator or an admin may do this.
    """
    collection = Collection.query.filter_by(slug=slug).first_or_404()

    # Permission check
    is_admin = getattr(current_user, 'is_admin', False)
    is_creator = current_user.id == collection.created_by_user_id
    if not (is_admin or is_creator):
        flash('You do not have permission to delete designs from this group order.', 'error')
        return redirect(url_for('collection.share', slug=slug))

    # Remove the design from allowed_design_ids
    try:
        ids = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
        ids = [i for i in ids if i != design_id]
        collection.allowed_design_ids = json.dumps(ids) if ids else None
        db.session.commit()
        flash('Design removed from this group order.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error removing design %s from collection %s: %s', design_id, slug, e)
        flash('Could not remove the design. Please try again.', 'error')

    return redirect(url_for('collection.share', slug=slug))
