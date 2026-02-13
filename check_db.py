import sqlite3
import os
from config import Config
db_uri = Config.SQLALCHEMY_DATABASE_URI
path = db_uri.replace('sqlite:///', '')
print('DB path:', path, 'exists:', os.path.exists(path))
conn = sqlite3.connect(path)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', [r[0] for r in c.fetchall()])
c.execute("PRAGMA table_info(collection)")
print('Collection columns:', c.fetchall())
