import json
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

    # Brute-force lockout: track consecutive bad passwords
    failed_logins = db.Column(db.Integer, default=0, nullable=True)
    locked_until  = db.Column(db.DateTime, nullable=True)

    # Self-serve password reset
    reset_token         = db.Column(db.String(128), nullable=True, index=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    # Logged-in cart shared across devices (JSON array of cart line dicts)
    cart_json = db.Column(db.Text, nullable=True)
    cart_updated_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    addresses = db.relationship('Address', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    orders = db.relationship('Order', backref='user', lazy='dynamic')
    favorites = db.relationship('Favorite', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_locked(self):
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False

    def record_failed_login(self):
        self.failed_logins = (self.failed_logins or 0) + 1
        # Lock for 15 minutes after 5 consecutive failures
        if self.failed_logins >= 5:
            from datetime import timedelta
            self.locked_until = datetime.utcnow() + timedelta(minutes=15)

    def reset_login_attempts(self):
        self.failed_logins = 0
        self.locked_until = None

    def generate_reset_token(self):
        """Create a secure 1-hour reset token and persist it. Returns the raw token."""
        from datetime import timedelta
        self.reset_token = secrets.token_urlsafe(48)
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token

    @staticmethod
    def verify_reset_token(token):
        """Return the User if the token is valid and unexpired, else None."""
        if not token:
            return None
        user = User.query.filter_by(reset_token=token).first()
        if user is None:
            return None
        if user.reset_token_expires is None or user.reset_token_expires < datetime.utcnow():
            return None
        return user

    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expires = None
    
    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email
    
    def __repr__(self):
        return f'<User {self.email}>'


class CartHandoff(db.Model):
    """Short-lived cart transfer so 'Open in Safari' keeps the same checkout cart."""
    __tablename__ = 'cart_handoff'
    token = db.Column(db.String(64), primary_key=True)
    cart_json = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    collection_id = db.Column(db.Integer, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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


class Favorite(db.Model):
    """User's favorite products"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    color_name = db.Column(db.String(100))  # Optional: save specific color
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to product
    product = db.relationship('Product', backref='favorited_by')
    
    def __repr__(self):
        return f'<Favorite user={self.user_id} product={self.product_id}>'


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
    order_opens_at = db.Column(db.DateTime)  # start of ordering window (KC calendar day)
    order_deadline = db.Column(db.DateTime)
    shipping_enabled = db.Column(db.Boolean, default=True)
    # Cash / pay-at-pickup — only offered at checkout when this is on (group orders)
    allow_cash_pickup = db.Column(db.Boolean, default=False)
    tax_rate = db.Column(db.Float, default=9.5)  # always KS 9.5%; not user-editable
    
    # Organizer/Admin choices - restrict what team can order (keeps everyone matching)
    restrict_options = db.Column(db.Boolean, default=False)
    allowed_colors = db.Column(db.Text)  # JSON list (legacy) or {brand: [colors]}
    allowed_design_ids = db.Column(db.Text)  # JSON: [1, 2, ...]
    # Logos shown at the top of the group-order storefront (subset of allowed_design_ids)
    showcase_design_ids = db.Column(db.Text)  # JSON: [1, 2, ...]
    allowed_placements = db.Column(db.Text)  # JSON: ["center_chest", "left_chest", "right_chest", "center_back"]
    allow_custom_upload = db.Column(db.Boolean, default=True)  # When restricted, team can still upload their own design
    back_design_font = db.Column(db.String(50))  # Organizer's chosen font for name/number on back

    # Organizer-set name/number styling — applied when lock_back_design_style is True
    back_design_text_color = db.Column(db.String(20))    # e.g. '#ffffff'
    back_design_outline = db.Column(db.Boolean, default=True)  # whether outline is shown
    back_design_outline_color = db.Column(db.String(20))  # e.g. '#000000'
    # When True + restrict_options, participants cannot change font/color/outline
    lock_back_design_style = db.Column(db.Boolean, default=False)

    # Back design permissions
    # allow_back_design: False = no back design at all; True = use back_design_type
    allow_back_design = db.Column(db.Boolean, default=True)
    # back_design_type: 'name_number' | 'image' | 'both'  (ignored when allow_back_design=False)
    back_design_type = db.Column(db.String(20), default='both')
    # Jersey name line: 'first' or 'last' so parents know what to type.
    back_design_name_part = db.Column(db.String(20), default='last')
    # Organizer artwork that prints only on the back. Kept off allowed_design_ids
    # so it never appears as a front-placement choice.
    back_design_id = db.Column(db.Integer, db.ForeignKey('design.id'), nullable=True)

    # Optional two-lane team store. JSON keeps the uniform product + fixed
    # Home/Away colors separate from the existing fan-wear product/color rules.
    # Null means a legacy fan-wear-only group order.
    team_store_config = db.Column(db.Text)

    # school | team | other. Controls send-home-with-child and whether grade is asked.
    group_kind = db.Column(db.String(20))

    # How the group order is paid for:
    #   'each_pays'      - every shopper checks out and pays for their own item (default)
    #   'organizer_pays' - the link only collects name + size; the organizer pays once
    #   'company_sponsored' - a company covers N items per employee; the organizer
    #                      approves requests and pays one invoice before production
    payment_mode = db.Column(db.String(20), default='each_pays')
    # Company-sponsored only
    sponsor_items_per_person = db.Column(db.Integer, default=1)
    sponsor_budget_per_person = db.Column(db.Float, nullable=True)  # per-item price cap; None = no cap
    sponsor_message = db.Column(db.Text, nullable=True)
    sponsor_submissions_locked = db.Column(db.Boolean, default=False)
    # Organizer-pays only: how many people the organizer expects to respond
    expected_count = db.Column(db.Integer)

    # Public directory — admin toggles this to list the collection on /group-orders
    show_in_directory = db.Column(db.Boolean, default=False)
    # Optional cover photo + short title for the public directory card
    cover_image = db.Column(db.String(500))
    card_title = db.Column(db.String(200))

    # Creator tracking — set when a logged-in user creates via /shop/group-orders/create
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # Email waiting to claim this store if the organizer does not have an account yet
    pending_organizer_email = db.Column(db.String(120))
    # When the "last day to order" reminder went out (so it is never sent twice for one deadline)
    deadline_reminder_sent_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    products = db.relationship('Product', secondary='collection_products', backref='collections')
    orders = db.relationship('Order', backref='collection', lazy='dynamic')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_collections')
    locked_back_design = db.relationship(
        'Design', foreign_keys=[back_design_id], post_update=True
    )
    roster_entries = db.relationship(
        'GroupRosterEntry', backref='collection', lazy='dynamic',
        cascade='all, delete-orphan', order_by='GroupRosterEntry.id',
    )
    
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


class GroupRosterEntry(db.Model):
    """One person's size for an organizer-pays group order (name + size only)."""
    __tablename__ = 'group_roster_entry'
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(
        db.Integer, db.ForeignKey('collection.id'), nullable=False, index=True
    )
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    size = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def __repr__(self):
        return f'<GroupRosterEntry {self.full_name} {self.size}>'


class SponsorSubmission(db.Model):
    """One employee's request under a company-sponsored group order.

    A staging record only: no Order exists (so nothing is produced) until the
    company invoice is paid. items_json holds the full, repriced cart lines so
    the real order can be built from them later.
    """
    __tablename__ = 'sponsor_submission'
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('collection.id'), nullable=False, index=True)

    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))

    fulfillment_method = db.Column(db.String(20), default='pickup')
    shipping_recipient = db.Column(db.String(200))
    shipping_street = db.Column(db.String(200))
    shipping_city = db.Column(db.String(100))
    shipping_state = db.Column(db.String(50))
    shipping_zip = db.Column(db.String(20))

    items_json = db.Column(db.Text, nullable=False)
    sponsored_total = db.Column(db.Float, default=0.0)   # what the company owes (before tax)

    # What the employee pays by card: items past the allowance (or above the price
    # cap), their tax, and shipping if they chose it.
    overage_total = db.Column(db.Float, default=0.0)
    overage_tax = db.Column(db.Float, default=0.0)
    overage_shipping = db.Column(db.Float, default=0.0)
    overage_payment_intent_id = db.Column(db.String(200), index=True)
    overage_paid_at = db.Column(db.DateTime)
    overage_refunded_at = db.Column(db.DateTime)

    # awaiting_payment (employee still paying) -> pending -> approved -> invoiced -> converted,
    # or rejected
    status = db.Column(db.String(20), default='pending', index=True)
    rejection_reason = db.Column(db.Text)

    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
    order = db.relationship('Order', foreign_keys=[order_id])
    # The employee's own paid items go into production at once, as their own order.
    immediate_order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
    immediate_order = db.relationship('Order', foreign_keys=[immediate_order_id])

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    collection = db.relationship('Collection', backref=db.backref('sponsor_submissions', lazy='dynamic'))

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def items(self):
        try:
            return json.loads(self.items_json or '[]')
        except (TypeError, ValueError):
            return []

    @property
    def overage_charge(self):
        return round((self.overage_total or 0) + (self.overage_tax or 0) + (self.overage_shipping or 0), 2)

    @property
    def item_count(self):
        return sum(int(i.get('quantity') or 1) for i in self.items)

    def __repr__(self):
        return f'<SponsorSubmission {self.full_name} collection={self.collection_id}>'


class CompanyInvoice(db.Model):
    """One consolidated bill to the company for the approved sponsored items."""
    __tablename__ = 'company_invoice'
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    collection_id = db.Column(db.Integer, db.ForeignKey('collection.id'), nullable=False, index=True)
    submission_ids_json = db.Column(db.Text, nullable=False)

    subtotal = db.Column(db.Float, nullable=False)
    tax = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, nullable=False)

    payment_method = db.Column(db.String(50))   # stripe, cash, check, venmo, paypal
    payment_status = db.Column(db.String(20), default='unpaid')  # unpaid, paid, voided
    payment_intent_id = db.Column(db.String(200))
    paid_at = db.Column(db.DateTime)
    admin_notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    collection = db.relationship('Collection', backref=db.backref('company_invoices', lazy='dynamic'))

    @staticmethod
    def generate_invoice_number():
        return f"INV-{datetime.utcnow().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

    @property
    def submission_ids(self):
        try:
            return json.loads(self.submission_ids_json or '[]')
        except (TypeError, ValueError):
            return []

    def __repr__(self):
        return f'<CompanyInvoice {self.invoice_number}>'


class Organization(db.Model):
    """An umbrella group (school, club, business) that owns multiple Collections.

    e.g. "Rainbow Cheetahs" owns Basketball, Soccer, Volleyball, and Fan Wear
    collections. Shoppers land at /org/<slug> and pick their sport; organizers
    manage everything from /org/<slug>/manage.
    """
    __tablename__ = 'organization'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    logo_url = db.Column(db.String(500))
    cover_image = db.Column(db.String(500))
    # JSON: {"uploads": [paths added by the organizer], "hidden": [fan design ids they removed]}
    photo_config = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

    # Organizer dashboard access
    password_hash = db.Column(db.String(256))

    # Creator tracking
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    pending_organizer_email = db.Column(db.String(120))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sections = db.relationship(
        'OrgSection', backref='organization', lazy='dynamic',
        order_by='OrgSection.sort_order',
        cascade='all, delete-orphan',
    )
    created_by = db.relationship('User', backref='created_organizations')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return True
        return check_password_hash(self.password_hash, password)

    @property
    def share_url(self):
        return f'/org/{self.slug}'

    def __repr__(self):
        return f'<Organization {self.name}>'


class OrgSection(db.Model):
    """One tile on the Organization landing page — links to a Collection.

    e.g. label='Basketball', icon='🏀', collection=<basketball Collection>
    """
    __tablename__ = 'org_section'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey('organization.id'), nullable=False, index=True
    )
    collection_id = db.Column(
        db.Integer, db.ForeignKey('collection.id'), nullable=False
    )
    label = db.Column(db.String(100), nullable=False)   # "Basketball"
    icon = db.Column(db.String(10), default='🏷️')      # emoji
    sort_order = db.Column(db.Integer, default=0)

    collection = db.relationship('Collection', backref='org_sections')

    def __repr__(self):
        return f'<OrgSection {self.label}>'


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
    slug = db.Column(db.String(200), unique=True, nullable=True, index=True)
    
    # Detailed categorization
    category = db.Column(db.String(50))  # Tee, Hoodie, Sweatshirt, Tank, Long Sleeve, etc.
    age_group = db.Column(db.String(20))  # 'baby', 'toddler', 'youth', 'adult'
    fit_type = db.Column(db.String(30))  # 'Unisex', 'Men\'s', 'Women\'s', 'Fitted', etc.
    neck_style = db.Column(db.String(30))  # 'Crew Neck', 'V-Neck', 'Scoop Neck', 'Hooded', etc.
    sleeve_length = db.Column(db.String(30))  # 'Short Sleeve', 'Long Sleeve', 'Sleeveless', '3/4 Sleeve'
    # Manual family grouping override — lets admin link toddler/baby/youth styles that
    # don't share a style-number prefix with their adult counterpart (e.g. RS3321T → BC3001)
    family_key = db.Column(db.String(100), nullable=True, index=True)
    
    description = db.Column(db.Text)
    
    # Pricing
    base_price = db.Column(db.Float, nullable=False)
    wholesale_cost = db.Column(db.Float)
    
    # Availability
    is_active = db.Column(db.Boolean, default=True)

    # Merchandising: highlight popular / best-selling products
    is_customer_favorite = db.Column(db.Boolean, default=False)
    
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
    
    # Size specifications and fit guide
    size_chart = db.Column(db.Text)  # JSON: Size chart data from S&S
    fit_guide = db.Column(db.Text)  # Fit description (e.g., "Unisex sizing", "Runs small")
    fabric_details = db.Column(db.Text)  # Fabric composition and care
    spec_sheet_url = db.Column(db.String(500))  # PDF spec sheet from SanMar CDN
    # Softness merchandising (1=Everyday … 4=Ultra Soft); seeded by style number
    softness_rating = db.Column(db.Integer)  # 1–4
    fabric_summary = db.Column(db.String(80))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    order_items = db.relationship('OrderItem', backref='product', lazy='dynamic')
    color_variants = db.relationship('ProductColorVariant', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    
    SOFTNESS_LABELS = {
        1: 'Everyday',
        2: 'Soft',
        3: 'Super Soft',
        4: 'Ultra Soft',
    }
    PORT_COMPANY_TIEDYE_STYLES = {
        'PC144', 'PC145', 'PC146', 'PC146Y', 'PC147',
        'PC147LS', 'PC147Y', 'PC147YLS', 'LPC147V',
    }

    @property
    def softness_label(self):
        """Human label for softness_rating, or None if unset/invalid."""
        style = (self.style_number or '').strip().upper()
        if style in self.PORT_COMPANY_TIEDYE_STYLES:
            return 'Artisan Soft'
        try:
            rating = int(self.softness_rating) if self.softness_rating is not None else None
        except (TypeError, ValueError):
            return None
        return self.SOFTNESS_LABELS.get(rating)
    
    def __repr__(self):
        return f'<Product {self.style_number} - {self.name}>'


class ProductColorVariant(db.Model):
    """Color-specific mockup images and inventory for each product"""
    __tablename__ = 'product_color_variant'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    
    # Color info
    color_name = db.Column(db.String(100), nullable=False)
    color_hex = db.Column(db.String(7))       # Optional hex code for display e.g. #FFFFFF
    color_swatch_url = db.Column(db.String(500))  # SanMar CDN swatch image URL
    
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
    
    # Gallery: designs available for customers to use.
    # is_gallery == True means the design is PUBLISHED to the public gallery.
    # Admin uploads are published directly; customer submissions must be
    # approved first (see gallery_status below) before is_gallery is set True.
    is_gallery = db.Column(db.Boolean, default=False)
    title = db.Column(db.String(200))  # Display name for gallery

    # Public-gallery submission / moderation workflow
    # gallery_submitted: customer asked to share this design publicly
    gallery_submitted = db.Column(db.Boolean, default=False)
    # gallery_status: None (never submitted) | pending | approved | rejected | changes_requested
    gallery_status = db.Column(db.String(20))
    gallery_rejection_reason = db.Column(db.Text)  # internal note shown to admins/owner
    gallery_submitted_at = db.Column(db.DateTime)
    gallery_reviewed_at = db.Column(db.DateTime)
    gallery_reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Design organization
    folder = db.Column(db.String(100))  # primary category: custom_orders, evergreen, school, holiday, sports, etc.
    extra_categories = db.Column(db.Text)   # comma-separated additional folder tags, e.g. "kc,sports"
    sku = db.Column(db.String(50))  # SKU number
    
    # Soft-hide from admin Design Library without removing the customer's copy
    # in My Designs (same Design row / file).
    hidden_from_admin = db.Column(db.Boolean, default=False)

    # Color variants: child rows point at a main gallery design (parent).
    # Public gallery shows parents only; clicking opens color choices.
    parent_design_id = db.Column(db.Integer, db.ForeignKey('design.id'), nullable=True, index=True)
    variant_label = db.Column(db.String(80))  # e.g. "Navy", "White", "Glitter Red"

    # Metadata
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    design_fee = db.Column(db.Float, default=0)  # Custom design fee: 0, 4, or 20 when from "Have Us Recreate"

    # Master library record (automatic organization). All optional: older designs keep working untouched.
    ai_status = db.Column(db.String(20))        # pending | processing | done | needs_review | error
    ai_confidence = db.Column(db.Float)         # 0..1, how sure the automatic classification was
    ai_error = db.Column(db.Text)
    ai_processed_at = db.Column(db.DateTime)
    style = db.Column(db.String(60))            # e.g. Vintage, Minimal
    audience = db.Column(db.String(60))         # who it is for, e.g. Mom, Grandma
    keywords = db.Column(db.Text)               # extra searchable words
    ai_suggestions = db.Column(db.Text)         # JSON: what the automation was unsure about
    # Fingerprint (finds duplicates and color/wording versions; see utils/design_fingerprint.py)
    file_hash = db.Column(db.String(64), index=True)
    phash = db.Column(db.String(16))
    shape_hash = db.Column(db.String(64))
    art_text = db.Column(db.Text)               # the words on the artwork, when known
    palette = db.Column(db.Text)                # JSON: ink colors with family and share
    color_families = db.Column(db.String(120))  # e.g. black,red
    fingerprinted_at = db.Column(db.DateTime)
    ip_status = db.Column(db.String(20))        # review (check before publishing) | cleared
    ip_note = db.Column(db.Text)
    locked_fields = db.Column(db.Text)          # JSON list of fields you set by hand; automation never overwrites them
    modified_at = db.Column(db.DateTime)
    
    # Relationships
    user = db.relationship('User', backref='uploaded_designs', foreign_keys=[uploaded_by_user_id])
    order_items = db.relationship('OrderItem', backref='design', lazy='dynamic')
    color_variants = db.relationship(
        'Design',
        backref=db.backref('parent_design', remote_side=[id]),
        foreign_keys=[parent_design_id],
        lazy='dynamic',
    )
    
    tag_links = db.relationship('DesignTagLink', backref='design', lazy='dynamic',
                                cascade='all, delete-orphan')
    category_links = db.relationship('DesignCategoryLink', backref='design', lazy='dynamic',
                                     cascade='all, delete-orphan')
    corrections = db.relationship('DesignCorrection', backref='design', lazy='dynamic',
                                  cascade='all, delete-orphan')

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
    
    # Soft-delete: True = customer dismissed the request card (reference image stays in account)
    is_deleted = db.Column(db.Boolean, default=False, nullable=True)

    # Set once the customer confirmation and business notification have gone out,
    # so a refresh or a repeated submit cannot send the pair twice.
    emails_sent_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref='custom_design_requests')
    created_design = db.relationship('Design', foreign_keys=[created_design_id])
    
    def __repr__(self):
        return f'<CustomDesignRequest {self.id} by {self.user_id}>'


class Order(db.Model):
    """Customer order"""
    # One order per payment, enforced by the database: no path can ever make
    # two orders for the same PayPal payment or card charge.
    __table_args__ = (
        db.Index('uq_order_paypal_order_id', 'paypal_order_id', unique=True,
                 postgresql_where=db.text('paypal_order_id IS NOT NULL'),
                 sqlite_where=db.text('paypal_order_id IS NOT NULL')),
        db.Index('uq_order_payment_intent_id', 'payment_intent_id', unique=True,
                 postgresql_where=db.text('payment_intent_id IS NOT NULL'),
                 sqlite_where=db.text('payment_intent_id IS NOT NULL')),
    )
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

    # Group-order send-home (printed on packing labels)
    send_home_with_child = db.Column(db.Boolean, default=False)
    teacher_name = db.Column(db.String(120))
    occasion_note = db.Column(db.String(200))
    # Customer emails: when each one went out, so none is ever sent twice
    completed_at = db.Column(db.DateTime)
    ready_notified_at = db.Column(db.DateTime)
    completed_notified_at = db.Column(db.DateTime)
    review_email_sent_at = db.Column(db.DateTime)
    review_token = db.Column(db.String(40), index=True)
    child_grade = db.Column(db.String(40))
    child_name = db.Column(db.String(120))
    
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
    payment_method = db.Column(db.String(50))  # stripe, paypal, cash
    payment_status = db.Column(db.String(50), default='pending')  # pending, paid, failed, refunded
    payment_intent_id = db.Column(db.String(200))  # Stripe payment intent ID
    paypal_order_id = db.Column(db.String(200))  # PayPal order ID
    paid_at = db.Column(db.DateTime)
    amount_paid = db.Column(db.Float)  # 0 for cash-due family promo; card/PayPal = total
    promo_code = db.Column(db.String(50))  # e.g. AIRMATTRESS family at-cost
    
    # Order status
    status = db.Column(db.String(50), default='new')  # new, paid, in_production, ready, picked_up, shipped, completed, cancelled
    
    # Production workflow stage (maps to 5 stages)
    production_stage = db.Column(db.String(50))  # order_received, waiting_supplies, ready_to_press, pressed, packaged_ready
    
    # Order type & revenue tracking
    order_type = db.Column(db.String(20), default='retail')  # retail, wholesale, event
    due_date = db.Column(db.DateTime)
    cost_of_goods = db.Column(db.Float)  # Total COGS for this order
    profit = db.Column(db.Float)  # total - cost_of_goods
    # True once real supplier costs have been entered; stops the order page from
    # overwriting cost_of_goods/profit with the calculated estimate.
    cogs_is_actual = db.Column(db.Boolean, default=False)
    # Stripe / PayPal cut. Pulled from the processor once (actual); a standard-rate
    # estimate fills in until then. Profit = total - tax - fee - cost_of_goods.
    processing_fee = db.Column(db.Float)
    processing_fee_is_actual = db.Column(db.Boolean, default=False)
    fee_checked_at = db.Column(db.DateTime)  # last time the processor was asked for the fee
    # Unique so two concurrent submits of the same checkout cannot both create
    # an order. NULL is allowed many times over (admin-created orders have no
    # token), which both Postgres and SQLite permit under a unique constraint.
    checkout_token = db.Column(db.String(64), index=True, unique=True)
    confirmation_email_sent_at = db.Column(db.DateTime)
    is_refunded = db.Column(db.Boolean, default=False)
    refund_notes = db.Column(db.Text)
    refunded_cents = db.Column(db.BigInteger, default=0)      # total refunded so far, in cents (partial refunds too)
    refunded_at = db.Column(db.DateTime)                       # when the latest refund went out (UTC)
    refund_checked_at = db.Column(db.DateTime)                 # last time PayPal was asked about refunds
    tax_jurisdiction = db.Column(db.String(20))                # local, ks_shipped, out_of_state (where it was taxed)
    tax_rate_percent = db.Column(db.Float)                     # the rate actually charged, e.g. 9.5
    
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
    # Group-store lane snapshot: fan | uniform, plus home | away for uniforms.
    catalog_section = db.Column(db.String(20))
    uniform_kit = db.Column(db.String(20))
    # Which group store this shirt was ordered from. One checkout can hold shirts
    # from several stores of the same organization (Basketball + Volleyball + Fan
    # Wear). Empty on older orders: those belong to the order's own store.
    collection_id = db.Column(db.Integer, index=True)
    
    # Quantity and pricing
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    
    # Print specifications
    placement = db.Column(db.String(50))  # center_chest, left_chest, full_front, full_back, sleeve
    print_type = db.Column(db.String(50))  # DTF, screen_print, vinyl, sublimation, etc.
    design_file_name = db.Column(db.String(500))  # Design file name for production
    back_design_file_name = db.Column(db.String(500))  # Back design (name/number or image) for production
    back_design_meta = db.Column(db.Text)  # JSON: name/number/font/text_color/outline/outline_color for back name & number
    print_width = db.Column(db.Float)  # inches
    print_height = db.Column(db.Float)  # inches
    transfer_production = db.Column(db.Text)  # JSON snapshot from utils.print_sizes
    position_x = db.Column(db.Float)  # relative position
    position_y = db.Column(db.Float)  # relative position
    rotation = db.Column(db.Float, default=0.0)
    
    # Preview image
    proof_image = db.Column(db.String(500))  # Path to rendered front proof
    proof_back_image = db.Column(db.String(500))  # Path to rendered back mockup (customer-approved)
    
    # Notes
    notes = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @property
    def back_design_details(self):
        """Parsed back-design name/number/color metadata, or None."""
        if not self.back_design_meta:
            return None
        try:
            import json as _json
            return _json.loads(self.back_design_meta)
        except Exception:
            return None

    @property
    def transfer_production_details(self):
        """Parsed transfer production snapshot, or None."""
        if not self.transfer_production:
            return None
        try:
            import json as _json
            return _json.loads(self.transfer_production)
        except Exception:
            return None
    
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


class LedgerEntry(db.Model):
    """One money event, in whole cents. Rows are never edited or deleted: a correction is a new dated entry.

    The sign is the effect on the business: sales and sales tax collected are positive; refunds, fees, cost of
    goods, expenses and owner draws are negative. kc_date is the Kansas City calendar day, used for every report.
    """
    __tablename__ = 'ledger_entry'
    id = db.Column(db.Integer, primary_key=True)
    occurred_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)     # UTC
    kc_date = db.Column(db.Date, nullable=False, index=True)                          # Kansas City day
    entry_type = db.Column(db.String(24), nullable=False, index=True)
    category = db.Column(db.String(60), index=True)
    amount_cents = db.Column(db.BigInteger, nullable=False)
    source_key = db.Column(db.String(40), index=True)        # order:12, invoice:3, legacy:7, expense:4, manual
    pay_source = db.Column(db.String(20))                    # stripe, paypal, cash, check, venmo, bank, other
    channel = db.Column(db.String(20), index=True)           # retail, group, company, invoice, cash
    collection_id = db.Column(db.Integer, db.ForeignKey('collection.id'))
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('manual_invoice.id'), index=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), index=True)
    vendor = db.Column(db.String(120))
    note = db.Column(db.Text)
    is_estimate = db.Column(db.Boolean, default=False)
    jurisdiction = db.Column(db.String(20), index=True)      # where the sale was taxed (sales tax report)
    taxable = db.Column(db.Boolean)                          # whether tax was charged on this sale
    tax_rate_percent = db.Column(db.Float)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship('Order', foreign_keys=[order_id])
    invoice = db.relationship('ManualInvoice', foreign_keys=[invoice_id])


class Payout(db.Model):
    """Money the processor sent (or is sending) to the bank. Used to tie sales and fees to the deposit."""
    __tablename__ = 'payout'
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(12), nullable=False, default='stripe')
    provider_id = db.Column(db.String(80), nullable=False, unique=True)
    amount_cents = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(6), default='usd')
    status = db.Column(db.String(20), index=True)             # pending, in_transit, paid, failed, canceled
    arrival_date = db.Column(db.Date)                          # the Kansas City day it lands in the bank
    reconciled_at = db.Column(db.DateTime)
    reconcile_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryCount(db.Model):
    """A year-end count of what is on the shelf, valued at cost. Once locked it never changes."""
    __tablename__ = 'inventory_count'
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, unique=True)
    as_of = db.Column(db.Date, nullable=False)                   # the Kansas City day it counts (Dec 31 for a past year)
    note = db.Column(db.Text)
    locked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lines = db.relationship('InventoryCountLine', backref='count', order_by='InventoryCountLine.id',
                            cascade='all, delete-orphan')


class InventoryCountLine(db.Model):
    __tablename__ = 'inventory_count_line'
    id = db.Column(db.Integer, primary_key=True)
    count_id = db.Column(db.Integer, db.ForeignKey('inventory_count.id'), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False, default='other')     # blanks, transfers, supplies, other
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    unit_cost_cents = db.Column(db.BigInteger, nullable=False, default=0)

    @property
    def value_cents(self):
        return int(self.quantity or 0) * int(self.unit_cost_cents or 0)


class MileageTrip(db.Model):
    """One business trip. The CPA applies the standard mileage rate to the total."""
    __tablename__ = 'mileage_trip'
    id = db.Column(db.Integer, primary_key=True)
    trip_date = db.Column(db.Date, nullable=False, index=True)           # Kansas City day
    start = db.Column(db.String(120))
    destination = db.Column(db.String(120))
    purpose = db.Column(db.String(200))
    miles_tenths = db.Column(db.Integer, nullable=False)                 # 12.5 miles is stored as 125
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MileageFavorite(db.Model):
    """A trip you make again and again (supplier pickup, post office), logged with one tap."""
    __tablename__ = 'mileage_favorite'
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(80), nullable=False)
    start = db.Column(db.String(120))
    destination = db.Column(db.String(120))
    purpose = db.Column(db.String(200))
    miles_tenths = db.Column(db.Integer, nullable=False)


class Expense(db.Model):
    """A business expense with its receipt. Its ledger entry is written alongside; voiding adds a reversing entry."""
    __tablename__ = 'expense'
    id = db.Column(db.Integer, primary_key=True)
    expense_date = db.Column(db.Date, nullable=False, index=True)                     # Kansas City day
    vendor = db.Column(db.String(120))
    amount_cents = db.Column(db.BigInteger, nullable=False)
    category = db.Column(db.String(60), nullable=False, index=True)
    payment_method = db.Column(db.String(30))
    note = db.Column(db.Text)
    receipt_url = db.Column(db.String(500))
    is_equipment = db.Column(db.Boolean, default=False)          # heat press, printer and similar (counted as supplies)
    recurring_id = db.Column(db.Integer, db.ForeignKey('recurring_expense.id'), index=True)   # made by a monthly rule
    voided_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SystemSettings(db.Model):
    """System-wide settings"""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<SystemSettings {self.key}>'


class Review(db.Model):
    """A customer's words (and optional photos) about an order. Shown on the site only once approved."""
    __tablename__ = 'review'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), index=True)
    name = db.Column(db.String(80), nullable=False)
    body = db.Column(db.Text)
    photos = db.Column(db.Text)                       # JSON list of image URLs
    photos_ok = db.Column(db.Boolean, default=False)  # the customer said we may show their photos
    status = db.Column(db.String(12), default='pending', index=True)   # pending | approved | hidden
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship('Order', backref=db.backref('reviews', lazy='dynamic'))

    def photo_urls(self):
        import json
        try:
            return [u for u in json.loads(self.photos or '[]') if isinstance(u, str)]
        except Exception:
            return []


class Affirmation(db.Model):
    """Daily affirmations shown on the shop page, one per day cycling through the active list."""
    __tablename__ = 'affirmation'

    id         = db.Column(db.Integer, primary_key=True)
    text       = db.Column(db.Text, nullable=False)
    is_active  = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Affirmation {self.id}: {self.text[:40]}>'


class SiteError(db.Model):
    """Customer-facing 500s, keyed by the reference ID shown on the error page."""
    __tablename__ = 'site_error'

    id = db.Column(db.Integer, primary_key=True)
    error_id = db.Column(db.String(16), unique=True, nullable=False, index=True)
    path = db.Column(db.String(500))
    method = db.Column(db.String(10))
    query_string = db.Column(db.String(500))
    referrer = db.Column(db.String(500))
    user_agent = db.Column(db.String(500))
    user_id = db.Column(db.Integer)
    message = db.Column(db.Text)
    traceback = db.Column(db.Text)
    notified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<SiteError {self.error_id} {self.path}>'


class AdminNotification(db.Model):
    """Inbound inbox for contact-form messages and design requests.

    Orders stay on the dashboard workflow and are never written here.
    """
    __tablename__ = 'admin_notification'

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    preview = db.Column(db.String(300))
    body = db.Column(db.Text)
    from_name = db.Column(db.String(200))
    from_email = db.Column(db.String(120))
    url = db.Column(db.String(300))
    related_id = db.Column(db.Integer, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<AdminNotification {self.kind} {self.id}>'


class PaymentCapture(db.Model):
    """Every PayPal payment the site captures, saved the moment money is taken.

    Lives in the database (not the browser session) so a paid checkout can
    always be matched to an order, recovered, or flagged to the admin.
    """
    __tablename__ = 'payment_capture'
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(20), nullable=False, default='paypal')
    provider_ref = db.Column(db.String(200), nullable=False, unique=True, index=True)
    amount = db.Column(db.Float)
    payer_name = db.Column(db.String(200))
    payer_email = db.Column(db.String(200))
    customer_json = db.Column(db.Text)  # name/email/phone/shipping typed at checkout
    cart_json = db.Column(db.Text)      # cart at the moment of payment
    collection_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True, index=True)
    failure_reason = db.Column(db.Text)
    alert_sent_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)  # admin handled it outside the site
    processing_at = db.Column(db.DateTime)  # claim while an order is being created from it
    awaiting_collection = db.Column(db.Boolean, default=False)  # approved in PayPal, money not collected
    checked_at = db.Column(db.DateTime)     # last time a card payment's status was checked
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    order = db.relationship('Order', foreign_keys=[order_id])

    def __repr__(self):
        return f'<PaymentCapture {self.provider} {self.provider_ref}>'


class ManualInvoice(db.Model):
    """An invoice or receipt Kayleigh writes by hand (orders taken directly, any brand).

    Deliberately NOT an Order: it never appears in production queues, blanks or
    DTF lists. It exists to be printed and kept on file.
    """
    __tablename__ = 'manual_invoice'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), unique=True, nullable=False, index=True)   # INV-2026-0001
    kind = db.Column(db.String(10), default='auto')       # auto | invoice | receipt
    customer_name = db.Column(db.String(200))
    company = db.Column(db.String(200))
    attn = db.Column(db.String(200))
    email = db.Column(db.String(200))
    phone = db.Column(db.String(40))
    address = db.Column(db.Text)
    po = db.Column(db.String(80))
    note = db.Column(db.Text)
    items_json = db.Column(db.Text, nullable=False, default='[]')    # [{description, qty, unit}]
    tax_rate = db.Column(db.Float, default=0.0)           # percent, e.g. 9.5
    shipping = db.Column(db.Float, default=0.0)
    discount = db.Column(db.Float, default=0.0)
    amount_paid = db.Column(db.Float, default=0.0)
    payment_method = db.Column(db.String(40))             # Venmo, Cash, Check, Card, Other
    # Pay online: a private link the customer can open to pay the balance by card.
    pay_token = db.Column(db.String(64), unique=True, index=True)   # None = link is off
    payment_intent_id = db.Column(db.String(200), index=True)       # the Stripe payment being collected
    card_paid_intent_id = db.Column(db.String(200))                  # the last one that was applied
    pay_link_sent_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)                    # when money first came in (cash basis books)
    refunded_cents = db.Column(db.BigInteger, default=0)
    refunded_at = db.Column(db.DateTime)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ManualInvoice {self.number}>'


class DesignTag(db.Model):
    """One standard tag (Mom, Football, Vintage...). Synonyms and related tags make search forgiving."""
    __tablename__ = 'design_tag'
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, nullable=False, index=True)
    label = db.Column(db.String(80), nullable=False)
    tag_type = db.Column(db.String(20), nullable=False, default='theme', index=True)
    synonyms = db.Column(db.Text)       # JSON list of other words that mean this tag
    implies = db.Column(db.Text)        # JSON list of tag slugs this tag also means ("football-mom")
    related = db.Column(db.Text)        # JSON list of tag slugs searched together at lower priority
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DesignTag {self.slug}>'


class DesignTagLink(db.Model):
    """A tag on a design. source 'manual' (you) always wins over 'auto'; locked links are never removed."""
    __tablename__ = 'design_tag_link'
    __table_args__ = (db.UniqueConstraint('design_id', 'tag_id', name='uq_design_tag'),)
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey('design.id', ondelete='CASCADE'), nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('design_tag.id', ondelete='CASCADE'), nullable=False, index=True)
    source = db.Column(db.String(10), default='auto')
    confidence = db.Column(db.Float)
    locked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tag = db.relationship('DesignTag')


class DesignCategoryLink(db.Model):
    """A design's place in a gallery collection (and optionally one of its subcategories)."""
    __tablename__ = 'design_category_link'
    __table_args__ = (db.UniqueConstraint('design_id', 'category_key', 'subcategory_key', name='uq_design_category'),)
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey('design.id', ondelete='CASCADE'), nullable=False, index=True)
    category_key = db.Column(db.String(40), nullable=False, index=True)
    subcategory_key = db.Column(db.String(60))
    is_primary = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(10), default='auto')       # auto | manual | legacy
    confidence = db.Column(db.Float)
    locked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DesignCorrection(db.Model):
    """Every time you fix something automation set: what it was, what you made it, and whether it is locked."""
    __tablename__ = 'design_correction'
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey('design.id', ondelete='CASCADE'), nullable=False, index=True)
    field = db.Column(db.String(40), nullable=False)        # title | colors | tag | category | ...
    original_value = db.Column(db.Text)
    corrected_value = db.Column(db.Text)
    correction_type = db.Column(db.String(30))              # renamed | wrong_category | missing_category | wrong_color | tag_removed | ...
    locked = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class DesignProposal(db.Model):
    """What the organizer suggests for one existing design. Nothing changes until you apply it; applied ones can be undone."""
    __tablename__ = 'design_proposal'
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey('design.id', ondelete='CASCADE'), nullable=False, index=True)
    batch_id = db.Column(db.String(20), index=True)
    mode = db.Column(db.String(10), default='smart')        # smart (reads the artwork) | name (free, name only)
    status = db.Column(db.String(12), default='queued', index=True)   # queued | processing | ready | applied | skipped | undone | error
    result_json = db.Column(db.Text)                        # the checked suggestion
    confidence = db.Column(db.Float)
    needs_attention = db.Column(db.Boolean, default=False)
    error = db.Column(db.Text)
    undo_json = db.Column(db.Text)                          # exactly what applying created or changed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)
    applied_at = db.Column(db.DateTime)

    design = db.relationship('Design', backref=db.backref('proposals', lazy='dynamic', cascade='all, delete-orphan'))


class DesignRelation(db.Model):
    """A link between two designs. Suggested by the system, then confirmed or dismissed by you. Never merges anything."""
    __tablename__ = 'design_relation'
    __table_args__ = (db.UniqueConstraint('design_id', 'related_design_id', 'relation_type', name='uq_design_relation'),)
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(db.Integer, db.ForeignKey('design.id', ondelete='CASCADE'), nullable=False, index=True)
    related_design_id = db.Column(db.Integer, db.ForeignKey('design.id', ondelete='CASCADE'), nullable=False, index=True)
    relation_type = db.Column(db.String(24), nullable=False)    # exact_duplicate | color_variation | wording_variation | matching_set
    status = db.Column(db.String(12), default='suggested', index=True)   # suggested | confirmed | dismissed
    score = db.Column(db.Float)
    reason = db.Column(db.String(300))
    source = db.Column(db.String(10), default='auto')           # auto | manual
    action = db.Column(db.String(12))                           # what confirming did: grouped | hidden (so it can be undone)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime)

    design = db.relationship('Design', foreign_keys=[design_id])
    related = db.relationship('Design', foreign_keys=[related_design_id])


class RecurringExpense(db.Model):
    """A bill that comes every month (software, insurance, a storage unit). One real Expense is made each month."""
    __tablename__ = 'recurring_expense'
    id = db.Column(db.Integer, primary_key=True)
    vendor = db.Column(db.String(120), nullable=False)
    amount_cents = db.Column(db.BigInteger, nullable=False)
    category = db.Column(db.String(60), nullable=False)
    payment_method = db.Column(db.String(30))
    note = db.Column(db.Text)
    day_of_month = db.Column(db.Integer, nullable=False, default=1)       # 1 to 28
    start_date = db.Column(db.Date, nullable=False)                      # the first month it applies to
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
