"""
Sync product catalog from S&S Activewear API
Run this script to update your products with live data
"""
from app import create_app
from models import db, Product
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime
import json

def sync_products(dry_run=False, limit=None, update_existing=True):
    """
    Sync products from S&S Activewear API
    
    Args:
        dry_run: If True, don't save to database (just preview)
        limit: Limit number of products to sync (for testing)
        update_existing: If True, update existing products; if False, only add new
    """
    app = create_app()
    
    with app.app_context():
        print("\n" + "="*70)
        print("S&S ACTIVEWEAR CATALOG SYNC")
        print("="*70)
        
        # Initialize API
        try:
            api = SSActivewearAPI()
        except ValueError as e:
            print(f"\n❌ ERROR: {e}")
            print("\nPlease add your S&S Activewear credentials to .env file:")
            print("  SSACTIVEWEAR_API_KEY=your_api_key")
            print("  SSACTIVEWEAR_ACCOUNT_NUMBER=your_account_number")
            return
        
        # Fetch products from API
        print(f"\n📡 Fetching Bella+Canvas products from S&S Activewear...")
        if limit:
            print(f"   (Limited to {limit} products for testing)")
        
        # Sync only styles that have mockup folders in uploads/mockups/
        products_data = api.sync_mockup_styles()
        
        if not products_data:
            print("\n❌ No products fetched from API")
            return
        
        print(f"\n✓ Fetched {len(products_data)} products from API")
        
        # Process each product
        stats = {
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0
        }
        
        print(f"\n{'DRY RUN - ' if dry_run else ''}Processing products...")
        print("-" * 70)
        
        for product_data in products_data:
            style_number = product_data['style_number']
            
            try:
                # Check if product exists
                existing = Product.query.filter_by(style_number=style_number).first()
                
                if existing:
                    if update_existing:
                        # Update existing product
                        existing.name = product_data['name']
                        existing.category = product_data['category']
                        existing.description = product_data['description']
                        existing.base_price = product_data['base_price']
                        existing.wholesale_cost = product_data['wholesale_cost']
                        existing.available_sizes = product_data['available_sizes']
                        existing.available_colors = product_data['available_colors']
                        
                        if not dry_run:
                            db.session.add(existing)
                        
                        stats['updated'] += 1
                        print(f"  ✓ Updated: {style_number} - {product_data['name']}")
                    else:
                        stats['skipped'] += 1
                        print(f"  ⊘ Skipped: {style_number} (already exists)")
                else:
                    # Add new product
                    new_product = Product(**product_data)
                    
                    if not dry_run:
                        db.session.add(new_product)
                    
                    stats['added'] += 1
                    print(f"  + Added: {style_number} - {product_data['name']}")
                    
            except Exception as e:
                stats['errors'] += 1
                print(f"  ✗ Error: {style_number} - {str(e)}")
        
        # Commit changes
        if not dry_run:
            try:
                db.session.commit()
                print(f"\n✓ Changes saved to database")
            except Exception as e:
                db.session.rollback()
                print(f"\n❌ Error saving to database: {e}")
                return
        else:
            print(f"\n⚠ DRY RUN - No changes saved")
        
        # Print summary
        print("\n" + "="*70)
        print("SYNC SUMMARY")
        print("="*70)
        print(f"  Products Added:   {stats['added']}")
        print(f"  Products Updated: {stats['updated']}")
        print(f"  Products Skipped: {stats['skipped']}")
        print(f"  Errors:           {stats['errors']}")
        print(f"  Total Processed:  {len(products_data)}")
        print("="*70)
        
        if dry_run:
            print("\n💡 Run without --dry-run to save changes")
        else:
            print(f"\n✓ Sync completed successfully at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync product catalog from S&S Activewear')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without saving')
    parser.add_argument('--limit', type=int, help='Limit number of products (for testing)')
    parser.add_argument('--no-update', action='store_true', help='Only add new products, don\'t update existing')
    
    args = parser.parse_args()
    
    sync_products(
        dry_run=args.dry_run,
        limit=args.limit,
        update_existing=not args.no_update
    )
