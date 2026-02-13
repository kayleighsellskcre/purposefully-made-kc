"""
Sync TOP 15 most popular Bella+Canvas products with all colors, sizes, and inventory
"""
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

# TOP 15 MOST POPULAR BELLA+CANVAS STYLES
TOP_15_STYLES = [
    '3001',  # Unisex Jersey Short Sleeve Tee - BESTSELLER
    '3413',  # Unisex Triblend Short Sleeve Tee
    '3005',  # Unisex Jersey Tank
    '3719',  # Unisex Fleece Pullover Hoodie
    '6400',  # Ladies' Relaxed Jersey Short Sleeve Tee
    '3001C', # Youth Jersey Short Sleeve Tee
    '8800',  # Unisex Fleece Crewneck Sweatshirt
    '3480',  # Unisex Jersey Long Sleeve Tee
    '3739',  # Unisex Sponge Fleece Full-Zip Hoodie
    '3501',  # Unisex Jersey Long Sleeve Tee
    '3415',  # Unisex Triblend Short Sleeve Tee
    '6004',  # Ladies' The Favorite Tee
    '8803',  # Unisex Fleece Raglan Sweatshirt
    '3200',  # Unisex V-Neck Jersey Tee
    '3415C', # Youth Triblend Short Sleeve Tee
]

app = create_app()

with app.app_context():
    print("="*80)
    print("      SYNCING TOP 15 BELLA+CANVAS PRODUCTS")
    print("="*80)
    print("\nThis will fetch:")
    print("  - Product details")
    print("  - ALL colors available")
    print("  - ALL sizes available")
    print("  - LIVE inventory for every color+size combo")
    print("\n" + "="*80)
    
    api = SSActivewearAPI()
    
    # Get all Bella+Canvas styles
    print("\nFetching Bella+Canvas catalog from S&S Activewear...")
    all_styles = api.get_styles(brand_name='Bella+Canvas')
    bella_canvas = [s for s in all_styles if 'bella' in s.get('brandName', '').lower() and 'canvas' in s.get('brandName', '').lower()]
    
    print(f"Found {len(bella_canvas)} total Bella+Canvas styles in S&S catalog")
    
    # Find our top 15
    found_styles = []
    for target_style in TOP_15_STYLES:
        for style in bella_canvas:
            if style.get('styleName') == target_style:
                found_styles.append(style)
                break
    
    print(f"\nFound {len(found_styles)} of the top 15 styles")
    print("="*80)
    
    total_added = 0
    total_updated = 0
    total_variants = 0
    
    for i, style in enumerate(found_styles, 1):
        style_id = style.get('styleID')
        style_name = style.get('styleName')
        
        print(f"\n[{i}/{len(found_styles)}] {style_name} (ID: {style_id})")
        print("-" * 60)
        
        # Get detailed info with colors, sizes, and inventory
        print(f"  Fetching details...")
        style_details = api.get_style_details(style_id)
        
        if not style_details:
            print(f"  ERROR: No details returned")
            continue
        
        # Parse to product format
        product_data = api.parse_style_to_product(style_details)
        color_variants_data = product_data.pop('color_variants', [])
        
        print(f"  Got {len(color_variants_data)} color variants")
        
        # Save product
        existing = Product.query.filter_by(style_number=style_name).first()
        
        if existing:
            for key, value in product_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            product = existing
            total_updated += 1
            print(f"  UPDATED product")
        else:
            product = Product(**product_data)
            db.session.add(product)
            total_added += 1
            print(f"  ADDED new product")
        
        db.session.flush()
        
        # Save color variants with inventory
        print(f"  Saving color variants...")
        for variant_data in color_variants_data:
            existing_variant = ProductColorVariant.query.filter_by(
                product_id=product.id,
                color_name=variant_data['color_name']
            ).first()
            
            inventory = variant_data.get('sizes', {})
            
            if existing_variant:
                existing_variant.front_image_url = variant_data.get('front_image')
                existing_variant.back_image_url = variant_data.get('back_image')
                existing_variant.side_image_url = variant_data.get('side_image')
                existing_variant.size_inventory = json.dumps(inventory)
                existing_variant.ss_color_id = variant_data.get('color_id')
                existing_variant.last_synced = datetime.utcnow()
            else:
                new_variant = ProductColorVariant(
                    product_id=product.id,
                    color_name=variant_data['color_name'],
                    front_image_url=variant_data.get('front_image'),
                    back_image_url=variant_data.get('back_image'),
                    side_image_url=variant_data.get('side_image'),
                    size_inventory=json.dumps(inventory),
                    ss_color_id=variant_data.get('color_id')
                )
                db.session.add(new_variant)
                total_variants += 1
        
        print(f"  SAVED {len(color_variants_data)} color variants")
        
        # Commit after each product
        db.session.commit()
        print(f"  COMMITTED to database")
    
    print("\n" + "="*80)
    print("                    SYNC COMPLETE!")
    print("="*80)
    print(f"\nProducts added: {total_added}")
    print(f"Products updated: {total_updated}")
    print(f"Color variants saved: {total_variants}")
    print(f"\nTotal products in catalog: {Product.query.count()}")
    print(f"Total color variants: {ProductColorVariant.query.count()}")
    
    # Show product summary
    print("\n" + "="*80)
    print("                  YOUR PRODUCT CATALOG")
    print("="*80)
    
    all_products = Product.query.order_by(Product.style_number).all()
    for p in all_products:
        variant_count = p.color_variants.count()
        print(f"\n{p.style_number} - {p.name}")
        print(f"  Price: ${p.base_price:.2f}")
        print(f"  Colors: {variant_count}")
        print(f"  View at: http://localhost:5000/shop/customize/{p.id}")
    
    print("\n" + "="*80)
    print("Go to http://localhost:5000/shop to see your products!")
    print("="*80)
