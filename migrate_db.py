"""
Auto-migration script for Railway deployment
Adds new columns safely if they don't exist
"""
from app import create_app
from models import db
import sys

app = create_app()

def add_column_if_not_exists(table_name, column_name, column_type):
    """Add a column to a table if it doesn't already exist"""
    with app.app_context():
        try:
            # Check if column exists by trying to query it
            result = db.engine.execute(f"SELECT {column_name} FROM {table_name} LIMIT 1")
            print(f"✓ Column {table_name}.{column_name} already exists")
        except Exception as e:
            # Column doesn't exist, add it
            try:
                db.engine.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                print(f"✓ Added column {table_name}.{column_name} ({column_type})")
            except Exception as alter_error:
                print(f"✗ Error adding {table_name}.{column_name}: {alter_error}")

def run_migrations():
    """Run all pending migrations"""
    with app.app_context():
        print("Running database migrations...")
        print("="*60)
        
        # Add new Product columns
        add_column_if_not_exists('product', 'size_chart', 'TEXT')
        add_column_if_not_exists('product', 'fit_guide', 'TEXT')
        add_column_if_not_exists('product', 'fabric_details', 'TEXT')
        
        print("="*60)
        print("✅ Migration complete!")

if __name__ == '__main__':
    try:
        run_migrations()
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
