"""Complete database reset with new schema"""
import os
import sys

# Remove cache
if os.path.exists('__pycache__'):
    import shutil
    shutil.rmtree('__pycache__', ignore_errors=True)
if os.path.exists('routes/__pycache__'):
    import shutil
    shutil.rmtree('routes/__pycache__', ignore_errors=True)

# Remove old database
if os.path.exists('apparel.db'):
    os.remove('apparel.db')
    print('[+] Removed old database')

# Now import fresh
from app import create_app
from models import db, User, Product
import json

app = create_app()

with app.app_context():
    # Create all tables
    db.create_all()
    print('[+] Created new database with updated schema')
    
    # Verify Product table has new columns
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('product')]
    print(f'[+] Product columns: {", ".join(columns)}')
    
    if 'brand' in columns and 'api_data' in columns:
        print('[+] New columns present!')
    else:
        print('[!] Warning: New columns missing')
        sys.exit(1)
    
    # Create admin user
    admin = User(
        email='admin@kbapparel.com',
        first_name='Admin',
        last_name='User',
        is_admin=True
    )
    admin.set_password('admin123')
    db.session.add(admin)
    print('[+] Created admin user')
    
    # Add sample products
    sample_products = [
        {
            "style_number": "3001",
            "name": "Bella+Canvas Unisex Jersey Tee",
            "category": "Tee",
            "description": "The ultimate in comfort and style. Pre-shrunk 100% combed ring-spun cotton.",
            "base_price": 25.00,
            "wholesale_cost": 8.50,
            "available_sizes": json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Red", "Heather Gray", "Royal Blue"]),
            "brand": "Bella+Canvas",
            "is_active": True
        },
        {
            "style_number": "3719",
            "name": "Bella+Canvas Unisex Sponge Fleece Pullover Hoodie",
            "category": "Hoodie",
            "description": "Cozy sponge fleece fabric with retail fit.",
            "base_price": 45.00,
            "wholesale_cost": 18.00,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["Black", "Navy", "Heather Gray", "Maroon"]),
            "brand": "Bella+Canvas",
            "is_active": True
        },
        {
            "style_number": "8800",
            "name": "Bella+Canvas Unisex Crewneck Sweatshirt",
            "category": "Crew",
            "description": "Classic crew neck sweatshirt with retail fit.",
            "base_price": 38.00,
            "wholesale_cost": 14.50,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
            "brand": "Bella+Canvas",
            "is_active": True
        },
        {
            "style_number": "3501",
            "name": "Bella+Canvas Unisex Jersey Long Sleeve Tee",
            "category": "Tee",
            "description": "Long sleeve version of our bestselling tee.",
            "base_price": 28.00,
            "wholesale_cost": 10.00,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
            "brand": "Bella+Canvas",
            "is_active": True
        },
        {
            "style_number": "6004",
            "name": "Bella+Canvas Unisex Jersey Tank",
            "category": "Tank",
            "description": "Relaxed fit tank with side seams.",
            "base_price": 22.00,
            "wholesale_cost": 7.50,
            "available_sizes": json.dumps(["S", "M", "L", "XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
            "brand": "Bella+Canvas",
            "is_active": True
        }
    ]
    
    for p_data in sample_products:
        product = Product(**p_data)
        db.session.add(product)
        print(f'[+] Added: {p_data["style_number"]} - {p_data["name"]}')
    
    db.session.commit()
    
    print('\n==== Database Reset Complete! ====')
    print('Admin: admin@kbapparel.com / admin123')
    print('Products: 5 sample Bella+Canvas products added')
    print('\nRestart Flask server:')
    print('.\\venv\\Scripts\\python app.py')
