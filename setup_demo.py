"""Quick setup script to create admin user and sample products"""
from app import create_app
from models import db, User, Product
import json

app = create_app()

with app.app_context():
    # Create admin user
    admin = User.query.filter_by(email='admin@kbapparel.com').first()
    if not admin:
        admin = User(
            email='admin@kbapparel.com',
            first_name='Admin',
            last_name='User',
            is_admin=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        print('[+] Admin user created: admin@kbapparel.com / admin123')
    else:
        print('Admin user already exists')
    
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
            "is_active": True
        },
        {
            "style_number": "3719",
            "name": "Bella+Canvas Unisex Sponge Fleece Pullover Hoodie",
            "category": "Hoodie",
            "description": "Cozy sponge fleece fabric with retail fit. Side-seamed construction.",
            "base_price": 45.00,
            "wholesale_cost": 18.00,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["Black", "Navy", "Heather Gray", "Maroon"]),
            "is_active": True
        },
        {
            "style_number": "8800",
            "name": "Bella+Canvas Unisex Crewneck Sweatshirt",
            "category": "Crew",
            "description": "Classic crew neck sweatshirt with retail fit. Side-seamed.",
            "base_price": 38.00,
            "wholesale_cost": 14.50,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
            "is_active": True
        },
        {
            "style_number": "3501",
            "name": "Bella+Canvas Unisex Jersey Long Sleeve Tee",
            "category": "Tee",
            "description": "Long sleeve version of our bestselling tee. Pre-shrunk 100% combed ring-spun cotton.",
            "base_price": 28.00,
            "wholesale_cost": 10.00,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
            "is_active": True
        },
        {
            "style_number": "6004",
            "name": "Bella+Canvas Unisex Jersey Tank",
            "category": "Tank",
            "description": "Relaxed fit tank with side seams. 100% combed and ring-spun cotton.",
            "base_price": 22.00,
            "wholesale_cost": 7.50,
            "available_sizes": json.dumps(["S", "M", "L", "XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
            "is_active": True
        }
    ]
    
    for p_data in sample_products:
        existing = Product.query.filter_by(style_number=p_data["style_number"]).first()
        if not existing:
            product = Product(**p_data)
            db.session.add(product)
            print(f'[+] Added product: {p_data["style_number"]} - {p_data["name"]}')
    
    db.session.commit()
    print('\n=== Setup Complete! ===')
    print('Admin login: admin@kbapparel.com / admin123')
    print('Run: python app.py')
    print('Visit: http://localhost:5000')
