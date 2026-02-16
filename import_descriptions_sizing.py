"""
Import descriptions and sizing information from S&S Activewear for all existing products
"""
from app import create_app
from models import db, Product
from services.ssactivewear_api import SSActivewearAPI
import sys

app = create_app()

with app.app_context():
    api = SSActivewearAPI()
    products = Product.query.filter_by(is_active=True).all()
    
    print(f"Found {len(products)} active products to update")
    print("=" * 80)
    
    updated_count = 0
    for i, product in enumerate(products, 1):
        print(f"\n[{i}/{len(products)}] {product.style_number} - {product.name}")
        
        try:
            # Fetch style data from S&S
            style_data = api.fetch_style_data_by_style_number(product.style_number)
            
            if not style_data:
                print(f"  ⚠️  Not found in S&S API")
                continue
            
            # Update description
            description = style_data.get('description', '')
            if description and description != product.description:
                product.description = description
                print(f"  ✓ Updated description ({len(description)} chars)")
            
            # Update fabric details
            fabric = style_data.get('fabric', '')
            if fabric:
                product.fabric_details = fabric
                print(f"  ✓ Added fabric: {fabric[:50]}...")
            
            # Update fit guide
            fit_guide = style_data.get('fit_guide', '')
            if fit_guide:
                product.fit_guide = fit_guide
                print(f"  ✓ Added fit guide: {fit_guide}")
            
            # Update size chart from spec sheet
            spec_sheet = style_data.get('spec_sheet')
            if spec_sheet:
                import json
                product.size_chart = json.dumps(spec_sheet)
                print(f"  ✓ Added size chart/spec sheet")
            
            updated_count += 1
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue
    
    # Commit all changes
    if updated_count > 0:
        db.session.commit()
        print("\n" + "=" * 80)
        print(f"✅ Successfully updated {updated_count} products")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print("No products were updated")
        print("=" * 80)
