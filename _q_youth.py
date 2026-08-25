from dotenv import load_dotenv
import os, re, json
import psycopg2
import psycopg2.extras

load_dotenv()
url = os.environ["DATABASE_URL"]
print("DB:", re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url))
conn = psycopg2.connect(url)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def cols(table):
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position",
        (table,),
    )
    return [r["column_name"] for r in cur.fetchall()]

print("products cols:", cols("products"))
print("product_color_variants cols:", cols("product_color_variants"))
print("collection_products cols:", cols("collection_products"))

# Product 336
cur.execute("SELECT * FROM products WHERE id=%s", (336,))
p = cur.fetchone()
print("\n=== PRODUCT 336 ===")
if p:
    for k, v in dict(p).items():
        print(f"  {k}: {v}")
else:
    print("  NOT FOUND")

# Also by style
cur.execute("SELECT id, style_number, name, slug, brand, category, is_active, base_price, image_url, front_image_url, back_image_url FROM products WHERE style_number ILIKE %s OR style_number ILIKE %s OR name ILIKE %s", ("%3945Y%", "%BC3945Y%", "%3945Y%"))
print("\n=== products matching 3945Y ===")
for r in cur.fetchall():
    print(dict(r))

cur.execute("SELECT * FROM product_color_variants WHERE product_id=%s ORDER BY id", (336,))
rows = cur.fetchall()
print(f"\n=== product_color_variants for 336 (count={len(rows)}) ===")
for r in rows:
    print(dict(r))

cur.execute("SELECT * FROM collection_products WHERE collection_id=%s AND product_id=%s", (8, 336))
cp = cur.fetchall()
print(f"\n=== collection_products collection=8 product=336 (count={len(cp)}) ===")
for r in cp:
    print(dict(r))

cur.execute("SELECT * FROM collection_products WHERE product_id=%s", (336,))
print("\n=== all collection_products for 336 ===")
for r in cur.fetchall():
    print(dict(r))

# Adult BC3945
cur.execute("""
SELECT id, style_number, name, brand
FROM products
WHERE style_number ILIKE %s OR style_number ILIKE %s OR name ILIKE %s
ORDER BY id
""", ("%3945%", "%BC3945%", "%BC3945%"))
print("\n=== products matching 3945 / BC3945 ===")
for r in cur.fetchall():
    print(dict(r))

cur.execute("""
SELECT p.id as product_id, p.style_number, v.id as variant_id, v.color_name, v.front_image_url, v.back_image_url
FROM products p
JOIN product_color_variants v ON v.product_id = p.id
WHERE p.style_number ILIKE %s OR p.style_number = %s OR p.style_number ILIKE %s
ORDER BY p.id, v.id
LIMIT 5
""", ("%BC3945%", "3945", "%3945"))
# refine below
