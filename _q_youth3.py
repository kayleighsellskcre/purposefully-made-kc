from dotenv import load_dotenv
import os, re
import psycopg2
import psycopg2.extras

load_dotenv()
url = os.environ["DATABASE_URL"]
print("DB:", re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url))
conn = psycopg2.connect(url)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("SELECT * FROM product_color_variant WHERE product_id=%s ORDER BY id", (336,))
rows = cur.fetchall()
print(f"\n=== ALL product_color_variant for 336 (n={len(rows)}) ===")
for r in rows:
    d = dict(r)
    print("---")
    for k,v in d.items():
        print(f"  {k}: {v}")

cur.execute("SELECT * FROM collection_products WHERE collection_id=%s AND product_id=%s", (8, 336))
cp = cur.fetchall()
print(f"\n=== collection_products collection_id=8 product_id=336 (n={len(cp)}) ===")
for r in cp:
    print(dict(r))

cur.execute("SELECT collection_id, product_id FROM collection_products WHERE product_id=%s", (336,))
print("\n=== all collections containing 336 ===")
for r in cur.fetchall():
    print(dict(r))

cur.execute("SELECT id, name FROM collection ORDER BY id")
print("\n=== collections ===")
for r in cur.fetchall():
    print(dict(r))

# Adult BC3945
cur.execute("""
SELECT id, style_number, name, brand, age_group, category, is_active, base_price
FROM product
WHERE style_number ILIKE %s OR style_number ILIKE %s
ORDER BY id
""", ("%3945%", "%BC3945%"))
print("\n=== products matching *3945* ===")
for r in cur.fetchall():
    print(dict(r))

# Adult BC3901
cur.execute("""
SELECT id, style_number, name, brand, age_group, category, is_active, base_price
FROM product
WHERE style_number ILIKE %s OR style_number ILIKE %s
ORDER BY id
""", ("%3901%", "%BC3901%"))
print("\n=== products matching *3901* ===")
for r in cur.fetchall():
    print(dict(r))

# Sample front_image_url for adult BC3945 (not youth)
cur.execute("""
SELECT p.id as product_id, p.style_number, p.age_group, v.id as variant_id, v.color_name, v.front_image_url, v.back_image_url
FROM product p
JOIN product_color_variant v ON v.product_id = p.id
WHERE p.style_number IN ('BC3945','3945') OR (p.style_number ILIKE '%3945%' AND (p.age_group IS NULL OR p.age_group ILIKE 'adult' OR p.age_group NOT ILIKE 'youth'))
ORDER BY p.id, v.id
LIMIT 8
""")
print("\n=== Adult BC3945 variant sample front_image_url ===")
for r in cur.fetchall():
    print(dict(r))

# More precise: style_number exactly BC3945 or 3945 without Y
cur.execute("""
SELECT p.id, p.style_number, p.age_group, p.name FROM product p
WHERE p.style_number IN ('BC3945','3945','Bella Canvas 3945') OR replace(p.style_number,' ','') ILIKE 'BC3945'
""")
print("\n=== exact adult 3945 candidates ===")
for r in cur.fetchall():
    print(dict(r))

cur.execute("""
SELECT p.id as product_id, p.style_number, p.age_group, v.color_name, v.front_image_url
FROM product p
JOIN product_color_variant v ON v.product_id = p.id
WHERE p.style_number = 'BC3945' OR (p.style_number = '3945')
ORDER BY v.id LIMIT 5
""")
print("\n=== BC3945 / 3945 samples ===")
for r in cur.fetchall():
    print(dict(r))

cur.execute("""
SELECT p.id as product_id, p.style_number, p.age_group, v.color_name, v.front_image_url
FROM product p
JOIN product_color_variant v ON v.product_id = p.id
WHERE p.style_number = 'BC3901' OR p.style_number = '3901'
ORDER BY v.id LIMIT 5
""")
print("\n=== BC3901 / 3901 samples ===")
for r in cur.fetchall():
    print(dict(r))

# If style has brand prefix differently
cur.execute("""
SELECT id, style_number, age_group, name FROM product
WHERE style_number ~* '3945' AND style_number !~* 'Y'
ORDER BY id
""")
print("\n=== style ~ 3945 without Y ===")
for r in cur.fetchall():
    print(dict(r))

cur.execute("""
SELECT id, style_number, age_group, name FROM product
WHERE style_number ~* '3901' AND style_number !~* 'Y'
ORDER BY id
""")
print("\n=== style ~ 3901 without Y ===")
for r in cur.fetchall():
    print(dict(r))
