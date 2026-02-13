"""Add allowed_placements column to collection table."""
import sqlite3
import os

basedir = os.path.dirname(os.path.abspath(__file__))
for db_name in ['apparel.db', os.path.join('instance', 'apparel.db')]:
    db_path = os.path.join(basedir, db_name)
    if not os.path.exists(db_path):
        continue
    print(f"Migrating {db_path}...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='collection'")
    if c.fetchone():
        try:
            c.execute('ALTER TABLE collection ADD COLUMN allowed_placements TEXT')
            print('  Added collection.allowed_placements')
        except sqlite3.OperationalError as e:
            if 'duplicate' in str(e).lower():
                print('  collection.allowed_placements already exists')
            else:
                print(f'  Error: {e}')
    conn.commit()
    conn.close()
    print("  Done.")
print("Migration complete.")
