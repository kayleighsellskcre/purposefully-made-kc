"""Add is_gallery and title columns to Design table - run with: python migrate_design_gallery.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from config import Config

app = create_app()
db_path = Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')

with app.app_context():
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE design ADD COLUMN is_gallery BOOLEAN DEFAULT 0")
        print("Added is_gallery column")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print("is_gallery column already exists")
        else:
            raise
    
    try:
        cursor.execute("ALTER TABLE design ADD COLUMN title VARCHAR(200)")
        print("Added title column")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print("title column already exists")
        else:
            raise
    
    conn.commit()
    conn.close()
    print("Migration complete!")
