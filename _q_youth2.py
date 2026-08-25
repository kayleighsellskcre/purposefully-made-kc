from dotenv import load_dotenv
import os, re
import psycopg2
import psycopg2.extras

load_dotenv()
url = os.environ["DATABASE_URL"]
print("DB:", re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url))
conn = psycopg2.connect(url)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def cols(table):
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position",
        (table,),
    )
    return list(cur.fetchall())

print("product cols:")
for c in cols("product"):
    print(" ", c["column_name"], c["data_type"])
print("product_color_variant cols:")
for c in cols("product_color_variant"):
    print(" ", c["column_name"], c["data_type"])

cur.execute("SELECT * FROM product WHERE id=%s", (336,))
p = cur.fetchone()
print("\n=== PRODUCT 336 ===")
if p:
    for k, v in dict(p).items():
        print(f"  {k}: {v}")
else:
    print("  NOT FOUND by id")

cur.execute("SELECT id, style_id, name, brand, category, active, base_price FROM product WHERE style_id ILIKE %s OR name ILIKE %s OR CAST(id AS text)=%s", ("%3945Y%", "%3945Y%", "336"))
print("\n=== product search 3945Y / 336 ===")
# may fail if columns wrong - catch
