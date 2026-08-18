"""Refresh live SanMar + S&S warehouse quantities into the shop catalog."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask
from config import Config
from models import db


def main():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    with app.app_context():
        from services.inventory_sync import sync_all_inventory
        stats = sync_all_inventory()
        print(stats)
        return 0 if stats.get('errors', 0) == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
