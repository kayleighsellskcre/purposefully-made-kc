"""
EMERGENCY FIX - Ensure design_fee column exists with proper handling
"""
from app import create_app
from models import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("="*80)
    print("EMERGENCY MIGRATION - Adding design_fee column")
    print("="*80)
    
    try:
        with db.engine.connect() as conn:
            # Check if column exists
            result = conn.execute(text("SELECT design_fee FROM design LIMIT 1"))
            print("Column design_fee already exists!")
    except Exception:
        print("Column design_fee NOT FOUND - adding it now...")
        try:
            with db.engine.connect() as conn:
                # Use proper PostgreSQL or SQLite syntax
                if 'postgresql' in str(db.engine.url):
                    conn.execute(text("ALTER TABLE design ADD COLUMN design_fee DOUBLE PRECISION DEFAULT 0"))
                else:
                    conn.execute(text("ALTER TABLE design ADD COLUMN design_fee REAL DEFAULT 0"))
                conn.commit()
            print("SUCCESS: Added design_fee column!")
        except Exception as e:
            print(f"ERROR: Failed to add column: {e}")
    
    print("="*80)
