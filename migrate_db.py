"""
Database migration script for adding new columns to Product table
"""
from app import create_app
from models import db
from sqlalchemy import text

app = create_app()

def add_column_if_not_exists(table_name, column_name, column_type):
    """Add column to table if it doesn't already exist - works for both SQLite and PostgreSQL"""
    with app.app_context():
        try:
            # Try to select the column to see if it exists
            with db.engine.connect() as conn:
                conn.execute(text(f"SELECT {column_name} FROM {table_name} LIMIT 1"))
            print(f"Column {table_name}.{column_name} already exists")
        except Exception:
            # Column doesn't exist, add it
            try:
                with db.engine.connect() as conn:
                    # Use IF NOT EXISTS for PostgreSQL, or try-catch for SQLite
                    if 'postgresql' in str(db.engine.url):
                        # PostgreSQL syntax
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}"))
                    else:
                        # SQLite syntax
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
                    conn.commit()
                print(f"Added {table_name}.{column_name}")
            except Exception as alter_error:
                print(f"Error adding {table_name}.{column_name}: {alter_error}")


def run_migrations():
    """Run all pending migrations"""
    with app.app_context():
        print("Running database migrations...")
        print("="*60)
        
        # Add new Product columns
        add_column_if_not_exists('product', 'size_chart', 'TEXT')
        add_column_if_not_exists('product', 'fit_guide', 'TEXT')
        add_column_if_not_exists('product', 'fabric_details', 'TEXT')
        add_column_if_not_exists('product', 'age_group', 'VARCHAR(20)')
        add_column_if_not_exists('product', 'fit_type', 'VARCHAR(30)')
        add_column_if_not_exists('product', 'neck_style', 'VARCHAR(30)')
        add_column_if_not_exists('product', 'sleeve_length', 'VARCHAR(30)')
        
        # Add design_fee column to Design table (use DOUBLE PRECISION for PostgreSQL)
        add_column_if_not_exists('design', 'design_fee', 'DOUBLE PRECISION DEFAULT 0')
        
        # Create favorites table if it doesn't exist
        try:
            from models import Favorite
            db.create_all()
            print("Favorites table ready")
        except Exception as e:
            print(f"Note: {e}")
        
        print("="*60)
        print("Migration complete!")


if __name__ == '__main__':
    try:
        run_migrations()
    except Exception as e:
        print(f"Migration failed: {e}")