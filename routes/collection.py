from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from models import db, Collection, Product, ProductColorVariant
from utils.mockups import get_carousel_colors_for_product
from sqlalchemy.orm import joinedload
import json

collection_bp = Blueprint('collection', __name__, url_prefix='/c')

@collection_bp.route('/<slug>')
def view(slug):
    """View collection landing page - design board of available items"""
    collection = Collection.query.options(
        joinedload(Collection.products).joinedload(Product.color_variants)
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
    
    return render_template('collection/share.html', collection=collection)
