"""Add custom_design_request table - run once: python migrate_custom_design_request.py"""
import sqlite3
import os

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'instance', 'apparel.db')
if not os.path.exists(db_path):
    db_path = os.path.join(basedir, 'apparel.db')
if not os.path.exists(db_path):
    print("Database not found. Run the app first to create it.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check if table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_design_request'")
if cursor.fetchone():
    print("custom_design_request table already exists.")
    conn.close()
    exit(0)

cursor.execute("""
CREATE TABLE custom_design_request (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    reference_file_path VARCHAR(500) NOT NULL,
    reference_original_filename VARCHAR(500),
    description TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_design_id INTEGER,
    admin_notes TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    FOREIGN KEY(user_id) REFERENCES user (id),
    FOREIGN KEY(created_design_id) REFERENCES design (id)
)
""")
conn.commit()
conn.close()
print("✓ custom_design_request table created.")
