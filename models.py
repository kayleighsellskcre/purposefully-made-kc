from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """Customer or admin user"""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    addresses = db.relationship('Address', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    orders = db.relationship('Order', backref='user', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email
    
    def __repr__(self):
        return f'<User {self.email}>'


class Address(db.Model):
    """Shipping/billing addresses"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    label = db.Column(db.String(50))  # "Home", "Work", etc.
    recipient_name = db.Column(db.String(200))
    street_address = db.Column(db.String(200), nullable=False)
    street_address_2 = db.Column(db.String(200))
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(50), nullable=False)
    zip_code = db.Column(db.String(20), nullable=False)
    country = db.Column(db.String(50), default='USA')
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Address {self.city}, {self.state}>'


class Collection(db.Model):
    """Team/School/Event collections with shareable links"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    share_token = db.Column(db.String(64), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_password_protected = db.Column(db.Boolean, default=False)
    password_hash = db.Column(db.String(256))
    
    # Settings
    pickup_address = db.Column(db.Text)
    pickup_instructions = db.Column(db.Text)
    order_deadline = db.Column(db.DateTime)
    shipping_enabled = db.Column(db.Boolean, default=True)
    tax_rate = db.Column(db.Float, default=0.0)
    
    # Organizer/Admin choices - restrict what team can order (keeps everyone matching)
    restrict_options = db.Column(db.Boolean, default=False)
    allowed_colors = db.Column(db.Text)  # JSON: ["Navy", "White", ...]
    allowed_design_ids = db.Column(db.Text)  # JSON: [1, 2, ...]
    allowed_placements = db.Column(db.Text)  # JSON: ["center_chest", "left_chest", "right_chest", "center_back"]
    allow_custom_upload = db.Column(db.Boolean, default=True)  # When restricted, team can still upload their own design
    back_design_font = db.Column(db.String(50))  # Organizer's chosen font for name/number on back (Bebas Neue, Oswald, Anton, Teko)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    products = db.relationship('Product', secondary='collection_products', backref='collections')
    orders = db.relationship('Order', backref='collection', lazy='dynamic')
    
    def __init__(self, **kwargs):
        super(Collection, self).__init__(**kwargs)
        if not self.share_token:
            self.share_token = secrets.token_urlsafe(32)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.is_password_protected = True
    
    def check_password(self, password):
        if not self.is_password_protected:
            return True
        return check_password_hash(self.password_hash, password)
    
    @property
    def share_url(self):
        return f"/c/{self.slug}"
    
    def __repr__(self):
        return f'<Collection {self.name}>'


# Association table for Collection-Product many-to-many
collection_products = db.Table('collection_products',
    db.Column('collection_id', db.Integer, db.ForeignKey('collection.id'), primary_key=True),
    db.Column('product_id', db.Integer, db.ForeignKey('product.id'), primary_key=True)
)


class Product(db.Model):
    """Bella+Canvas product catalog"""
    id = db.Column(db.Integer, primary_key=True)
    style_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50))  # Tee, Hoodie, Crew, Tank, Youth
    description = db.Column(db.Text)
    
    # Pricing
    base_price = db.Column(db.Float, nullable=False)
    wholesale_cost = db.Column(db.Float)
    
    # Availability
    is_active = db.Column(db.Boolean, default=True)
    
    # Product specs
    available_sizes = db.Column(db.Text)  # JSON string: ["XS", "S", "M", "L", "XL", "2XL", "3XL"]
    available_colors = db.Column(db.Text)  # JSON string
    
    # Mockup configuration
    front_mockup_template = db.Column(db.String(500))  # Path to base front image
    back_mockup_template = db.Column(db.String(500))  # Path to base back image
    print_area_config = db.Column(db.Text)  # JSON: print areas, dimensions, safe zones
    
    # API Integration
    brand = db.Column(db.String(100))  # Brand name (e.g., "Bella+Canvas")
    api_data = db.Column(db.Text)  # JSON: API sync data and metadata
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    order_items = db.relationship('OrderItem', backref='product', lazy='dynamic')
    color_variants = db.relationship('ProductColorVariant', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Product {self.style_number} - {self.name}>'


class ProductColorVariant(db.Model):
    """Color-specific mockup images and inventory for each product"""
    __tablename__ = 'product_color_variant'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    
    # Color info
    color_name = db.Column(db.String(100), nullable=False)
    color_hex = db.Column(db.String(7))  # Optional hex code for display
    
    # Mockup images for this specific color
    front_image_url = db.Column(db.String(500))  # Front mockup of this color
    back_image_url = db.Column(db.String(500))   # Back mockup of this color
    side_image_url = db.Column(db.String(500))   # Optional side view
    
    # Size/inventory data (JSON: {"S": 45, "M": 120, "L": 89, "XL": 67, "2XL": 23})
    size_inventory = db.Column(db.Text)  # Quantity available for each size
    
    # S&S SKU reference
    ss_color_id = db.Column(db.String(50))  # S&S internal color ID
    
    last_synced = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint: one record per product+color
    __table_args__ = (db.UniqueConstraint('product_id', 'color_name', name='_product_color_uc'),)
    
    def __repr__(self):
        return f'<ProductColorVariant {self.color_name}>'


class Design(db.Model):
    """Uploaded artwork/designs"""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(500))
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)  # bytes
    width = db.Column(db.Integer)  # pixels
    height = db.Column(db.Integer)  # pixels
    dpi = db.Column(db.Integer)
    has_transparency = db.Column(db.Boolean, default=False)
    
    # Gallery: designs available for customers to use (uploaded by admin)
    is_gallery = db.Column(db.Boolean, default=False)
    title = db.Column(db.String(200))  # Display name for gallery
    
    # Design organization
    folder = db.Column(db.String(100))  # custom_orders, evergreen, school, holiday, sports, etc.
    sku = db.Column(db.String(50))  # SKU number
    
    # Metadata
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    design_fee = db.Column(db.Float, default=0)  # Custom design fee: 0, 4, or 20 when from "Have Us Recreate"
    
    # Relationships
    user = db.relationship('User', backref='uploaded_designs', foreign_keys=[uploaded_by_user_id])
    order_items = db.relationship('OrderItem', backref='design', lazy='dynamic')
    
    def __repr__(self):
        return f'<Design {self.filename}>'


class CustomDesignRequest(db.Model):
    """Customer request to have an image recreated - they upload reference + description"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Reference image (screenshot or saved image they want recreated)
    reference_file_path = db.Column(db.String(500), nullable=False)
    reference_original_filename = db.Column(db.String(500))
    
    # Customer's description of what they want
    description = db.Column(db.Text, nullable=False)
    
    # Status: pending (awaiting creation), completed (design uploaded to their profile), declined
    status = db.Column(db.String(50), default='pending')
    
    # When admin creates the design, link it here
    created_design_id = db.Column(db.Integer, db.ForeignKey('design.id'))
    
    # Design fee: 0 = exact copy, 4 = lots of changes, 20 = from scratch
    design_fee = db.Column(db.Float, default=0)
    
    # Admin notes (internal)
    admin_notes = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='custom_design_requests')
    created_design = db.relationship('Design', foreign_keys=[created_design_id])
    
    def __repr__(self):
        return f'<CustomDesignRequest {self.id} by {self.user_id}>'


class Order(db.Model):
    """Customer order"""
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    
    # Customer info
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    collection_id = db.Column(db.Integer, db.ForeignKey('collection.id'))
    
    # Contact info (for guest checkout)
    email = db.Column(db.String(120))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    
    # Fulfillment
    fulfillment_method = db.Column(db.String(20), default='pickup')  # pickup or shipping
    
    # Shipping address (if applicable)
    shipping_recipient = db.Column(db.String(200))
    shipping_street = db.Column(db.String(200))
    shipping_street_2 = db.Column(db.String(200))
    shipping_city = db.Column(db.String(100))
    shipping_state = db.Column(db.String(50))
    shipping_zip = db.Column(db.String(20))
    shipping_country = db.Column(db.String(50), default='USA')
    
    # Pricing
    subtotal = db.Column(db.Float, nullable=False)
    shipping_cost = db.Column(db.Float, default=0.0)
    tax = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, nullable=False)
    
    # Payment
    payment_method = db.Column(db.String(50))  # stripe, paypal
    payment_status = db.Column(db.String(50), default='pending')  # pending, paid, failed, refunded
    payment_intent_id = db.Column(db.String(200))  # Stripe payment intent ID
    paypal_order_id = db.Column(db.String(200))  # PayPal order ID
    paid_at = db.Column(db.DateTime)
    
    # Order status
    status = db.Column(db.String(50), default='new')  # new, paid, in_production, ready, picked_up, shipped, completed, cancelled
    
    # Production workflow stage (maps to 5 stages)
    production_stage = db.Column(db.String(50))  # order_received, waiting_supplies, ready_to_press, pressed, packaged_ready
    
    # Order type & revenue tracking
    order_type = db.Column(db.String(20), default='retail')  # retail, wholesale, event
    due_date = db.Column(db.DateTime)
    cost_of_goods = db.Column(db.Float)  # Total COGS for this order
    profit = db.Column(db.Float)  # total - cost_of_goods
    is_refunded = db.Column(db.Boolean, default=False)
    refund_notes = db.Column(db.Text)
    
    # Tracking
    tracking_number = db.Column(db.String(200))
    carrier = db.Column(db.String(100))
    
    # Notes
    customer_notes = db.Column(db.Text)
    admin_notes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    items = db.relationship('OrderItem', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    
    def __init__(self, **kwargs):
        super(Order, self).__init__(**kwargs)
        if not self.order_number:
            self.order_number = self.generate_order_number()
    
    @staticmethod
    def generate_order_number():
        """Generate unique order number"""
        timestamp = datetime.utcnow().strftime('%Y%m%d')
        random_part = secrets.token_hex(4).upper()
        return f"PMKC{timestamp}{random_part}"
    
    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email
    
    def __repr__(self):
        return f'<Order {self.order_number}>'


class OrderItem(db.Model):
    """Individual items in an order"""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    design_id = db.Column(db.Integer, db.ForeignKey('design.id'))
    
    # Product details (snapshot at time of order)
    product_name = db.Column(db.String(200))
    style_number = db.Column(db.String(50))
    size = db.Column(db.String(20), nullable=False)
    color = db.Column(db.String(100), nullable=False)
    
    # Quantity and pricing
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    
    # Print specifications
    placement = db.Column(db.String(50))  # center_chest, left_chest, full_front, full_back, sleeve
    print_type = db.Column(db.String(50))  # DTF, screen_print, vinyl, sublimation, etc.
    design_file_name = db.Column(db.String(500))  # Design file name for production
    back_design_file_name = db.Column(db.String(500))  # Back design (name/number or image) for production
    print_width = db.Column(db.Float)  # inches
    print_height = db.Column(db.Float)  # inches
    position_x = db.Column(db.Float)  # relative position
    position_y = db.Column(db.Float)  # relative position
    rotation = db.Column(db.Float, default=0.0)
    
    # Preview image
    proof_image = db.Column(db.String(500))  # Path to rendered proof
    
    # Notes
    notes = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<OrderItem {self.product_name} - {self.color} {self.size}>'


class Vendor(db.Model):
    """Vendor & supplier database"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(200))
    contact_email = db.Column(db.String(120))
    contact_phone = db.Column(db.String(50))
    website = db.Column(db.String(500))
    website_login = db.Column(db.String(200))  # Login URL or notes
    lead_time_days = db.Column(db.Integer)  # Days to fulfillment
    moq = db.Column(db.Integer)  # Minimum order quantity
    pricing_tier = db.Column(db.String(50))  # Tier notes
    quality_rating = db.Column(db.Integer)  # 1-5
    backup_vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    backup_vendor = db.relationship('Vendor', remote_side=[id])
    
    def __repr__(self):
        return f'<Vendor {self.name}>'


class ApparelInventory(db.Model):
    """Apparel inventory - blanks by brand, color, size"""
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)  # Bella+Canvas 3001, 3001CVC, etc.
    color = db.Column(db.String(100), nullable=False)
    size = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    cost_per_unit = db.Column(db.Float)
    reorder_threshold = db.Column(db.Integer, default=5)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ApparelInventory {self.brand} {self.color} {self.size}>'


class TransferInventory(db.Model):
    """DTF / Screen print transfer inventory"""
    id = db.Column(db.Integer, primary_key=True)
    design_name = db.Column(db.String(200), nullable=False)
    size = db.Column(db.String(50))  # adult, youth, chest width
    quantity = db.Column(db.Integer, default=0)
    cost_per_sheet = db.Column(db.Float)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    delivery_time = db.Column(db.String(50))  # e.g. "3-5 days"
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    vendor = db.relationship('Vendor', backref='transfers')
    
    def __repr__(self):
        return f'<TransferInventory {self.design_name}>'


class Supply(db.Model):
    """Blanks + supplies - heat tape, teflon, packaging, etc."""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50))  # heat_tape, teflon, packaging, ink, blades, etc.
    name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    unit = db.Column(db.String(20), default='ea')  # ea, roll, box, etc.
    cost_per_unit = db.Column(db.Float)
    reorder_threshold = db.Column(db.Integer, default=0)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    vendor = db.relationship('Vendor', backref='supplies')
    
    def __repr__(self):
        return f'<Supply {self.name}>'


class EquipmentLog(db.Model):
    """Equipment maintenance log"""
    id = db.Column(db.Integer, primary_key=True)
    equipment = db.Column(db.String(100), nullable=False)  # heat_press, printer, etc.
    task = db.Column(db.String(200), nullable=False)  # calibration, blade replacement, etc.
    task_date = db.Column(db.DateTime, default=datetime.utcnow)
    next_due = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EquipmentLog {self.equipment} - {self.task}>'


class GrowthMetric(db.Model):
    """Weekly growth dashboard metrics"""
    id = db.Column(db.Integer, primary_key=True)
    week_start = db.Column(db.DateTime, nullable=False)
    units_sold = db.Column(db.Integer, default=0)
    revenue = db.Column(db.Float, default=0)
    website_traffic = db.Column(db.Integer, default=0)
    events_booked = db.Column(db.Integer, default=0)
    wholesale_inquiries = db.Column(db.Integer, default=0)
    social_reach = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<GrowthMetric {self.week_start}>'


class FinancialEntry(db.Model):
    """Financial buckets - revenue, COGS, advertising, equipment, misc"""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)  # revenue, cogs, advertising, equipment, misc
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    entry_date = db.Column(db.DateTime, default=datetime.utcnow)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))  # Link to order if applicable
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    order = db.relationship('Order', backref='financial_entries')
    
    def __repr__(self):
        return f'<FinancialEntry {self.category} ${self.amount}>'


class SystemSettings(db.Model):
    """System-wide settings"""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<SystemSettings {self.key}>'
