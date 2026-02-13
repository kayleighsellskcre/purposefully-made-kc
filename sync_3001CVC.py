"""
Sync Bella+Canvas 3001CVC (Canvas Tee) with all colors, sizes, and inventory
"""
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

app = create_app()

with app.app_context():
    print("="*80)
    print("SYNCING BELLA+CANVAS 3001CVC (CANVAS TEE)")
    print("="*80)
    
    api = SSActivewearAPI()
    
    # Get all Bella+Canvas styles
    print("\nFetching Bella+Canvas catalog...")
    all_styles = api.get_styles(brand_name='Bella+Canvas')
    bella_canvas = [s for s in all_styles if 'bella' in s.get('brandName', '').lower() and 'canvas' in s.get('brandName', '').lower()]
    
    print(f"Found {len(bella_canvas)} Bella+Canvas styles")
    
    # Find 3001CVC
    target_style = None
    for style in bella_canvas:
        if style.get('styleName') == '3001CVC':
            target_style = style
            break
    
    if not target_style:
        print("\nERROR: 3001CVC not found in S&S catalog")
        print("\nSearching for similar styles...")
        cvc_styles = [s for s in bella_canvas if 'CVC' in s.get('styleName', '')]
        if cvc_styles:
            print(f"\nFound {len(cvc_styles)} CVC styles:")
            for s in cvc_styles[:10]:
                print(f"  {s.get('styleName')} - {s.get('styleDescription', 'N/A')}")
        exit(1)
    
    style_id = target_style.get('styleID')
    style_name = target_style.get('styleName')
    
    print(f"\nFound: {style_name} (ID: {style_id})")
    print("-" * 80)
    
    # Get detailed info
    print("Fetching ALL colors, sizes, and inventory...")
    style_details = api.get_style_details(style_id)
    
    if not style_details:
        print("ERROR: Could not fetch style details")
        exit(1)
    
    # Parse product data
    product_data = api.parse_style_to_product(style_details)
    color_variants_data = product_data.pop('color_variants', [])
    
    print(f"\nProduct Info:")
    print(f"  Name: {product_data['name']}")
    print(f"  Category: {product_data['category']}")
    print(f"  Price: ${product_data['base_price']}")
    print(f"  Colors: {len(color_variants_data)}")
    
    # Show color details
    print(f"\nColor Variants:")
    for variant in color_variants_data[:10]:  # Show first 10
        inventory = variant.get('sizes', {})
        total_qty = sum(inventory.values()) if inventory else 0
        print(f"  - {variant['color_name']}: {len(inventory)} sizes, {total_qty} total units")
    
    if len(color_variants_data) > 10:
        print(f"  ... and {len(color_variants_data) - 10} more colors")
    
    # Save to database
    print(f"\nSaving to database...")
    
    existing = Product.query.filter_by(style_number=style_name).first()
    
    if existing:
        print("  Product already exists - UPDATING")
        for key, value in product_data.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
        product = existing
    else:
        print("  Creating NEW product")
        product = Product(**product_data)
        db.session.add(product)
    
    db.session.flush()
    
    # Save color variants
    print(f"  Saving {len(color_variants_data)} color variants...")
    
    variants_added = 0
    variants_updated = 0
    
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
            variants_updated += 1
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
            variants_added += 1
    
    db.session.commit()
    
    print("\n" + "="*80)
    print("SUCCESS!")
    print("="*80)
    print(f"\nProduct: {product_data['name']}")
    print(f"Style: {style_name}")
    print(f"Colors: {len(color_variants_data)}")
    print(f"Variants added: {variants_added}")
    print(f"Variants updated: {variants_updated}")
    
    # Show sample inventory
    print(f"\nSample Inventory (first color):")
    if color_variants_data:
        first_color = color_variants_data[0]
        print(f"  Color: {first_color['color_name']}")
        inventory = first_color.get('sizes', {})
        for size, qty in sorted(inventory.items()):
            print(f"    {size}: {qty} in stock")
    
    print(f"\nView product at: http://localhost:5000/shop/customize/{product.id}")
    print("="*80)
