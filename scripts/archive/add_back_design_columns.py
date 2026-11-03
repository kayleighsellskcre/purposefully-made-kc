#!/usr/bin/env python3
"""
scripts/add_back_design_columns.py

Adds allow_back_design and back_design_type columns to the collection table.
Run once from Cursor terminal:

  python scripts/add_back_design_columns.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from app import app
from models import db

with app.app_context():
    with db.engine.connect() as conn:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        cols = {c['name'] for c in inspector.get_columns('collection')}

        added = []
        if 'allow_back_design' not in cols:
            conn.execute(text(
                "ALTER TABLE collection ADD COLUMN allow_back_design BOOLEAN DEFAULT TRUE"
            ))
            added.append('allow_back_design')

        if 'back_design_type' not in cols:
            conn.execute(text(
                "ALTER TABLE collection ADD COLUMN back_design_type VARCHAR(20) DEFAULT 'both'"
            ))
            added.append('back_design_type')

        conn.commit()

    if added:
        print(f"Added columns: {', '.join(added)}")
    else:
        print("Columns already exist — nothing to do.")
