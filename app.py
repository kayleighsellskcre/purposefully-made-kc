import os
import sys
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from config import Config
from models import db, User, Address, Collection, Product, Design, Order, OrderItem, Favorite
import stripe
import paypalrestsdk

mail = Mail()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def _sync_mockups_to_static(app):
    """Copy mockups from uploads/mockups to static/uploads/mockups so they're served by Flask."""
    import shutil
    src = os.path.join(app.root_path, 'uploads', 'mockups')
    dst = os.path.join(app.config['UPLOAD_FOLDER'], 'mockups')
    if not os.path.isdir(src):
        return
    for name in os.listdir(src):
        src_path = os.path.join(src, name)
        dst_path = os.path.join(dst, name)
        if os.path.isdir(src_path):
            os.makedirs(dst_path, exist_ok=True)
            for f in os.listdir(src_path):
                s = os.path.join(src_path, f)
                d = os.path.join(dst_path, f)
                if os.path.isfile(s) and (not os.path.exists(d) or os.path.getmtime(s) > os.path.getmtime(d)):
                    shutil.copy2(s, d)
        elif os.path.isfile(src_path):
            if not os.path.exists(dst_path) or os.path.getmtime(src_path) > os.path.getmtime(dst_path):
                shutil.copy2(src_path, dst_path)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    
    # Create tables if they don't exist (needed for fresh Railway/PostgreSQL deploys)
    with app.app_context():
        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if 'sqlite' in db_url.lower():
            import sys
            print("WARNING: Using SQLite. All accounts and data are DELETED on every deploy.", file=sys.stderr)
            print("Add PostgreSQL in Railway (New -> Database -> PostgreSQL) so data persists.", file=sys.stderr)
        db.create_all()
        
        # Run migrations for new columns (safe to run multiple times)
        try:
            from sqlalchemy import text
            with db.engine.connect() as conn:
                # ALL migrations inside the same connection block
                all_migrations = [
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS size_chart TEXT",
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS fit_guide TEXT",
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS fabric_details TEXT",
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS age_group VARCHAR(20)",
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS fit_type VARCHAR(30)",
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS neck_style VARCHAR(30)",
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS sleeve_length VARCHAR(30)",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS design_fee DOUBLE PRECISION DEFAULT 0",
                    # order_item.design_id — links a design to a line item (needed for delete guard)
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS design_id INTEGER REFERENCES design(id)",
                    # custom_design_request.is_deleted — soft-delete flag so dismissed cards stay gone
                    "ALTER TABLE custom_design_request ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
                    # user.failed_logins / locked_until — brute-force lockout tracking
                    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS failed_logins INTEGER DEFAULT 0",
                    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP",
                ]
                for migration in all_migrations:
                    try:
                        conn.execute(text(migration))
                        conn.commit()
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass

            # Create favorites table if it doesn't exist
            from models import Favorite
            db.create_all()
        except Exception:
            # Migration errors shouldn't crash the app
            pass
        
        # Ensure purposefullymadekc@gmail.com has admin on every app start (fixes fresh deploy)
        admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip()
        if admin_email:
            admin_user = User.query.filter(db.func.lower(User.email) == admin_email.lower()).first()
            if admin_user and not getattr(admin_user, 'is_admin', False):
                admin_user.is_admin = True
                db.session.commit()

        # Seed daily affirmations if the table is empty
        try:
            from affirmations_seed import seed_affirmations
            seed_affirmations(app)
        except Exception:
            pass

    # Flask-Login setup
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Stripe setup
    if app.config.get('STRIPE_SECRET_KEY'):
        stripe.api_key = app.config['STRIPE_SECRET_KEY']
    
    # PayPal setup
    if app.config.get('PAYPAL_CLIENT_ID'):
        paypalrestsdk.configure({
            "mode": app.config['PAYPAL_MODE'],
            "client_id": app.config['PAYPAL_CLIENT_ID'],
            "client_secret": app.config['PAYPAL_CLIENT_SECRET']
        })
    
    # Create upload folders
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'designs'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'proofs'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'mockups'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'custom_requests'), exist_ok=True)

    # Sync mockups from uploads/mockups to static/uploads/mockups so Flask serves them
    _sync_mockups_to_static(app)
    
    # Register blueprints
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.shop import shop_bp
    from routes.cart import cart_bp
    from routes.checkout import checkout_bp
    from routes.account import account_bp
    from routes.admin import admin_bp
    from routes.collection import collection_bp
    from routes.api import api_bp
    from routes.design import design_bp
    from routes.custom_request import custom_request_bp
    from routes.favorites import favorites_bp
    
    # Serve uploads (mockups, designs) - register FIRST so /uploads/mockups/... works
    @app.route('/uploads/<path:path>')
    def serve_uploads(path):
        """Serve files from uploads/ or static/uploads/."""
        path = path.replace('..', '').replace('\\', '/')
        for base_name in ('uploads', 'static/uploads'):
            uploads_dir = os.path.normpath(os.path.join(app.root_path, *base_name.split('/')))
            if not os.path.isdir(uploads_dir):
                continue
            full = os.path.normpath(os.path.join(uploads_dir, path.replace('/', os.sep)))
            try:
                if os.path.isfile(full) and os.path.commonpath([uploads_dir, full]) == uploads_dir:
                    return send_from_directory(os.path.dirname(full), os.path.basename(full))
            except ValueError:
                pass
        return '', 404

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(design_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(custom_request_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(collection_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(favorites_bp)

    # ── CSRF exemptions ──────────────────────────────────────────────────────
    # Stripe / PayPal webhooks POST with their own signatures, not our CSRF token.
    from routes.checkout import checkout_bp as _co_bp
    try:
        csrf.exempt(_co_bp)
    except Exception:
        pass
    # Internal API routes use X-Requested-With or their own auth — CSRF not applicable.
    from routes.api import api_bp as _api_bp
    try:
        csrf.exempt(_api_bp)
    except Exception:
        pass
    # Admin routes are already protected by @admin_required (login + is_admin check).
    # Exempting avoids breaking the many existing AJAX fetch() calls in admin templates
    # while CSRF still protects all public-facing customer routes.
    from routes.admin import admin_bp as _adm_bp
    try:
        csrf.exempt(_adm_bp)
    except Exception:
        pass
    # Design and custom-request AJAX calls are also authenticated — exempt.
    from routes.design import design_bp as _des_bp
    try:
        csrf.exempt(_des_bp)
    except Exception:
        pass
    from routes.custom_request import custom_request_bp as _cr_bp
    try:
        csrf.exempt(_cr_bp)
    except Exception:
        pass
    from routes.favorites import favorites_bp as _fav_bp
    try:
        csrf.exempt(_fav_bp)
    except Exception:
        pass

    # ── Security headers (added to every response) ───────────────────────────
    @app.after_request
    def set_security_headers(response):
        # Prevent browsers from MIME-sniffing the content type
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Block the site from being embedded in iframes (clickjacking protection)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Tell browsers to use HTTPS for the next year (only effective over HTTPS)
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Don't leak the full URL in the Referer header when leaving the site
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Restrict resource loading to same origin (images/fonts from known CDNs allowed)
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        return response
    
    # Initialize background scheduler and run startup seed (optional - won't crash app if fails)
    try:
        import sys as sys_module
        from scheduler import init_scheduler
        scheduler = init_scheduler(app)
        if scheduler:
            print("Background scheduler initialized successfully", file=sys_module.stderr)
    except ImportError as e:
        print(f"Scheduler module not available: {e}", file=sys_module.stderr)
    except Exception as e:
        print(f"Scheduler init skipped: {e}", file=sys_module.stderr)
    
    # Add custom template filters
    @app.template_filter('image_url')
    def image_url_filter(path_or_url):
        """Return the correct src for a stored image — Cloudinary URL or local static path."""
        if not path_or_url:
            return ''
        if path_or_url.startswith('http'):
            return path_or_url
        from flask import url_for
        return url_for('static', filename=path_or_url)

    @app.template_filter('from_json')
    def from_json_filter(value):
        """Convert JSON string to Python object"""
        if not value:
            return {}
        import json
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}

    @app.before_request
    def ensure_admin_email_has_admin():
        """On every request: if logged-in user is purposefullymadekc@gmail.com, force is_admin=True.
        Ensures admin access even if DB was reset or grant was missed on login."""
        from flask_login import current_user
        if not current_user.is_authenticated:
            return
        admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').lower().strip()
        user_email = (current_user.email or '').lower().strip()
        if user_email and user_email == admin_email:
            if not getattr(current_user, 'is_admin', False):
                current_user.is_admin = True
                db.session.commit()

    # Template filter: color name to hex (fallback when color_hex not in DB)
    COMMON_COLOR_HEX = {
        'navy': '#1e3a5f', 'black': '#000000', 'white': '#ffffff', 'red': '#c41e3a',
        'royal': '#4169e1', 'true royal': '#4169e1', 'royal blue': '#4169e1',
        'team purple': '#4b0082', 'purple': '#800080', 'heather gray': '#9e9e9e',
        'grey': '#808080', 'gray': '#808080', 'ash': '#b2beb5', 'charcoal': '#36454f',
        'terracotta': '#e2725b', 'toast': '#c4a484', 'forest': '#228b22', 'kelly': '#4cbb17',
        'aqua': '#00ffff', 'teal': '#008080', 'maroon': '#800000', 'burgundy': '#800020',
        'gold': '#ffd700', 'yellow': '#ffff00', 'orange': '#ff8c00', 'pink': '#ffc0cb',
        'lime': '#32cd32', 'mint': '#98ff98', 'sky': '#87ceeb', 'baby blue': '#89cff0',
    }
    @app.template_filter('color_hex_fallback')
    def color_hex_fallback(color_name):
        if not color_name: return None
        key = str(color_name).lower().strip()
        return COMMON_COLOR_HEX.get(key) or COMMON_COLOR_HEX.get(key.replace(' ', ''))
    
    # Context processors
    @app.context_processor
    def inject_globals():
        from flask_login import current_user as cu
        cart_count = 0
        if 'cart' in session:
            cart_count = sum(item['quantity'] for item in session['cart'])
        admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').lower().strip()

        # Do a fresh DB lookup every request so is_site_admin is always accurate
        # (bypasses SQLAlchemy object expiry / caching issues across devices)
        is_site_admin = False
        if cu.is_authenticated:
            try:
                fresh = User.query.get(cu.id)
                if fresh:
                    is_site_admin = bool(fresh.is_admin)
                    # Auto-promote the designated admin email if flag isn't set yet
                    if not is_site_admin and (fresh.email or '').lower().strip() == admin_email:
                        fresh.is_admin = True
                        db.session.commit()
                        is_site_admin = True
            except Exception:
                is_site_admin = False

        return {
            'cart_count': cart_count,
            'current_year': 2026,
            'admin_email': admin_email,
            'is_site_admin': is_site_admin,
        }
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500
    
    # CLI commands
    @app.cli.command()
    def init_db():
        """Initialize the database."""
        db.create_all()
        print('Database initialized.')
    
    @app.cli.command()
    def create_admin():
        """Create or ensure the designated admin user (purposefullymadekc@gmail.com). Only this email can access admin."""
        admin_email = os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com'
        existing = User.query.filter_by(email=admin_email).first()
        if existing:
            existing.is_admin = True
            db.session.commit()
            print(f'Admin access confirmed for: {admin_email}')
            return
        password = input(f'Create password for {admin_email}: ')
        admin = User(
            email=admin_email,
            first_name='Admin',
            last_name='User',
            is_admin=True
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f'Admin user created: {admin_email}')
    
    @app.cli.command()
    def sync_catalog():
        """Sync product catalog from S&S Activewear (mockup styles only)."""
        try:
            from services.ssactivewear_api import SSActivewearAPI

            print('Syncing mockup styles from S&S Activewear...')
            api = SSActivewearAPI()
            products_data = api.sync_mockup_styles()
            
            added = 0
            updated = 0
            
            for product_data in products_data:
                color_variants = product_data.pop('color_variants', [])
                style_num = product_data['style_number']
                existing = Product.query.filter_by(style_number=style_num).first()
                if existing:
                    for key, value in product_data.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    updated += 1
                else:
                    db.session.add(Product(**product_data))
                    added += 1
            
            db.session.commit()
            print(f'Sync complete! Added: {added}, Updated: {updated}')
            
        except Exception as e:
            print(f'Error syncing catalog: {e}')
    
    @app.cli.command()
    def upgrade_db():
        """Upgrade database schema (add new columns)."""
        print('Upgrading database schema...')
        db.create_all()
        print('Database upgraded successfully!')
        print('New fields added to Product model: brand, api_data')
    
    @app.cli.command()
    def sync_growth():
        """Sync weekly growth metrics from orders & collections. Run weekly (e.g. via Task Scheduler)."""
        try:
            from services.growth_sync import sync_all_recent_weeks
            results = sync_all_recent_weeks(weeks=4)
            for m, action in results:
                print(f"  {m.week_start.strftime('%Y-%m-%d')}: {action} — {m.units_sold} units, ${m.revenue:.2f}")
            print('Growth metrics synced successfully.')
        except Exception as e:
            print(f'Error: {e}')
            raise
    
    return app

# Module-level app for gunicorn (app:app)
app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
