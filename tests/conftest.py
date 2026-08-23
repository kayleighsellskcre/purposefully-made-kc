"""Shared pytest fixtures.

Safety note: the environment overrides below run at import time, before any
project module is imported. `app.py` calls `create_app()` at module scope, so
without this the mere act of importing it would connect to the production
Railway database. python-dotenv does not override variables that already
exist, so setting them here wins over `.env`.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SESSION_COOKIE_SECURE'] = 'false'
os.environ['PREFERRED_URL_SCHEME'] = 'http'
# app.py calls create_app() at module scope, so merely importing it builds a
# second app under the production Config. Left alone, that one starts
# APScheduler and fires the startup inventory sync mid-test-run.
os.environ['SCHEDULER_ENABLED'] = 'false'
os.environ['ADMIN_EMAIL'] = 'admin-test@example.com'
os.environ['ADMIN_BASE_URL'] = 'https://purposefullymadekc.com'
# Blank every outbound-service credential so nothing can reach a real provider.
for _var in (
    'MAIL_SERVER', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER',
    'STRIPE_SECRET_KEY', 'STRIPE_PUBLIC_KEY', 'STRIPE_WEBHOOK_SECRET',
    'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER',
    'R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME',
    'R2_PUBLIC_URL', 'SSACTIVEWEAR_API_KEY', 'SSACTIVEWEAR_ACCOUNT_NUMBER',
    'SANMAR_USERNAME', 'SANMAR_PASSWORD', 'ADMIN_PHONE_CARRIER',
):
    os.environ.pop(_var, None)

import json  # noqa: E402
import pytest  # noqa: E402

from config import TestConfig  # noqa: E402
from models import (  # noqa: E402
    db, User, Product, ProductColorVariant, Design, Collection,
)

ADMIN_EMAIL = 'admin-test@example.com'
CUSTOMER_EMAIL = 'customer-test@example.com'
OTHER_EMAIL = 'other-test@example.com'
PASSWORD = 'TestPassw0rd!23'

SIZES = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']


@pytest.fixture(scope='session')
def app():
    from app import create_app
    application = create_app(TestConfig)
    with application.app_context():
        db.drop_all()
        db.create_all()
    yield application


@pytest.fixture()
def _clean_db(app):
    """Give every test a fresh schema so row IDs and state never leak between tests."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()


@pytest.fixture()
def seed(app, _clean_db):
    """Representative catalog + accounts. Returns a dict of primary keys.

    Prices are deliberately round numbers so expected totals in the pricing
    tests are obvious by inspection.
    """
    with app.app_context():
        admin = User(
            email=ADMIN_EMAIL, first_name='Site', last_name='Owner', is_admin=True,
        )
        admin.set_password(PASSWORD)
        customer = User(
            email=CUSTOMER_EMAIL, first_name='Casey', last_name='Customer',
            phone='816-555-0100',
        )
        customer.set_password(PASSWORD)
        other = User(email=OTHER_EMAIL, first_name='Otto', last_name='Other')
        other.set_password(PASSWORD)
        db.session.add_all([admin, customer, other])
        db.session.flush()

        tee = Product(
            style_number='3001', name='Unisex Jersey Short Sleeve Tee',
            category='Tee', age_group='adult', base_price=30.00,
            wholesale_cost=6.00, is_active=True,
            available_sizes=json.dumps(SIZES),
            available_colors=json.dumps(['Black', 'White', 'Navy']),
        )
        hoodie = Product(
            style_number='18500', name='Heavy Blend Hooded Sweatshirt',
            category='Hoodie', age_group='adult', base_price=45.00,
            wholesale_cost=14.00, is_active=True,
            available_sizes=json.dumps(SIZES),
            available_colors=json.dumps(['Black', 'Sport Grey']),
        )
        youth = Product(
            style_number='3001Y', name='Youth Jersey Short Sleeve Tee',
            category='Tee', age_group='youth', base_price=24.00,
            wholesale_cost=5.00, is_active=True,
            available_sizes=json.dumps(['YS', 'YM', 'YL', 'XL', '2XL']),
            available_colors=json.dumps(['Black', 'White']),
        )
        inactive = Product(
            style_number='0000', name='Retired Style', category='Tee',
            age_group='adult', base_price=20.00, is_active=False,
            available_sizes=json.dumps(['M']),
            available_colors=json.dumps(['Black']),
        )
        db.session.add_all([tee, hoodie, youth, inactive])
        db.session.flush()

        # One variant per product carries stock for every size.
        stocked = {s: 50 for s in SIZES}
        db.session.add_all([
            ProductColorVariant(
                product_id=tee.id, color_name='Black', color_hex='#000000',
                size_inventory=json.dumps(stocked),
            ),
            ProductColorVariant(
                product_id=tee.id, color_name='White', color_hex='#ffffff',
                size_inventory=json.dumps(stocked),
            ),
            ProductColorVariant(
                product_id=hoodie.id, color_name='Black', color_hex='#000000',
                size_inventory=json.dumps(stocked),
            ),
            ProductColorVariant(
                product_id=youth.id, color_name='Black', color_hex='#000000',
                size_inventory=json.dumps({'YS': 10, 'YM': 10, 'YL': 10, 'XL': 10, '2XL': 10}),
            ),
        ])

        free_design = Design(
            filename='gallery-logo.png', file_path='uploads/designs/gallery-logo.png',
            title='Gallery Logo', is_gallery=True, design_fee=0,
            uploaded_by_user_id=admin.id,
        )
        # $4 = "lots of changes", $20 = "from scratch" (see CustomDesignRequest.design_fee)
        fee_4_design = Design(
            filename='recreate-4.png', file_path='uploads/designs/recreate-4.png',
            title='Recreated Art', design_fee=4.0, uploaded_by_user_id=customer.id,
        )
        fee_20_design = Design(
            filename='recreate-20.png', file_path='uploads/designs/recreate-20.png',
            title='From Scratch Art', design_fee=20.0, uploaded_by_user_id=customer.id,
        )
        db.session.add_all([free_design, fee_4_design, fee_20_design])
        db.session.flush()

        group = Collection(
            name='Test Elementary Spirit Wear', slug='test-elementary',
            is_active=True, shipping_enabled=True, show_in_directory=True,
            created_by_user_id=admin.id,
        )
        group.products.append(tee)
        db.session.add(group)

        db.session.commit()

        ids = {
            'admin_id': admin.id,
            'customer_id': customer.id,
            'other_id': other.id,
            'tee_id': tee.id,
            'hoodie_id': hoodie.id,
            'youth_id': youth.id,
            'inactive_id': inactive.id,
            'free_design_id': free_design.id,
            'fee_4_design_id': fee_4_design.id,
            'fee_20_design_id': fee_20_design.id,
            'collection_id': group.id,
            'collection_slug': group.slug,
            'tee_price': 30.00,
            'hoodie_price': 45.00,
            'youth_price': 24.00,
        }
    return ids


@pytest.fixture()
def client(app, seed):
    with app.test_client() as c:
        yield c


@pytest.fixture()
def guest(app, seed):
    """A client with no session at all, for auth-boundary tests."""
    with app.test_client() as c:
        yield c


def _login(client, email, password=PASSWORD):
    return client.post(
        '/auth/login',
        data={'email': email, 'password': password},
        follow_redirects=True,
    )


@pytest.fixture()
def customer_client(client):
    resp = _login(client, CUSTOMER_EMAIL)
    assert resp.status_code == 200, 'customer login failed'
    return client


@pytest.fixture()
def admin_client(client):
    resp = _login(client, ADMIN_EMAIL)
    assert resp.status_code == 200, 'admin login failed'
    return client


@pytest.fixture()
def login():
    """Log an arbitrary email into a given client."""
    return _login


@pytest.fixture()
def outbox(app):
    """Capture every message Flask-Mail would have sent."""
    from app import mail
    with mail.record_messages() as messages:
        yield messages
