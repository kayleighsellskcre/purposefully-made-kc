"""
Rebuild database with color variant support
"""
import os
import shutil
from app import create_app
from models import db, User, Product, ProductColorVariant
from werkzeug.security import generate_password_hash

print("="*80)
print("REBUILDING DATABASE WITH COLOR VARIANT SUPPORT")
print("="*80)

# 1. Delete old database
db_path = 'apparel.db'
if os.path.exists(db_path):
    print(f"Deleting old database: {db_path}")
    os.remove(db_path)

# 2. Delete pycache directories
print("Cleaning __pycache__ directories...")
for root, dirs, files in os.walk('.'):
    if '__pycache__' in dirs:
        pycache_path = os.path.join(root, '__pycache__')
        print(f"  Removing: {pycache_path}")
        shutil.rmtree(pycache_path, ignore_errors=True)

# 3. Create new database with all tables
app = create_app()
with app.app_context():
    print("\nCreating fresh database...")
    db.drop_all()  # Just in case
    db.create_all()
    print("SUCCESS: Database created with ALL tables including product_color_variant!")
    
    # Verify tables exist
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f"\nTables created: {', '.join(tables)}")
    
    # Check product_color_variant table structure
    if 'product_color_variant' in tables:
        columns = [col['name'] for col in inspector.get_columns('product_color_variant')]
        print(f"\nproduct_color_variant columns: {', '.join(columns)}")
    
    # 4. Create admin user
    print("\nCreating admin user...")
    admin = User(
        email='kayleighsellskcre@gmail.com',
        first_name='Admin',
        last_name='User',
        is_admin=True
    )
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()
    print(f"SUCCESS: Admin user created: {admin.email}")

print("\n" + "="*80)
print("DATABASE REBUILD COMPLETE!")
print("="*80)
print("\nNext steps:")
print("1. Start server: python app.py")
print("2. Login at http://localhost:5000/login")
print("   Email: kayleighsellskcre@gmail.com")
print("   Password: admin123")
print("3. Go to Admin > Products")
print("4. Click 'Sync from S&S Activewear'")
print("5. Watch as products sync WITH color variants, mockups, and inventory! 🚀")
print("="*80)
