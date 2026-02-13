"""
Quick script to sync products from S&S Activewear with color variants and inventory
"""
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

app = create_app()

with app.app_context():
    print("="*80)
    print("SYNCING PRODUCTS FROM S&S ACTIVEWEAR")
    print("="*80)
    
    try:
        # Initialize API
        api = SSActivewearAPI()
        print("\nFetching products from S&S Activewear...")
        
        # Sync 10 products to start
        products_data = api.sync_bella_canvas_catalog(limit=10)
        
        if not products_data:
            print("ERROR: No products returned from API")
            exit(1)
        
        print(f"\nReceived {len(products_data)} products from API")
        print("\nProcessing products...")
        
        added = 0
        updated = 0
        variants_added = 0
        
        for product_data in products_data:
            # Extract color variants
            color_variants_data = product_data.pop('color_variants', [])
            
            style_num = product_data['style_number']
            print(f"\n  Processing: {style_num} - {product_data['name']}")
            
            # Check if product exists
            existing = Product.query.filter_by(style_number=style_num).first()
            
            if existing:
                # Update existing
                for key, value in product_data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                product = existing
                updated += 1
                print(f"    UPDATED product")
            else:
                # Add new
                product = Product(**product_data)
                db.session.add(product)
                added += 1
                print(f"    ADDED new product")
            
            # Flush to get product ID
            db.session.flush()
            
            # Process color variants
            print(f"    Processing {len(color_variants_data)} color variants...")
            for variant_data in color_variants_data:
                # Check if variant exists
                existing_variant = ProductColorVariant.query.filter_by(
                    product_id=product.id,
                    color_name=variant_data['color_name']
                ).first()
                
                if existing_variant:
                    # Update existing
                    existing_variant.front_image_url = variant_data.get('front_image')
                    existing_variant.back_image_url = variant_data.get('back_image')
                    existing_variant.side_image_url = variant_data.get('side_image')
                    existing_variant.size_inventory = variant_data.get('size_inventory')
                    existing_variant.ss_color_id = variant_data.get('color_id')
                    existing_variant.last_synced = datetime.utcnow()
                else:
                    # Add new
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
                    variants_added += 1
            
            print(f"    SYNCED {len(color_variants_data)} colors")
        
        # Commit all changes
        db.session.commit()
        
        print("\n" + "="*80)
        print("SYNC COMPLETE!")
        print("="*80)
        print(f"Products added: {added}")
        print(f"Products updated: {updated}")
        print(f"Color variants added: {variants_added}")
        print(f"Total products in database: {Product.query.count()}")
        print("="*80)
        print("\nGo to http://localhost:5000/shop to see your products!")
        
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
