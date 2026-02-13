"""
Fix missing color variant images by re-syncing from S&S
"""
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

app = create_app()

with app.app_context():
    print("="*80)
    print("FIXING COLOR VARIANT IMAGES")
    print("="*80)
    
    # Get the bodysuit product
    product = Product.query.filter_by(style_number='0990').first()
    
    if not product:
        print("Product 0990 not found!")
        exit(1)
    
    print(f"\nProduct: {product.name}")
    print(f"Current variants: {product.color_variants.count()}")
    
    # Re-sync from API
    api = SSActivewearAPI()
    
    # Get fresh data for this style
    print("\nFetching fresh data from S&S API...")
    style_id = 8507  # Style ID for 0990
    style_details = api.get_style_details(style_id)
    
    if not style_details or 'color_variants' not in style_details:
        print("ERROR: No color variants in API response")
        print("Response:", style_details)
        exit(1)
    
    print(f"Got {len(style_details['color_variants'])} color variants from API")
    
    # Update or create color variants
    updated = 0
    for variant_data in style_details['color_variants']:
        color_name = variant_data['color_name']
        front_image = variant_data.get('front_image')
        back_image = variant_data.get('back_image')
        inventory = variant_data.get('sizes', {})
        
        print(f"\n  Processing: {color_name}")
        print(f"    Front: {front_image[:60] if front_image else 'None'}...")
        print(f"    Back: {back_image[:60] if back_image else 'None'}...")
        print(f"    Inventory: {inventory}")
        
        # Find or create variant
        existing = ProductColorVariant.query.filter_by(
            product_id=product.id,
            color_name=color_name
        ).first()
        
        if existing:
            existing.front_image_url = front_image
            existing.back_image_url = back_image
            existing.size_inventory = json.dumps(inventory)
            existing.ss_color_id = variant_data.get('color_id')
            existing.last_synced = datetime.utcnow()
            print(f"    UPDATED existing variant")
        else:
            new_variant = ProductColorVariant(
                product_id=product.id,
                color_name=color_name,
                front_image_url=front_image,
                back_image_url=back_image,
                size_inventory=json.dumps(inventory),
                ss_color_id=variant_data.get('color_id')
            )
            db.session.add(new_variant)
            print(f"    CREATED new variant")
        
        updated += 1
    
    db.session.commit()
    
    print("\n" + "="*80)
    print(f"SUCCESS! Updated {updated} color variants")
    print("="*80)
    
    # Verify
    print("\nVerifying...")
    variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
    for v in variants:
        print(f"  {v.color_name}: front={bool(v.front_image_url)}, back={bool(v.back_image_url)}")
    
    print("\nRefresh your browser and the images will appear!")
