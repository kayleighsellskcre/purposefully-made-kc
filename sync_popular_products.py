"""
Sync popular Bella+Canvas products that HAVE mockup images
"""
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

app = create_app()

# Popular styles that usually have mockup images
POPULAR_STYLES = [
    '3001',  # Unisex Jersey Tee - MOST POPULAR
    '3413',  # Unisex Triblend Tee
    '3719',  # Unisex Fleece Pullover Hoodie
    '6400',  # Ladies' Relaxed Jersey Tee
    '3005',  # Unisex Jersey Tank
]

with app.app_context():
    print("="*80)
    print("SYNCING POPULAR BELLA+CANVAS PRODUCTS WITH MOCKUP IMAGES")
    print("="*80)
    
    api = SSActivewearAPI()
    
    # Get all styles
    print("\nFetching all Bella+Canvas styles...")
    all_styles = api.get_styles(brand_name='Bella+Canvas')
    bella_canvas = [s for s in all_styles if 'bella' in s.get('brandName', '').lower() and 'canvas' in s.get('brandName', '').lower()]
    
    print(f"Found {len(bella_canvas)} Bella+Canvas styles")
    
    # Find the popular ones
    print(f"\nLooking for popular styles: {', '.join(POPULAR_STYLES)}")
    
    popular_found = []
    for style_num in POPULAR_STYLES:
        for style in bella_canvas:
            if style.get('styleName') == style_num:
                popular_found.append(style)
                break
    
    print(f"Found {len(popular_found)} popular styles")
    
    # Process each one
    for i, style in enumerate(popular_found, 1):
        style_id = style.get('styleID')
        style_name = style.get('styleName')
        
        print(f"\n[{i}/{len(popular_found)}] Processing: {style_name} (ID: {style_id})")
        
        # Get detailed info
        style_details = api.get_style_details(style_id)
        
        if not style_details:
            print(f"  ERROR: No details returned")
            continue
        
        # Parse to product format
        product_data = api.parse_style_to_product(style_details)
        color_variants_data = product_data.pop('color_variants', [])
        
        # Check if we got images
        has_images = any(v.get('front_image') for v in color_variants_data)
        print(f"  Colors: {len(color_variants_data)}, Has images: {has_images}")
        
        if not has_images:
            print(f"  SKIPPING - No mockup images available")
            continue
        
        # Create or update product
        existing = Product.query.filter_by(style_number=style_name).first()
        
        if existing:
            for key, value in product_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            product = existing
            print(f"  UPDATED product")
        else:
            product = Product(**product_data)
            db.session.add(product)
            print(f"  CREATED product")
        
        db.session.flush()
        
        # Add color variants
        for variant_data in color_variants_data:
            existing_variant = ProductColorVariant.query.filter_by(
                product_id=product.id,
                color_name=variant_data['color_name']
            ).first()
            
            if existing_variant:
                existing_variant.front_image_url = variant_data.get('front_image')
                existing_variant.back_image_url = variant_data.get('back_image')
                existing_variant.side_image_url = variant_data.get('side_image')
                existing_variant.size_inventory = variant_data.get('size_inventory')
                existing_variant.ss_color_id = variant_data.get('color_id')
                existing_variant.last_synced = datetime.utcnow()
            else:
                new_variant = ProductColorVariant(
                    product_id=product.id,
                    color_name=variant_data['color_name'],
                    front_image_url=variant_data.get('front_image'),
                    back_image_url=variant_data.get('back_image'),
                    side_image_url=variant_data.get('side_image'),
                    size_inventory=variant_data.get('size_inventory'),
                    ss_color_id=variant_data.get('color_id')
                )
                db.session.add(new_variant)
        
        print(f"  SYNCED {len(color_variants_data)} color variants")
    
    db.session.commit()
    
    print("\n" + "="*80)
    print("SYNC COMPLETE!")
    print("="*80)
    
    # Show results
    products_with_images = []
    all_products = Product.query.all()
    
    for p in all_products:
        variants = p.color_variants.all()
        if variants and any(v.front_image_url for v in variants):
            products_with_images.append(p)
    
    print(f"\nProducts WITH mockup images: {len(products_with_images)}")
    for p in products_with_images:
        colors = p.color_variants.count()
        print(f"  {p.style_number} - {p.name} ({colors} colors)")
        print(f"    View at: http://localhost:5000/shop/customize/{p.id}")
    
    print("\nGo try one of these products - they have real mockup images!")
