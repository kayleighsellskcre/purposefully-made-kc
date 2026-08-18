"""
add_directory_column.py
───────────────────────
One-time migration: adds show_in_directory column to the collection table.
Safe to run multiple times (skips if column already exists).

Run from project root in Cursor terminal:
    py -3.12 scripts/add_directory_column.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

from app import create_app
from models import db

app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(db.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='collection' AND column_name='show_in_directory'"
        ))
        if result.fetchone():
            print("Column 'show_in_directory' already exists — nothing to do.")
        else:
            conn.execute(db.text(
                "ALTER TABLE collection ADD COLUMN show_in_directory BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()
            print("✅  Added 'show_in_directory' column to collection table.")
