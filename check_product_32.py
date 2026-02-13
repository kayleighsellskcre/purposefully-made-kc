"""
Check product ID 32 to see inventory data
"""
from app import create_app
from models import db, Product, ProductColorVariant
import json

app = create_app()

with app.app_context():
    product = Product.query.get(32)
    
    if not product:
        print("Product 32 not found!")
    else:
        print(f"Product: {product.name} (Style: {product.style_number})")
        print(f"ID: {product.id}")
        print()
        
        variants = ProductColorVariant.query.filter_by(product_id=32).all()
        print(f"Found {len(variants)} color variants:")
        print("="*80)
        
        for v in variants:
            inventory = json.loads(v.size_inventory) if v.size_inventory else {}
            total_qty = sum(inventory.values()) if inventory else 0
            
            print(f"\nColor: {v.color_name}")
            print(f"  Inventory: {inventory}")
            print(f"  Total: {total_qty} units")
            print(f"  Front Image: {v.front_image_url[:50] if v.front_image_url else 'None'}...")
