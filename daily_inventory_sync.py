"""
Daily Inventory Sync Script
Run this daily to update inventory counts for all products
"""
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

app = create_app()

with app.app_context():
    print("="*80)
    print(f"DAILY INVENTORY SYNC - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    api = SSActivewearAPI()
    
    # Get all products
    products = Product.query.all()
    
    print(f"\nUpdating inventory for {len(products)} products...")
    
    updated_products = 0
    updated_variants = 0
    
    for i, product in enumerate(products, 1):
        # Skip if no brand or API data
        if not product.brand or 'bella' not in product.brand.lower():
            continue
        
        print(f"\n[{i}/{len(products)}] {product.style_number} - {product.name}")
        
        try:
            # Get product API data to find style ID
            if product.api_data:
                api_data = json.loads(product.api_data)
                style_id = api_data.get('style_id')
                
                if not style_id:
                    print(f"  SKIP: No style ID")
                    continue
            else:
                print(f"  SKIP: No API data")
                continue
            
            # Fetch fresh inventory
            print(f"  Fetching inventory for style ID {style_id}...")
            inventory_data = api.get_inventory(style_id=style_id)
            
            if not inventory_data:
                print(f"  SKIP: No inventory data")
                continue
            
            # Build inventory map: {SKU: quantity}
            inventory_map = {}
            for inv in inventory_data:
                sku = inv.get('sku', '')
                qty = inv.get('qty', 0)
                inventory_map[sku] = qty
            
            print(f"  Got inventory for {len(inventory_map)} SKUs")
            
            # Update color variants
            variants_updated = 0
            for variant in product.color_variants:
                # Get inventory for this color's sizes
                size_inventory = {}
                
                # Try to match SKUs (format: STYLE-COLOR-SIZE)
                for sku, qty in inventory_map.items():
                    if variant.color_name.upper().replace(' ', '') in sku.upper():
                        # Extract size from SKU
                        parts = sku.split('-')
                        if len(parts) >= 3:
                            size = parts[-1]
                            size_inventory[size] = qty
                
                if size_inventory:
                    variant.size_inventory = json.dumps(size_inventory)
                    variant.last_synced = datetime.utcnow()
                    variants_updated += 1
            
            if variants_updated > 0:
                db.session.commit()
                updated_products += 1
                updated_variants += variants_updated
                print(f"  UPDATED {variants_updated} color variants")
            else:
                print(f"  NO variants updated")
                
        except Exception as e:
            print(f"  ERROR: {str(e)}")
            continue
    
    print("\n" + "="*80)
    print("DAILY SYNC COMPLETE!")
    print("="*80)
    print(f"Products updated: {updated_products}")
    print(f"Color variants updated: {updated_variants}")
    print(f"Synced at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
