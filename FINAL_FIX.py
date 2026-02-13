"""
Final fix - Drop all tables and recreate with correct schema
"""
import os
import sys

# Remove database file completely
if os.path.exists('apparel.db'):
    os.remove('apparel.db')
    print('Deleted old database file')

# Set environment
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True

from app import create_app
from models import db, User, Product
import json

app = create_app()

with app.app_context():
    # Drop ALL tables first (important!)
    db.drop_all()
    print('[+] Dropped all tables')
    
    # Now create fresh tables with current schema
    db.create_all()
    print('[+] Created all tables with new schema')
    
    # Verify
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('product')]
    print(f'[+] Product table has {len(columns)} columns:')
    print(f'    {", ".join(columns)}')
    
    if 'brand' not in columns or 'api_data' not in columns:
        print('\n[ERROR] Still missing columns!')
        print('This is a critical issue - please report')
        sys.exit(1)
    
    print('\n[SUCCESS] New columns present!')
    
    # Add admin
    admin = User(
        email='admin@kbapparel.com',
        first_name='Admin',
        last_name='User',
        is_admin=True
    )
    admin.set_password('admin123')
    db.session.add(admin)
    print('[+] Added admin user')
    
    # Add products WITHOUT brand/api_data first to test
    products = [
        Product(
            style_number="3001",
            name="Bella+Canvas Unisex Jersey Tee",
            category="Tee",
            description="Classic unisex tee",
            base_price=25.00,
            wholesale_cost=8.50,
            available_sizes=json.dumps(["XS","S","M","L","XL","2XL"]),
            available_colors=json.dumps(["White","Black","Navy","Red"]),
            is_active=True
        ),
        Product(
            style_number="3719",
            name="Bella+Canvas Pullover Hoodie",
            category="Hoodie",
            description="Cozy pullover",
            base_price=45.00,
            wholesale_cost=18.00,
            available_sizes=json.dumps(["S","M","L","XL"]),
            available_colors=json.dumps(["Black","Navy"]),
            is_active=True
        ),
        Product(
            style_number="8800",
            name="Bella+Canvas Crewneck Sweatshirt",
            category="Crew",
            description="Classic crewneck",
            base_price=38.00,
            wholesale_cost=14.50,
            available_sizes=json.dumps(["S","M","L","XL"]),
            available_colors=json.dumps(["White","Black"]),
            is_active=True
        ),
        Product(
            style_number="3501",
            name="Bella+Canvas Long Sleeve Tee",
            category="Tee",
            description="Long sleeve",
            base_price=28.00,
            wholesale_cost=10.00,
            available_sizes=json.dumps(["S","M","L"]),
            available_colors=json.dumps(["White","Black"]),
            is_active=True
        ),
        Product(
            style_number="6004",
            name="Bella+Canvas Jersey Tank",
            category="Tank",
            description="Relaxed tank",
            base_price=22.00,
            wholesale_cost=7.50,
            available_sizes=json.dumps(["S","M","L"]),
            available_colors=json.dumps(["White","Black"]),
            is_active=True
        )
    ]
    
    for p in products:
        db.session.add(p)
        print(f'[+] Added: {p.style_number}')
    
    db.session.commit()
    print('\n==== DATABASE READY! ====')
    print('Admin: admin@kbapparel.com / admin123')
    print('Products: 5 items')
    print('\nYou can now:')
    print('1. Start server: .\\venv\\Scripts\\python app.py')
    print('2. Visit: http://localhost:5000')
    print('3. Login to admin and sync from S&S API')
