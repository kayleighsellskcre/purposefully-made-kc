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


@main_bp.route('/status')
def status():
    """Diagnostics: what's configured (no secrets shown). Visit /status to see why things might not connect."""
    from models import db, User, Product
    import os

    admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip()
    ss_key = os.environ.get('SSACTIVEWEAR_API_KEY') or ''
    ss_account = os.environ.get('SSACTIVEWEAR_ACCOUNT_NUMBER') or ''
    db_url = os.environ.get('DATABASE_URL') or ''

    db_ok = False
    try:
        Product.query.first()
        db_ok = True
    except Exception:
        pass

    admin_user = User.query.filter(db.func.lower(User.email) == admin_email.lower()).first() if admin_email else None
    product_count = Product.query.count()

    return render_template('status.html',
        admin_email_set=bool(admin_email),
        admin_email_value=admin_email,
        admin_user_exists=admin_user is not None,
        admin_user_is_admin=admin_user.is_admin if admin_user else False,
        ss_key_set=bool(ss_key and ss_key.strip() and 'your_' not in ss_key.lower() and 'paste' not in ss_key.lower()),
        ss_account_set=bool(ss_account and ss_account.strip() and 'your_' not in ss_account.lower() and 'paste' not in ss_account.lower()),
        db_using_postgres='postgresql' in db_url or 'postgres' in db_url,
        db_ok=db_ok,
        product_count=product_count,
    )
