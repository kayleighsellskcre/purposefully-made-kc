from flask import Blueprint, render_template, session
from models import Product, Collection

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Homepage"""
    session.pop('collection_id', None)
    featured_products = Product.query.filter_by(is_active=True).order_by(Product.style_number).limit(8).all()
    active_collections = Collection.query.filter_by(is_active=True).order_by(Collection.created_at.desc()).limit(6).all()
    return render_template('index.html', 
                         featured_products=featured_products,
                         active_collections=active_collections)

@main_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@main_bp.route('/contact')
def contact():
    """Contact page"""
    return render_template('contact.html')
