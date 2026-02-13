"""
Add brand and api_data columns directly using SQL
This bypasses any Python caching issues
"""
import sqlite3
import os

db_path = 'apparel.db'

if not os.path.exists(db_path):
    print(f"Error: Database file '{db_path}' not found")
    print("Run: .\\venv\\Scripts\\flask init-db")
    exit(1)

print(f"Opening database: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check current columns
cursor.execute("PRAGMA table_info(product)")
columns = [row[1] for row in cursor.fetchall()]
print(f"\nCurrent columns: {', '.join(columns)}")

# Add brand column if missing
if 'brand' not in columns:
    try:
        cursor.execute("ALTER TABLE product ADD COLUMN brand VARCHAR(100)")
        print("[+] Added 'brand' column")
    except Exception as e:
        print(f"[!] Could not add 'brand': {e}")
else:
    print("[=] 'brand' column already exists")

# Add api_data column if missing
if 'api_data' not in columns:
    try:
        cursor.execute("ALTER TABLE product ADD COLUMN api_data TEXT")
        print("[+] Added 'api_data' column")
    except Exception as e:
        print(f"[!] Could not add 'api_data': {e}")
else:
    print("[=] 'api_data' column already exists")

conn.commit()

# Verify
cursor.execute("PRAGMA table_info(product)")
columns = [row[1] for row in cursor.fetchall()]
print(f"\nUpdated columns: {', '.join(columns)}")

if 'brand' in columns and 'api_data' in columns:
    print("\n[SUCCESS] Database updated successfully!")
    print("Restart Flask server: .\\venv\\Scripts\\python app.py")
else:
    print("\n[ERROR] Some columns still missing")

conn.close()
