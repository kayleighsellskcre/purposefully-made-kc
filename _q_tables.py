from dotenv import load_dotenv
import os, re
import psycopg2
import psycopg2.extras

load_dotenv()
url = os.environ["DATABASE_URL"]
print("DB:", re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url))
conn = psycopg2.connect(url)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("""
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema')
ORDER BY table_schema, table_name
""")
for r in cur.fetchall():
    print(f"{r['table_schema']}.{r['table_name']}")
