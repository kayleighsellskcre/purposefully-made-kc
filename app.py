import os
import sys
from flask import Flask, Request, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
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


class SiteRequest(Request):
    """Form limits sized for this site's largest form.

    Werkzeug allows 1000 multipart parts by default, counting every checkbox,
    not just files. The Create Group Order form renders one checkbox per active
    product and one per brand/colour pair — 995 parts on the live catalogue.
    Adding a single colour pushed it over, and "Create Group Order" started
    failing with 413 Request Entity Too Large; it did so six times on 17 Aug
    before anyone understood why, because the message talks about data size and
    the payload was only about 100 KB.

    These are set on the request class rather than in config because Flask only
    began reading them from config in 3.1, and requirements.txt pins 3.0.

    MAX_CONTENT_LENGTH in config.py is still the real upload guard.
    """

    max_form_parts = 5000
    max_form_memory_size = 2 * 1024 * 1024


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
    app.request_class = SiteRequest
    app.config.from_object(config_class)

    # Ensure all externally generated URLs use https in production.
    # This fixes OG tags, share links, and email links that were http://.
    if os.environ.get('PREFERRED_URL_SCHEME', 'https') == 'https':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

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
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS original_filename VARCHAR(500)",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS file_size INTEGER",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS width INTEGER",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS height INTEGER",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS dpi INTEGER",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS has_transparency BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS title VARCHAR(200)",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS folder VARCHAR(100)",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS sku VARCHAR(50)",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS gallery_submitted BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS gallery_status VARCHAR(20)",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS gallery_rejection_reason TEXT",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS gallery_submitted_at TIMESTAMP",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS gallery_reviewed_at TIMESTAMP",
                    "ALTER TABLE design ADD COLUMN IF NOT EXISTS gallery_reviewed_by_id INTEGER REFERENCES \"user\"(id)",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS back_design_meta TEXT",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS back_design_file_name VARCHAR(500)",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS print_width DOUBLE PRECISION",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS print_height DOUBLE PRECISION",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS transfer_production TEXT",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS position_x DOUBLE PRECISION",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS position_y DOUBLE PRECISION",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS rotation DOUBLE PRECISION DEFAULT 0",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS proof_image VARCHAR(500)",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS proof_back_image VARCHAR(500)",
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS notes TEXT",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS collection_id INTEGER REFERENCES collection(id)",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS production_stage VARCHAR(50)",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS order_type VARCHAR(20) DEFAULT 'retail'",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS due_date TIMESTAMP",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS cost_of_goods DOUBLE PRECISION",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS checkout_token VARCHAR(64)",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS confirmation_email_sent_at TIMESTAMP",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS profit DOUBLE PRECISION",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS is_refunded BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS refund_notes TEXT",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(200)",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS carrier VARCHAR(100)",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS send_home_with_child BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS teacher_name VARCHAR(120)",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS child_grade VARCHAR(40)",
                    "ALTER TABLE \"order\" ADD COLUMN IF NOT EXISTS child_name VARCHAR(120)",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS description TEXT",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS is_password_protected BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS password_hash VARCHAR(256)",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS pickup_address TEXT",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS pickup_instructions TEXT",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS order_opens_at TIMESTAMP",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS order_deadline TIMESTAMP",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS shipping_enabled BOOLEAN DEFAULT TRUE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS tax_rate DOUBLE PRECISION DEFAULT 9.5",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS restrict_options BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS allowed_colors TEXT",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS allowed_design_ids TEXT",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS allowed_placements TEXT",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS allow_custom_upload BOOLEAN DEFAULT TRUE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS back_design_font VARCHAR(50)",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS share_token VARCHAR(64)",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS back_design_text_color VARCHAR(20)",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS back_design_outline BOOLEAN DEFAULT TRUE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS back_design_outline_color VARCHAR(20)",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS lock_back_design_style BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS is_customer_favorite BOOLEAN DEFAULT FALSE",
                    # order_item.design_id — links a design to a line item (needed for delete guard)
                    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS design_id INTEGER REFERENCES design(id)",
                    # custom_design_request.is_deleted — soft-delete flag so dismissed cards stay gone
                    "ALTER TABLE custom_design_request ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
                    # custom_design_request.emails_sent_at — idempotency marker for the
                    # customer confirmation + business notification pair
                    "ALTER TABLE custom_design_request ADD COLUMN IF NOT EXISTS emails_sent_at TIMESTAMP",
                    # user.failed_logins / locked_until — brute-force lockout tracking
                    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS failed_logins INTEGER DEFAULT 0",
                    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP",
                    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS reset_token VARCHAR(128)",
                    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMP",
                    # collection.created_by_user_id — tracks who created a group order (for delete-design permission)
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES \"user\"(id)",
                    # Group-order organizer options + public directory listing
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS allow_back_design BOOLEAN DEFAULT TRUE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS back_design_type VARCHAR(20) DEFAULT 'both'",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS show_in_directory BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS cover_image VARCHAR(500)",
                    "ALTER TABLE collection ADD COLUMN IF NOT EXISTS card_title VARCHAR(200)",
                    # product.spec_sheet_url — SanMar CDN PDF link added during Bella+Canvas CSV import
                    "ALTER TABLE product ADD COLUMN IF NOT EXISTS spec_sheet_url VARCHAR(500)",
                    # product_color_variant.color_swatch_url — SanMar CDN swatch image (color_hex is only 7 chars)
                    "ALTER TABLE product_color_variant ADD COLUMN IF NOT EXISTS color_swatch_url VARCHAR(500)",
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

                # Enforce one order per checkout token at the database level, so
                # two simultaneous submits cannot both pass the application's
                # duplicate check and create a double order. Partial index keeps
                # the many NULL tokens (admin-created orders) legal.
                try:
                    conn.execute(text(
                        'CREATE UNIQUE INDEX IF NOT EXISTS uq_order_checkout_token '
                        'ON "order" (checkout_token) WHERE checkout_token IS NOT NULL'
                    ))
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            # Create favorites table if it doesn't exist
            from models import Favorite
            db.create_all()

            # ── One-time product category fixes ──────────────────────────────
            # Onesies: 100B and 134B were mis-labelled as "Tee"
            # Shorts:  0814, 3787, 3797, 6824GD were mis-labelled as "Tee"
            # Bodysuit: 0990 was mis-labelled as "Tee"
            _cat_fixes = [
                ("UPDATE product SET category = 'Onesie' WHERE style_number IN ('100B','134B') AND category = 'Tee'",),
                ("UPDATE product SET category = 'Shorts' WHERE style_number IN ('0814','3787','3797','6824GD') AND category = 'Tee'",),
                ("UPDATE product SET category = 'Bodysuit' WHERE style_number = '0990' AND category = 'Tee'",),
            ]
            for (fix_sql,) in _cat_fixes:
                try:
                    with db.engine.connect() as _conn:
                        _conn.execute(text(fix_sql))
                        _conn.commit()
                except Exception:
                    pass

            # KS sales tax is fixed at 9.5% — normalize any stale/0 rates from when
            # organizers could edit the field.
            try:
                _tax_pct = float(app.config.get('KS_SALES_TAX_PERCENT', 9.5))
                with db.engine.connect() as _conn:
                    _conn.execute(text(
                        "UPDATE collection SET tax_rate = :rate "
                        "WHERE tax_rate IS NULL OR tax_rate <> :rate"
                    ), {"rate": _tax_pct})
                    _conn.commit()
            except Exception:
                pass
        except Exception:
            # Migration errors shouldn't crash the app
            pass
        
        # Ensure the one admin account has is_admin=True; revoke from all others
        _admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip().lower()
        if _admin_email:
            # Grant to approved admin
            _au = User.query.filter(db.func.lower(User.email) == _admin_email).first()
            if _au and not getattr(_au, 'is_admin', False):
                _au.is_admin = True
                db.session.commit()
            # Revoke from anyone else who has is_admin=True
            try:
                _non_admins = User.query.filter(
                    User.is_admin == True,
                    db.func.lower(User.email) != _admin_email
                ).all()
                for _u in _non_admins:
                    _u.is_admin = False
                if _non_admins:
                    db.session.commit()
            except Exception:
                pass

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
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None
    
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
    # Cart routes are JSON API calls from the browser — CSRF token not available.
    from routes.cart import cart_bp as _cart_bp
    try:
        csrf.exempt(_cart_bp)
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
        # Disable browser features that this site doesn't need
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        # Content-Security-Policy: restrict what scripts/styles/frames can load.
        # Protects clients from XSS and data-injection attacks.
        # 'unsafe-inline' is required for our inline <script> and <style> tags;
        # remove it in the future by migrating to nonces.
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "js.stripe.com www.paypal.com www.paypalobjects.com "
                "cdnjs.cloudflare.com cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' "
                "fonts.googleapis.com cdnjs.cloudflare.com cdn.jsdelivr.net fonts.cdnfonts.com; "
            "font-src 'self' fonts.gstatic.com data: fonts.cdnfonts.com; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' api.stripe.com api.ssactivewear.com; "
            "frame-src js.stripe.com www.paypal.com; "
            "object-src 'none'; "
            "base-uri 'self';"
        )
        response.headers['Content-Security-Policy'] = csp
        return response
    
    # Do NOT preload rembg here. create_app() runs in every gunicorn worker;
    # downloading isnet/u2net at boot OOMs Railway and the deploy never goes live.
    # The model loads on the first upload instead.

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
    
    # Apple Pay domain verification — required for Apple Pay to work on Safari/iOS.
    # Apple fetches this URL to confirm the domain is authorized to use Apple Pay via Stripe.
    @app.route('/.well-known/apple-developer-merchantid-domain-association')
    def apple_pay_domain_association():
        import requests as _req
        try:
            r = _req.get(
                'https://stripe.com/files/apple-pay/apple-developer-merchantid-domain-association',
                timeout=10
            )
            return r.content, 200, {'Content-Type': 'application/octet-stream'}
        except Exception:
            return '', 404

    # Diagnostic endpoint — tells us which git commit Railway is running.
    # Check at /version to verify deployments landed.
    @app.route('/version')
    def _version():
        import subprocess, datetime
        try:
            commit = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            commit = 'unknown'
        return jsonify({
            'commit': commit,
            'time': datetime.datetime.utcnow().isoformat(),
            'rembg_model_loaded': bool(getattr(__import__('services.image_processing', fromlist=['_SESSION_CACHE']), '_SESSION_CACHE', {})),
        })

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

    @app.template_filter('sort_sizes')
    def sort_sizes_filter(sizes):
        """Order apparel sizes XS → 6XL (and baby/youth equivalents)."""
        from utils.sizes import sort_sizes
        return sort_sizes(sizes or [])

    @app.template_filter('inches')
    def inches_filter(value):
        """Format a measurement in inches to two decimal places."""
        from utils.print_sizes import format_inches
        return format_inches(value)

    @app.template_filter('inch_wh')
    def inch_wh_filter(pair):
        """Format (width, height) as 10.00″ W × 8.50″ H."""
        from utils.print_sizes import format_wh
        if not pair:
            return 'N/A'
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            return format_wh(pair[0], pair[1])
        return 'N/A'

    @app.template_filter('central')
    def central_filter(dt, fmt='%B %d, %Y at %I:%M %p'):
        """Show a stored UTC datetime in Kansas City time."""
        from utils.local_time import format_central
        return format_central(dt, fmt)

    @app.template_filter('kc_date')
    def kc_date_filter(dt, fmt='%B %d, %Y'):
        """Group-order calendar date in Kansas City time."""
        from utils.group_orders import format_schedule_date
        return format_schedule_date(dt, fmt)

    @app.template_filter('kc_date_input')
    def kc_date_input_filter(dt):
        """YYYY-MM-DD for date inputs, in Kansas City time."""
        from utils.group_orders import schedule_date_input
        return schedule_date_input(dt)

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
        """On every request: if logged-in user is a known admin email, force is_admin=True.
        Ensures admin access even if DB was reset or grant was missed on login."""
        from flask_login import current_user
        if not current_user.is_authenticated:
            return
        _known_admins = {
            (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').lower().strip(),
        }
        user_email = (current_user.email or '').lower().strip()
        if user_email and user_email in _known_admins:
            if not getattr(current_user, 'is_admin', False):
                try:
                    current_user.is_admin = True
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass

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
        try:
            cart = session.get('cart')
            if isinstance(cart, list):
                for item in cart:
                    if isinstance(item, dict):
                        try:
                            cart_count += int(item.get('quantity') or 0)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            cart_count = 0
        admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').lower().strip()

        # Fresh DB lookup so is_site_admin is always accurate.
        # Wrapped tightly so a DB hiccup never breaks template rendering.
        # getattr rather than cu.is_authenticated: outside a request context
        # (background email threads) the proxy resolves to None, and the bare
        # attribute access raised AttributeError mid-render.
        is_site_admin = False
        if getattr(cu, 'is_authenticated', False):
            try:
                is_site_admin = bool(getattr(cu, 'is_admin', False))
            except Exception:
                is_site_admin = False

        from datetime import datetime as _dt
        active_group_order = None
        try:
            from utils.group_orders import get_active_collection
            active_group_order = get_active_collection(session.get('cart'))
        except Exception:
            active_group_order = None
        # Canonical URL and origin for <link rel="canonical"> and Open Graph.
        #
        # request.base_url was used before, which echoes whatever host the
        # visitor happened to arrive on. Reaching the site as www and non-www,
        # or over http, produced a different canonical each time and told search
        # engines the same page lived at several addresses. SITE_ORIGIN pins it
        # to one preferred address.
        site_origin = (app.config.get('SITE_ORIGIN') or '').rstrip('/')
        try:
            if site_origin:
                canonical_url = site_origin + request.path
            else:
                canonical_url = request.base_url
        except Exception:
            canonical_url = site_origin or ''

        # Whole areas of the site should never appear in search results: the
        # admin, a customer's account, the cart and checkout, and the sign-in
        # pages. Deciding this from the blueprint covers every template at once,
        # including the forty-odd admin ones, and cannot be forgotten on a new
        # page. A template can still override the `robots` block.
        private_blueprints = {
            'admin', 'account', 'auth', 'cart', 'checkout', 'favorites',
        }
        try:
            is_private = request.blueprint in private_blueprints
        except Exception:
            is_private = False
        robots_directive = 'noindex, nofollow' if is_private else 'index, follow'

        return {
            'cart_count': cart_count,
            'current_year': _dt.now().year,
            'admin_email': admin_email,
            'is_site_admin': is_site_admin,
            'active_group_order': active_group_order,
            'site_origin': site_origin,
            'canonical_url': canonical_url,
            'robots_directive': robots_directive,
        }
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(413)
    def request_too_large(error):
        """Handle a request that exceeded one of the body limits.

        Two very different things land here, and saying "your file was too
        large" for both sent us chasing an imaginary upload problem for the
        group-order form, where the payload was 100 KB of checkboxes. Compare
        the declared length against the limit to tell them apart.

        - AJAX/JSON requests → JSON error (fetch() in customize.html can parse it)
        - Regular form POSTs → flash + redirect back so the user sees a message
        """
        from flask import request as _req, jsonify as _json, redirect, flash as _flash
        limit_bytes = int(app.config.get('MAX_CONTENT_LENGTH') or 50 * 1024 * 1024)
        limit_mb = limit_bytes // (1024 * 1024)
        oversized_body = (_req.content_length or 0) > limit_bytes

        if oversized_body:
            message = (
                f'That upload is too large (limit: {limit_mb} MB). '
                'On iPhone: share the photo and choose "Medium" size. '
                'On Android: use a photo editor to reduce the size first.'
            )
        else:
            message = (
                'That form had too many options selected at once for us to '
                'process. Please choose fewer colours or styles and try again — '
                'and let us know, because this is our bug, not yours.'
            )
            app.logger.error(
                '413 with only %s bytes on %s — form part limit (%s) was hit',
                _req.content_length, _req.path, _req.max_form_parts,
            )

        is_ajax = (
            _req.path.startswith('/design/')
            or 'json' in _req.headers.get('Accept', '')
            or _req.is_json
            or _req.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )
        if is_ajax:
            return _json({'error': message}), 413

        _flash(message, 'error')
        return redirect(_req.referrer or '/')

    @app.errorhandler(500)
    def internal_error(error):
        try:
            db.session.rollback()
        except Exception:
            pass
        error_id = None
        notified = False
        try:
            from utils.error_notify import new_error_id, record_and_notify
            error_id = new_error_id()
            error_id, notified = record_and_notify(app, error, error_id=error_id)
        except Exception:
            app.logger.exception('internal_error notify failed: %s', error)
        wants_json = False
        try:
            accept = request.headers.get('Accept') or ''
            wants_json = (
                request.path.startswith('/checkout/')
                or request.path.startswith('/cart/')
                or request.path.startswith('/api/')
                or request.is_json
                or 'application/json' in accept
                or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            )
        except Exception:
            pass
        if wants_json:
            from flask import jsonify as _jsonify
            return _jsonify({
                'success': False,
                'error': 'Something went wrong. Your cart is still saved — please try again.',
                'error_code': 'SERVER_ERROR',
                'error_id': error_id,
            }), 500
        try:
            return render_template(
                'errors/500.html',
                error_id=error_id,
                notified=notified,
                safe_back_url=request.referrer if request.referrer else None,
            ), 500
        except Exception as tmpl_err:
            from flask import jsonify as _jsonify
            return _jsonify({
                'error': 'Internal server error',
                'error_id': error_id,
                'detail': str(error),
                'template_error': str(tmpl_err),
            }), 500
    
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
            print(f'Error syncing growth metrics: {e}')

    # ── Widen image import — no blueprint, CORS-open ─────────────────────────
    # Registered inside the factory. It used to be attached to the module-level
    # `app` below, which meant any app built by create_app() — every test, every
    # script — had no such route. A security-critical, unauthenticated,
    # CORS-open endpoint that writes product images cannot be one that tests are
    # structurally unable to reach.
    @app.route('/widen-import', methods=['POST', 'OPTIONS'])
    def widen_import():
        from flask import request as rq, jsonify, make_response
        from models import db, Product, ProductColorVariant
        from datetime import datetime

        def cors(resp):
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return resp

        if rq.method == 'OPTIONS':
            return cors(make_response('', 204))

        from utils.widen_import_auth import secret_matches

        body = rq.get_json(silent=True) or {}
        # Unset WIDEN_IMPORT_SECRET disables this endpoint outright. It writes
        # image URLs for every product with no login session and wildcard CORS,
        # so it should only be reachable while an import is actually running.
        if not secret_matches(body.get('secret')):
            return cors(make_response(jsonify({'error': 'unauthorized'}), 403))

        images = body.get('images', {})
        updated = created = skipped = 0

        for style_number, color_map in images.items():
            product = Product.query.filter_by(style_number=style_number).first()
            if not product:
                skipped += len(color_map)
                continue
            first_front = first_back = None
            for color_name, sides in color_map.items():
                front_url = sides.get('front', '')
                back_url  = sides.get('back', '')
                if not front_url and not back_url:
                    skipped += 1
                    continue
                variant = ProductColorVariant.query.filter(
                    ProductColorVariant.product_id == product.id,
                    db.func.lower(ProductColorVariant.color_name) == color_name.lower()
                ).first()
                if variant:
                    if front_url: variant.front_image_url = front_url
                    if back_url:  variant.back_image_url  = back_url
                    variant.last_synced = datetime.utcnow()
                    updated += 1
                else:
                    db.session.add(ProductColorVariant(
                        product_id=product.id, color_name=color_name,
                        front_image_url=front_url, back_image_url=back_url,
                        last_synced=datetime.utcnow(),
                    ))
                    created += 1
                if not first_front and front_url: first_front = front_url
                if not first_back  and back_url:  first_back  = back_url
            if first_front and not product.front_mockup_template:
                product.front_mockup_template = first_front
            if first_back and not product.back_mockup_template:
                product.back_mockup_template = first_back
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            # The raw exception text names tables and columns, and this endpoint
            # answers any origin. Logged for us, not returned to the caller.
            app.logger.exception('widen-import commit failed')
            return cors(make_response(jsonify({'error': 'import failed'}), 500))

        return cors(make_response(jsonify(
            {'ok': True, 'updated': updated, 'created': created, 'skipped': skipped}), 200))

    return app


app = create_app()


if __name__ == '__main__':
    app.run(debug=False)
