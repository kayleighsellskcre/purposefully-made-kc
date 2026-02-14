from flask import Blueprint, render_template, session, current_app, send_file
from models import Product, Collection
import os

main_bp = Blueprint('main', __name__)


@main_bp.route('/uploads/mockups/<path:path>')
def serve_mockup(path):
    """Serve mockup images from uploads/mockups (static/uploads/mockups or project uploads/mockups)."""
    path = path.strip('/').replace('..', '')
    if not path:
        return '', 404
    bases = [
        os.path.realpath(os.path.join(current_app.root_path, '..', 'static', 'uploads', 'mockups')),
        os.path.realpath(os.path.join(current_app.root_path, '..', 'uploads', 'mockups')),
    ]
    for base in bases:
        if not os.path.isdir(base):
            continue
        filepath = os.path.normpath(os.path.join(base, path))
        filepath = os.path.realpath(filepath)
        if not filepath.startswith(base) or not os.path.isfile(filepath):
            continue
        return send_file(filepath)
    return '', 404


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
