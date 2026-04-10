"""
Emergency fix - check what's causing 500 error and ensure all migrations run
"""
from app import create_app
from models import db
from sqlalchemy import text, inspect

app = create_app()

with app.app_context():
    print("="*80)
    print("CHECKING DATABASE SCHEMA")
    print("="*80)
    
    inspector = inspect(db.engine)
    
    # Check Design table
    print("\nDesign table columns:")
    design_columns = [col['name'] for col in inspector.get_columns('design')]
    print(design_columns)
    
    if 'design_fee' not in design_columns:
        print("\nMISSING: design_fee column!")
        print("Adding it now...")
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE design ADD COLUMN design_fee FLOAT DEFAULT 0"))
                conn.commit()
            print("Successfully added design_fee column")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("\ndesign_fee column exists!")
    
    # Check Product table
    print("\nProduct table columns:")
    product_columns = [col['name'] for col in inspector.get_columns('product')]
    print(product_columns)
    
    missing = []
    for col in ['age_group', 'fit_type', 'neck_style', 'sleeve_length']:
        if col not in product_columns:
            missing.append(col)
    
    if missing:
        print(f"\nMISSING Product columns: {missing}")
    else:
        print("\nAll Product columns exist!")
    
    print("\n" + "="*80)
    print("SCHEMA CHECK COMPLETE")
    print("="*80)
