"""Add missing columns to order table - fixes 500 error."""
import sqlite3
import os

basedir = os.path.dirname(os.path.abspath(__file__))
# Check both possible DB locations
for db_name in ['apparel.db', os.path.join('instance', 'apparel.db')]:
    db_path = os.path.join(basedir, db_name)
    if not os.path.exists(db_path):
        continue
    print(f"Migrating {db_path}...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT name FROM sqlite_master WHERE type="table"')
    tables = [r[0] for r in c.fetchall()]
    print("  Tables:", tables)
    
    order_table = 'order' if 'order' in tables else None
    if order_table:
        cols = [
            ('production_stage', 'TEXT'),
            ('order_type', 'TEXT DEFAULT "retail"'),
            ('due_date', 'DATETIME'),
            ('cost_of_goods', 'REAL'),
            ('profit', 'REAL'),
            ('is_refunded', 'BOOLEAN DEFAULT 0'),
            ('refund_notes', 'TEXT'),
        ]
        for col, typ in cols:
            try:
                c.execute(f'ALTER TABLE "{order_table}" ADD COLUMN {col} {typ}')
                print(f'  Added {order_table}.{col}')
            except sqlite3.OperationalError as e:
                if 'duplicate' in str(e).lower():
                    print(f'  {order_table}.{col} already exists')
                else:
                    print(f'  Error: {e}')
    
    if 'order_item' in tables:
        for col, typ in [('print_type', 'TEXT'), ('design_file_name', 'TEXT')]:
            try:
                c.execute(f'ALTER TABLE order_item ADD COLUMN {col} {typ}')
                print(f'  Added order_item.{col}')
            except sqlite3.OperationalError as e:
                if 'duplicate' in str(e).lower():
                    print(f'  order_item.{col} already exists')
                else:
                    print(f'  Error: {e}')
    
    if 'design' in tables:
        for col, typ in [('folder', 'TEXT'), ('sku', 'TEXT'), ('is_gallery', 'BOOLEAN DEFAULT 0'), ('title', 'TEXT')]:
            try:
                c.execute(f'ALTER TABLE design ADD COLUMN {col} {typ}')
                print(f'  Added design.{col}')
            except sqlite3.OperationalError as e:
                if 'duplicate' in str(e).lower():
                    print(f'  design.{col} already exists')
                else:
                    print(f'  Error: {e}')
    
    conn.commit()
    conn.close()
    print("  Done.")

print("Migration complete. Restart the app.")
