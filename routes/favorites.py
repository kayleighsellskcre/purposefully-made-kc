from flask import Blueprint, render_template, request, jsonify, session
from flask_login import current_user
from models import db, Favorite, Product
from utils.mockups import get_carousel_colors_for_product, get_first_shop_image_url
from flask import current_app

favorites_bp = Blueprint('favorites', __name__)

@favorites_bp.route('/favorites')
def index():
    """View all favorites"""
    favorites = []
    
    if current_user.is_authenticated:
        # Get favorites from database for logged-in users
        user_favorites = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
        for fav in user_favorites:
            if fav.product and fav.product.is_active:
                product = fav.product
                product.carousel_colors = get_carousel_colors_for_product(product, current_app)
                product.fallback_image_url = get_first_shop_image_url(product, current_app)
                favorites.append({
                    'id': fav.id,
                    'product': product,
                    'color_name': fav.color_name
                })
    else:
        # Get favorites from session for guests
        session_favorites = session.get('favorites', [])
        for fav_data in session_favorites:
            product = Product.query.get(fav_data.get('product_id'))
            if product and product.is_active:
                product.carousel_colors = get_carousel_colors_for_product(product, current_app)
                product.fallback_image_url = get_first_shop_image_url(product, current_app)
                favorites.append({
                    'id': None,
                    'product': product,
                    'color_name': fav_data.get('color_name')
                })
    
    return render_template('shop/favorites.html', favorites=favorites)


@favorites_bp.route('/favorites/add', methods=['POST'])
def add_favorite():
    """Add product to favorites"""
    data = request.get_json()
    product_id = data.get('product_id')
    color_name = data.get('color_name')
    
    if not product_id:
        return jsonify({'success': False, 'error': 'Product ID required'}), 400
    
    # Verify product exists
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    if current_user.is_authenticated:
        # Check if already favorited
        existing = Favorite.query.filter_by(
            user_id=current_user.id,
            product_id=product_id,
            color_name=color_name
        ).first()
        
        if existing:
            return jsonify({'success': True, 'message': 'Already in favorites'})
        
        # Add to database
        favorite = Favorite(
            user_id=current_user.id,
            product_id=product_id,
            color_name=color_name
        )
        db.session.add(favorite)
        db.session.commit()
    else:
        # Add to session for guests
        if 'favorites' not in session:
            session['favorites'] = []
        
        # Check if already in session
        session_favorites = session['favorites']
        for fav in session_favorites:
            if fav.get('product_id') == product_id and fav.get('color_name') == color_name:
                return jsonify({'success': True, 'message': 'Already in favorites'})
        
        # Add to session
        session_favorites.append({
            'product_id': product_id,
            'color_name': color_name
        })
        session['favorites'] = session_favorites
        session.modified = True
    
    return jsonify({'success': True, 'message': 'Added to favorites'})


@favorites_bp.route('/favorites/remove', methods=['POST'])
def remove_favorite():
    """Remove product from favorites"""
    data = request.get_json()
    product_id = data.get('product_id')
    color_name = data.get('color_name')
    
    if not product_id:
        return jsonify({'success': False, 'error': 'Product ID required'}), 400
    
    if current_user.is_authenticated:
        # Remove from database
        favorite = Favorite.query.filter_by(
            user_id=current_user.id,
            product_id=product_id,
            color_name=color_name
        ).first()
        
        if favorite:
            db.session.delete(favorite)
            db.session.commit()
    else:
        # Remove from session
        if 'favorites' in session:
            session_favorites = session['favorites']
            session['favorites'] = [
                fav for fav in session_favorites 
                if not (fav.get('product_id') == product_id and fav.get('color_name') == color_name)
            ]
            session.modified = True
    
    return jsonify({'success': True, 'message': 'Removed from favorites'})


@favorites_bp.route('/favorites/check-batch', methods=['POST'])
def check_favorites_batch():
    """Check which of a list of products are favorited.
    Body: {"items": [{"product_id": 1, "color_name": "White"}, ...]}
    Returns: {"favorites": {"1:White": true, ...}}
    """
    data = request.get_json() or {}
    items = data.get('items', [])
    result = {}

    if current_user.is_authenticated:
        if items:
            product_ids = list({item.get('product_id') for item in items})
            user_favs = Favorite.query.filter_by(user_id=current_user.id)\
                .filter(Favorite.product_id.in_(product_ids)).all()
            fav_set = {(f.product_id, f.color_name or '') for f in user_favs}
            for item in items:
                pid = item.get('product_id')
                color = item.get('color_name') or ''
                result[f"{pid}:{color}"] = (pid, color) in fav_set
    else:
        session_favorites = session.get('favorites', [])
        session_set = {(f.get('product_id'), f.get('color_name') or '') for f in session_favorites}
        for item in items:
            pid = item.get('product_id')
            color = item.get('color_name') or ''
            result[f"{pid}:{color}"] = (pid, color) in session_set

    return jsonify({'favorites': result})


@favorites_bp.route('/favorites/check', methods=['POST'])
def check_favorite():
    """Check if product is in favorites"""
    data = request.get_json()
    product_id = data.get('product_id')
    color_name = data.get('color_name')
    
    is_favorite = False
    
    if current_user.is_authenticated:
        favorite = Favorite.query.filter_by(
            user_id=current_user.id,
            product_id=product_id,
            color_name=color_name
        ).first()
        is_favorite = favorite is not None
    else:
        session_favorites = session.get('favorites', [])
        for fav in session_favorites:
            if fav.get('product_id') == product_id and fav.get('color_name') == color_name:
                is_favorite = True
                break
    
    return jsonify({'is_favorite': is_favorite})
