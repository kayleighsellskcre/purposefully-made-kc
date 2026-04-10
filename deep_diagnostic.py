"""
Deep diagnostic - check Railway deployment and database state
"""
import os
import sys

# Check if we can even import the app
try:
    print("="*80)
    print("DEEP DIAGNOSTIC CHECK")
    print("="*80)
    
    print("\n1. Importing app...")
    from app import create_app
    print("   ✓ App imports successfully")
    
    print("\n2. Creating app instance...")
    app = create_app()
    print("   ✓ App created successfully")
    
    print("\n3. Checking database connection...")
    with app.app_context():
        from models import db, Design, Product
        from sqlalchemy import inspect, text
        
        # Test connection
        try:
            with db.engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                print("   ✓ Database connection works!")
        except Exception as e:
            print(f"   ✗ Database connection failed: {e}")
            sys.exit(1)
        
        # Check Design table structure
        print("\n4. Checking Design table...")
        inspector = inspect(db.engine)
        design_cols = [col['name'] for col in inspector.get_columns('design')]
        print(f"   Columns: {design_cols}")
        
        if 'design_fee' in design_cols:
            print("   ✓ design_fee column exists")
        else:
            print("   ✗ design_fee column MISSING!")
        
        # Check column type
        design_table_cols = inspector.get_columns('design')
        for col in design_table_cols:
            if col['name'] == 'design_fee':
                print(f"   design_fee type: {col['type']}")
        
        # Try to query Design table
        print("\n5. Testing Design model query...")
        try:
            designs = Design.query.limit(1).all()
            print(f"   ✓ Design query works! Found {len(designs)} designs")
        except Exception as e:
            print(f"   ✗ Design query failed: {e}")
            print(f"   Error type: {type(e).__name__}")
        
        # Check Product table
        print("\n6. Checking Product table...")
        product_cols = [col['name'] for col in inspector.get_columns('product')]
        required = ['age_group', 'fit_type', 'neck_style', 'sleeve_length']
        for col in required:
            if col in product_cols:
                print(f"   ✓ {col} exists")
            else:
                print(f"   ✗ {col} MISSING!")
        
        # Try to query Product table
        print("\n7. Testing Product model query...")
        try:
            products = Product.query.limit(1).all()
            print(f"   ✓ Product query works! Found {len(products)} products")
        except Exception as e:
            print(f"   ✗ Product query failed: {e}")
        
        # Test the homepage route
        print("\n8. Testing homepage route...")
        try:
            from routes.main import index
            with app.test_request_context():
                response = index()
                print(f"   ✓ Homepage route works! Response type: {type(response)}")
        except Exception as e:
            print(f"   ✗ Homepage route failed: {e}")
            print(f"   Full error: {repr(e)}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*80)
    print("DIAGNOSTIC COMPLETE")
    print("="*80)

except Exception as e:
    print(f"\n✗ CRITICAL ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
