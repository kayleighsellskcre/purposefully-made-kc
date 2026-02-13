"""
Add new columns to existing database
Run this once to add brand and api_data columns
"""
from app import create_app
from models import db
import sqlite3

app = create_app()

with app.app_context():
    print("Adding new columns to Product table...")
    
    try:
        # Get database path
        db_path = 'apparel.db'
        
        # Connect directly to SQLite
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Add brand column
        try:
            cursor.execute("ALTER TABLE product ADD COLUMN brand VARCHAR(100)")
            print("✓ Added 'brand' column")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                print("  'brand' column already exists")
            else:
                raise
        
        # Add api_data column
        try:
            cursor.execute("ALTER TABLE product ADD COLUMN api_data TEXT")
            print("✓ Added 'api_data' column")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                print("  'api_data' column already exists")
            else:
                raise
        
        # Add Design gallery columns
        try:
            cursor.execute("ALTER TABLE design ADD COLUMN is_gallery BOOLEAN DEFAULT 0")
            print("✓ Added 'is_gallery' column to design")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                print("  'is_gallery' column already exists")
            else:
                raise
        try:
            cursor.execute("ALTER TABLE design ADD COLUMN title VARCHAR(200)")
            print("✓ Added 'title' column to design")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                print("  'title' column already exists")
            else:
                raise
        
        conn.commit()
        conn.close()
        
        print("\n✓ Database migration complete!")
        print("You can now refresh your browser")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        print("\nIf you see 'table locked' error, stop the Flask server first:")
        print("  1. Press CTRL+C in the terminal running Flask")
        print("  2. Run this script again")
        print("  3. Restart Flask: .\\venv\\Scripts\\python app.py")
