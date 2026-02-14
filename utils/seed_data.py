"""
Seed demo products when the database is empty (e.g. after deploy).
Used at app startup and when the shop is visited with no products.
"""
import json
from models import db, Product

DEMO_PRODUCTS = [
    {"style_number": "3001", "name": "Bella+Canvas Unisex Jersey Tee", "category": "Tee",
     "description": "Pre-shrunk 100% combed ring-spun cotton.", "base_price": 25.00,
     "available_sizes": json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL"]),
     "available_colors": json.dumps(["White", "Black", "Navy", "Red", "Heather Gray", "Royal Blue", "Aqua"]),
     "is_active": True},
    {"style_number": "3719", "name": "Bella+Canvas Unisex Sponge Fleece Hoodie", "category": "Hoodie",
     "description": "Cozy sponge fleece with retail fit.", "base_price": 45.00,
     "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
     "available_colors": json.dumps(["Black", "Navy", "Heather Gray", "Maroon"]),
     "is_active": True},
    {"style_number": "8800", "name": "Bella+Canvas Unisex Crewneck Sweatshirt", "category": "Crew",
     "description": "Classic crew neck sweatshirt.", "base_price": 38.00,
     "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
     "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
     "is_active": True},
    {"style_number": "3501", "name": "Bella+Canvas Long Sleeve Tee", "category": "Tee",
     "description": "Long sleeve jersey tee.", "base_price": 28.00,
     "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
     "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
     "is_active": True},
    {"style_number": "6004", "name": "Bella+Canvas Jersey Tank", "category": "Tank",
     "description": "Relaxed fit tank.", "base_price": 22.00,
     "available_sizes": json.dumps(["S", "M", "L", "XL"]),
     "available_colors": json.dumps(["White", "Black", "Navy", "Heather Gray"]),
     "is_active": True},
]


def seed_products_if_empty():
    """If no products exist (e.g. fresh deploy), seed demo products so the shop is not empty."""
    if Product.query.count() > 0:
        return
    for p_data in DEMO_PRODUCTS:
        if not Product.query.filter_by(style_number=p_data["style_number"]).first():
            db.session.add(Product(**p_data))
    db.session.commit()
