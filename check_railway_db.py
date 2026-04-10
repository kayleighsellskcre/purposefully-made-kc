"""
Check Railway database state and fix products issue
"""
from app import create_app
from models import db, Product, ProductColorVariant
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("="*80)
    print("CHECKING RAILWAY DATABASE STATE")
    print("="*80)
    
    # Check Product table
    print("\n1. Checking products...")
    try:
        product_count = Product.query.count()
        active_count = Product.query.filter_by(is_active=True).count()
        print(f"   Total products: {product_count}")
        print(f"   Active products: {active_count}")
        
        if product_count == 0:
            print("\n   *** NO PRODUCTS IN DATABASE ***")
            print("   You need to:")
            print("   1. Go to Admin → Products")
            print("   2. Click 'Sync from S&S Activewear' button")
            print("   OR")
            print("   3. Manually add products via 'Add Product'")
        else:
            # Show some products
            products = Product.query.limit(5).all()
            print("\n   Sample products:")
            for p in products:
                print(f"   - {p.style_number}: {p.name} (Active: {p.is_active})")
    except Exception as e:
        print(f"   Error querying products: {e}")
    
    # Check ProductColorVariant table
    print("\n2. Checking color variants...")
    try:
        variant_count = ProductColorVariant.query.count()
        print(f"   Total color variants: {variant_count}")
        
        if variant_count == 0 and product_count > 0:
            print("\n   *** PRODUCTS EXIST BUT NO COLOR VARIANTS ***")
            print("   You need to:")
            print("   1. Go to Admin → Products")
            print("   2. Click 'Link Mockup Images' button")
    except Exception as e:
        print(f"   Error querying variants: {e}")
    
    # Check all Product columns exist
    print("\n3. Checking Product table schema...")
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    product_cols = [col['name'] for col in inspector.get_columns('product')]
    
    required_cols = ['age_group', 'fit_type', 'neck_style', 'sleeve_length']
    missing = [col for col in required_cols if col not in product_cols]
    
    if missing:
        print(f"   MISSING columns: {missing}")
    else:
        print("   All required columns exist!")
    
    print("\n" + "="*80)
    print("CHECK COMPLETE")
    print("="*80)
