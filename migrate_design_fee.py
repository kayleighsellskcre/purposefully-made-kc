"""Add design_fee columns - run once: python migrate_design_fee.py"""
import sqlite3
import os

basedir = os.path.abspath(os.path.dirname(__file__))
for db_name in ['apparel.db', os.path.join('instance', 'apparel.db')]:
    db_path = os.path.join(basedir, db_name)
    if not os.path.exists(db_path):
        continue
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Design table - only if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='design'")
    if cursor.fetchone():
        try:
            cursor.execute("SELECT design_fee FROM design LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE design ADD COLUMN design_fee REAL DEFAULT 0")
            print(f"Added design_fee to design in {db_name}")
    # CustomDesignRequest table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_design_request'")
    if cursor.fetchone():
        try:
            cursor.execute("SELECT design_fee FROM custom_design_request LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE custom_design_request ADD COLUMN design_fee REAL DEFAULT 0")
            print(f"Added design_fee to custom_design_request in {db_name}")
    conn.commit()
    conn.close()
    print("Migration complete.")
    break
else:
    print("Database not found. Run the app first to create it.")
