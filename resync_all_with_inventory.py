"""
Re-sync ALL products to fix inventory data
This will update inventory counts for all color variants
"""
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

app = create_app()

with app.app_context():
    print("="*80)
    print("RE-SYNCING ALL PRODUCTS WITH CORRECT INVENTORY")
    print("="*80)
    
    api = SSActivewearAPI()
    
    # Get all products that have API data
    products = Product.query.filter(Product.api_data.isnot(None)).all()
    
    print(f"\nFound {len(products)} products to re-sync")
    print("="*80)
    
    updated_count = 0
    total_inventory_items = 0
    
    for i, product in enumerate(products, 1):
        try:
            # Get style ID from API data
            api_data = json.loads(product.api_data)
            style_id = api_data.get('style_id')
            
            if not style_id:
                print(f"\n[{i}/{len(products)}] SKIP {product.style_number} - No style ID")
                continue
            
            print(f"\n[{i}/{len(products)}] {product.style_number} - {product.name}")
            
            # Re-fetch style details with inventory
            print(f"  Re-fetching from S&S API...")
            style_details = api.get_style_details(style_id)
            
            if not style_details or 'color_variants' not in style_details:
                print(f"  ERROR: No style details")
                continue
            
            color_variants_data = style_details['color_variants']
            print(f"  Got {len(color_variants_data)} color variants")
            
            # Update color variants with new inventory
            for variant_data in color_variants_data:
                color_name = variant_data['color_name']
                inventory = variant_data.get('sizes', {})
                total_qty = sum(inventory.values()) if inventory else 0
                
                # Find existing variant
                existing_variant = ProductColorVariant.query.filter_by(
                    product_id=product.id,
                    color_name=color_name
                ).first()
                
                if existing_variant:
                    # Update inventory
                    existing_variant.size_inventory = json.dumps(inventory)
                    existing_variant.last_synced = datetime.utcnow()
                    
                    if total_qty > 0:
                        print(f"    {color_name}: {total_qty} units across {len(inventory)} sizes")
                        total_inventory_items += total_qty
                else:
                    # Create new variant
                    new_variant = ProductColorVariant(
                        product_id=product.id,
                        color_name=color_name,
                        front_image_url=variant_data.get('front_image'),
                        back_image_url=variant_data.get('back_image'),
                        side_image_url=variant_data.get('side_image'),
                        size_inventory=json.dumps(inventory),
                        ss_color_id=variant_data.get('color_id')
                    )
                    db.session.add(new_variant)
                    
                    if total_qty > 0:
                        print(f"    {color_name}: {total_qty} units (NEW)")
                        total_inventory_items += total_qty
            
            db.session.commit()
            updated_count += 1
            print(f"  UPDATED!")
            
        except Exception as e:
            print(f"  ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            continue
    
    print("\n" + "="*80)
    print("RE-SYNC COMPLETE!")
    print("="*80)
    print(f"Products updated: {updated_count}")
    print(f"Total inventory items: {total_inventory_items}")
    print("\nRefresh your browser to see inventory counts!")
    print("="*80)
