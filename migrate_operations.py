"""Migrate database for operations system - adds new columns and tables."""
import sqlite3
import os

basedir = os.path.dirname(os.path.abspath(__file__))
# Use same path as Flask app - check env and both possible locations
db_uri = os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(basedir, 'apparel.db')
db_path = db_uri.replace('sqlite:///', '')
if not os.path.isabs(db_path):
    db_path = os.path.join(basedir, db_path)
# Also try instance folder (Flask default)
DB_PATHS = [db_path, os.path.join(basedir, 'apparel.db'), os.path.join(basedir, 'instance', 'apparel.db')]

def migrate():
    migrated = False
    for DB_PATH in DB_PATHS:
        if not os.path.exists(DB_PATH):
            continue
        print(f'Migrating {DB_PATH}...')
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in c.fetchall()]

        order_table = 'order' if 'order' in tables else None
        if not order_table:
            for t in tables:
                if 'order' in t.lower():
                    order_table = t
                    break

        if order_table:
            cols = {'production_stage': 'TEXT', 'order_type': 'TEXT DEFAULT "retail"',
                    'due_date': 'DATETIME', 'cost_of_goods': 'REAL', 'profit': 'REAL',
                    'is_refunded': 'BOOLEAN DEFAULT 0', 'refund_notes': 'TEXT'}
            for col, typ in cols.items():
                try:
                    c.execute(f'ALTER TABLE "{order_table}" ADD COLUMN {col} {typ}')
                    print(f'  Added {order_table}.{col}')
                except sqlite3.OperationalError as e:
                    if 'duplicate column' in str(e).lower():
                        print(f'  {order_table}.{col} already exists')
                    else:
                        raise

        if 'order_item' in tables:
            for col, typ in [('print_type', 'TEXT'), ('design_file_name', 'TEXT')]:
                try:
                    c.execute(f'ALTER TABLE order_item ADD COLUMN {col} {typ}')
                    print(f'  Added order_item.{col}')
                except sqlite3.OperationalError as e:
                    if 'duplicate column' in str(e).lower():
                        print(f'  order_item.{col} already exists')
                    else:
                        raise

        if 'design' in tables:
            for col, typ in [('folder', 'TEXT'), ('sku', 'TEXT')]:
                try:
                    c.execute(f'ALTER TABLE design ADD COLUMN {col} {typ}')
                    print(f'  Added design.{col}')
                except sqlite3.OperationalError as e:
                    if 'duplicate column' in str(e).lower():
                        print(f'  design.{col} already exists')
                    else:
                        raise

        conn.commit()
        conn.close()
        migrated = True
    if not migrated:
        print('No database found. Will create via create_all().')
    else:
        print('Column migration complete.')

def create_new_tables():
    """Create new tables via Flask-SQLAlchemy"""
    from app import create_app
    from models import db
    app = create_app()
    with app.app_context():
        db.create_all()
        print('All tables created/updated.')

if __name__ == '__main__':
    print('Running operations migration...')
    migrate()
    create_new_tables()
    print('Done!')
