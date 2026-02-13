"""Add back_design_font column to Collection table - run with: python migrate_back_design_font.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config

basedir = os.path.dirname(os.path.abspath(__file__))
db_uri = Config.SQLALCHEMY_DATABASE_URI
if not db_uri.startswith('sqlite'):
    print("This migration is for SQLite. For other DBs, run: ALTER TABLE collection ADD COLUMN back_design_font VARCHAR(50)")
    sys.exit(1)

# Try multiple possible DB locations (app may use instance folder or project root)
db_path = db_uri.replace('sqlite:///', '')
if not os.path.isabs(db_path):
    db_path = os.path.join(basedir, db_path)
db_paths = [db_path, os.path.join(basedir, 'apparel.db'), os.path.join(basedir, 'instance', 'apparel.db')]

import sqlite3
done = False
for db_path in db_paths:
    if not os.path.exists(db_path):
        continue
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    tbl = 'collection' if 'collection' in tables else next((t for t in tables if 'collection' in t.lower()), None)
    if not tbl:
        conn.close()
        continue
    try:
        cursor.execute(f'ALTER TABLE "{tbl}" ADD COLUMN back_design_font VARCHAR(50)')
        conn.commit()
        print(f"Added back_design_font column to {tbl} table in {db_path}")
        done = True
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            print(f"back_design_font column already exists in {db_path}")
            done = True
        else:
            print(f"Error: {e}")
    conn.close()
    if done:
        break

if not done:
    print("Could not find database with 'collection' table. Tried:")
    for p in db_paths:
        print(f"  - {p} (exists: {os.path.exists(p)})")
    sys.exit(1)
print("Migration complete!")
