import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail
from werkzeug.utils import secure_filename
from config import Config
from models import db, User, Address, Collection, Product, Design, Order, OrderItem
import stripe
import paypalrestsdk

mail = Mail()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    mail.init_app(app)
    
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
        cart_count = 0
        if 'cart' in session:
            cart_count = sum(item['quantity'] for item in session['cart'])
        return {
            'cart_count': cart_count,
            'current_year': 2026
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
        """Create admin user."""
        email = input('Admin email: ')
        password = input('Admin password: ')
        
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print('User already exists.')
            return
        
        admin = User(
            email=email,
            first_name='Admin',
            last_name='User',
            is_admin=True
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f'Admin user created: {email}')
    
    @app.cli.command()
    def sync_catalog():
        """Sync product catalog from S&S Activewear API."""
        try:
            from services.ssactivewear_api import SSActivewearAPI
            
            print('Syncing catalog from S&S Activewear...')
            api = SSActivewearAPI()
            products_data = api.sync_bella_canvas_catalog()
            
            added = 0
            updated = 0
            
            for product_data in products_data:
                existing = Product.query.filter_by(style_number=product_data['style_number']).first()
                
                if existing:
                    # Update existing
                    for key, value in product_data.items():
                        setattr(existing, key, value)
                    updated += 1
                else:
                    # Add new
                    new_product = Product(**product_data)
                    db.session.add(new_product)
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
