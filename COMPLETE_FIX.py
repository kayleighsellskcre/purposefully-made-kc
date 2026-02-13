"""
Complete fix - Creates database with correct schema and adds data
"""
import os
import sys
import json

# Clean up cache FIRST
for root, dirs, files in os.walk('.'):
    if '__pycache__' in dirs:
        import shutil
        cache_path = os.path.join(root, '__pycache__')
        shutil.rmtree(cache_path, ignore_errors=True)
        print(f'Cleared cache: {cache_path}')

# Remove old database
if os.path.exists('apparel.db'):
    os.remove('apparel.db')
    print('Removed old database')

# Set environment to not write bytecode
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True

# Now import fresh
print('Creating fresh database...')
from app import create_app
from models import db, User, Product

app = create_app()

with app.app_context():
    # Create tables
    db.create_all()
    print('[+] Created database tables')
    
    # Verify Product table structure
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('product')]
    print(f'[+] Product columns: {len(columns)} columns')
    
    # Create admin
    admin = User(
        email='admin@kbapparel.com',
        first_name='Admin',
        last_name='User',
        is_admin=True
    )
    admin.set_password('admin123')
    db.session.add(admin)
    print('[+] Created admin user')
    
    # Add 5 sample products
    products = [
        {
            "style_number": "3001", "name": "Bella+Canvas Unisex Jersey Tee",
            "category": "Tee", "description": "Classic unisex tee",
            "base_price": 25.00, "wholesale_cost": 8.50,
            "available_sizes": json.dumps(["XS","S","M","L","XL","2XL","3XL"]),
            "available_colors": json.dumps(["White","Black","Navy","Red"]),
            "is_active": True
        },
        {
            "style_number": "3719", "name": "Bella+Canvas Pullover Hoodie",
            "category": "Hoodie", "description": "Cozy pullover hoodie",
            "base_price": 45.00, "wholesale_cost": 18.00,
            "available_sizes": json.dumps(["S","M","L","XL","2XL"]),
            "available_colors": json.dumps(["Black","Navy","Gray"]),
            "is_active": True
        },
        {
            "style_number": "8800", "name": "Bella+Canvas Crewneck Sweatshirt",
            "category": "Crew", "description": "Classic crewneck",
            "base_price": 38.00, "wholesale_cost": 14.50,
            "available_sizes": json.dumps(["S","M","L","XL","2XL"]),
            "available_colors": json.dumps(["White","Black","Navy"]),
            "is_active": True
        },
        {
            "style_number": "3501", "name": "Bella+Canvas Long Sleeve Tee",
            "category": "Tee", "description": "Long sleeve comfort",
            "base_price": 28.00, "wholesale_cost": 10.00,
            "available_sizes": json.dumps(["S","M","L","XL"]),
            "available_colors": json.dumps(["White","Black"]),
            "is_active": True
        },
        {
            "style_number": "6004", "name": "Bella+Canvas Jersey Tank",
            "category": "Tank", "description": "Relaxed fit tank",
            "base_price": 22.00, "wholesale_cost": 7.50,
            "available_sizes": json.dumps(["S","M","L","XL"]),
            "available_colors": json.dumps(["White","Black"]),
            "is_active": True
        }
    ]
    
    for p in products:
        product = Product(**p)
        db.session.add(product)
        print(f'[+] Added: {p["style_number"]}')
    
    db.session.commit()
    
    print('\n=== DATABASE READY ===')
    print('Admin: admin@kbapparel.com / admin123')
    print('Products: 5 items')
    print('\nStart server: .\\venv\\Scripts\\python app.py')
    print('Visit: http://localhost:5000')
