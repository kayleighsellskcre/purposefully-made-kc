"""Add design_fee to custom_design_request in both possible DB locations."""
import sqlite3
import os

basedir = os.path.abspath(os.path.dirname(__file__))
for db_name in ['apparel.db', os.path.join('instance', 'apparel.db')]:
    db_path = os.path.join(basedir, db_name)
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        continue
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_design_request'")
    if cur.fetchone():
        try:
            cur.execute("SELECT design_fee FROM custom_design_request LIMIT 1")
            print(f"{db_name}: design_fee column already exists")
        except sqlite3.OperationalError:
            cur.execute("ALTER TABLE custom_design_request ADD COLUMN design_fee REAL DEFAULT 0")
            conn.commit()
            print(f"{db_name}: Added design_fee column")
    conn.close()
