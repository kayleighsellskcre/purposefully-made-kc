"""Add back_design_file_name column to order_item table."""
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
    try:
        c.execute('ALTER TABLE order_item ADD COLUMN back_design_file_name TEXT')
        print('  Added order_item.back_design_file_name')
    except sqlite3.OperationalError as e:
        if 'duplicate' in str(e).lower():
            print('  order_item.back_design_file_name already exists')
        else:
            print(f'  Error: {e}')
    conn.commit()
    conn.close()
    print("  Done.")
print("Migration complete.")
