"""
Migrate products from local SQLite to Railway PostgreSQL.

Run locally with Railway's DATABASE_URL:
  1. In Railway: Postgres service -> Connect -> copy the DATABASE_URL
  2. Run: set DATABASE_URL=postgresql://... && python migrate_to_railway.py
     (or on Mac/Linux: DATABASE_URL=postgresql://... python migrate_to_railway.py)
"""
import os
import sys

# Local SQLite path
LOCAL_DB = os.path.join(os.path.dirname(__file__), 'apparel.db')
if not os.path.exists(LOCAL_DB):
    print(f"ERROR: Local database not found at {LOCAL_DB}")
    print("Make sure you're running this from the project root.")
    sys.exit(1)

railway_url = os.environ.get('DATABASE_URL')
if not railway_url:
    print("ERROR: DATABASE_URL not set.")
    print("Get it from Railway: Postgres service -> Connect -> DATABASE_URL")
    print("Then run: set DATABASE_URL=<paste-url> && python migrate_to_railway.py")
    sys.exit(1)

# Fix postgres:// -> postgresql://
if railway_url.startswith('postgres://'):
    railway_url = railway_url.replace('postgres://', 'postgresql://', 1)

print("Connecting to local SQLite...")
print("Connecting to Railway PostgreSQL...")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

local_engine = create_engine(f'sqlite:///{LOCAL_DB}')
railway_engine = create_engine(railway_url)

LocalSession = sessionmaker(bind=local_engine)
RailwaySession = sessionmaker(bind=railway_engine)

local = LocalSession()
railway = RailwaySession()

try:
    # Get products from local
    result = local.execute(text("""
        SELECT id, style_number, name, category, description, base_price, wholesale_cost,
               is_active, available_sizes, available_colors, front_mockup_template, back_mockup_template,
               print_area_config, brand, api_data, created_at, updated_at
        FROM product
    """))
    products = result.fetchall()
    
    if not products:
        print("No products found in local database.")
        sys.exit(0)
    
    print(f"Found {len(products)} products in local DB. Migrating...")
    
    # Get max id in Railway to avoid conflicts
    max_id = railway.execute(text("SELECT COALESCE(MAX(id), 0) FROM product")).scalar()
    id_offset = max_id
    
    for row in products:
        # Insert into Railway (skip if style_number exists)
        exists = railway.execute(
            text("SELECT 1 FROM product WHERE style_number = :sn"),
            {"sn": row.style_number}
        ).fetchone()
        if exists:
            print(f"  Skip (exists): {row.style_number}")
            continue
        
        railway.execute(text("""
            INSERT INTO product (style_number, name, category, description, base_price, wholesale_cost,
                is_active, available_sizes, available_colors, front_mockup_template, back_mockup_template,
                print_area_config, brand, api_data, created_at, updated_at)
            VALUES (:style_number, :name, :category, :description, :base_price, :wholesale_cost,
                :is_active, :available_sizes, :available_colors, :front_mockup_template, :back_mockup_template,
                :print_area_config, :brand, :api_data, :created_at, :updated_at)
        """), {
            "style_number": row.style_number, "name": row.name, "category": row.category,
            "description": row.description, "base_price": row.base_price, "wholesale_cost": row.wholesale_cost,
            "is_active": row.is_active or True, "available_sizes": row.available_sizes,
            "available_colors": row.available_colors, "front_mockup_template": row.front_mockup_template,
            "back_mockup_template": row.back_mockup_template, "print_area_config": row.print_area_config,
            "brand": row.brand, "api_data": row.api_data, "created_at": row.created_at, "updated_at": row.updated_at
        })
        print(f"  Migrated: {row.style_number} - {row.name}")
    
    # Migrate product_color_variant (if table exists locally)
    # First build style_number -> new id map
    id_map = {}
    for row in railway.execute(text("SELECT id, style_number FROM product")):
        id_map[row.style_number] = row.id
    
    try:
        result = local.execute(text("""
            SELECT product_id, color_name, color_hex, front_image_url, back_image_url, side_image_url,
                   size_inventory, ss_color_id, last_synced
            FROM product_color_variant
        """))
        variants = result.fetchall()
    except Exception:
        variants = []
        print("  (No color variants table or empty)")
    
    if variants:
        local_products = {r.id: r.style_number for r in local.execute(text("SELECT id, style_number FROM product")).fetchall()}
    
    for row in variants:
        style_num = local_products.get(row.product_id)
        if not style_num or style_num not in id_map:
            continue
        new_product_id = id_map[style_num]
        
        # Check if variant exists
        exists = railway.execute(text("""
            SELECT 1 FROM product_color_variant 
            WHERE product_id = :pid AND color_name = :cn
        """), {"pid": new_product_id, "cn": row.color_name}).fetchone()
        if exists:
            continue
        
        railway.execute(text("""
            INSERT INTO product_color_variant (product_id, color_name, color_hex, front_image_url, back_image_url,
                side_image_url, size_inventory, ss_color_id, last_synced)
            VALUES (:product_id, :color_name, :color_hex, :front_image_url, :back_image_url,
                :side_image_url, :size_inventory, :ss_color_id, :last_synced)
        """), {
            "product_id": new_product_id, "color_name": row.color_name, "color_hex": row.color_hex,
            "front_image_url": row.front_image_url, "back_image_url": row.back_image_url,
            "side_image_url": row.side_image_url, "size_inventory": row.size_inventory,
            "ss_color_id": row.ss_color_id, "last_synced": row.last_synced
        })
        print(f"  Variant: {style_num} / {row.color_name}")
    
    railway.commit()
    print(f"\nDone! Migrated {len(products)} products to Railway.")
    
except Exception as e:
    railway.rollback()
    print(f"ERROR: {e}")
    raise
finally:
    local.close()
    railway.close()
