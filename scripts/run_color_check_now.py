"""Run the supplier color/size check once, now, against the database in .env (the live one on this computer's setup).

Adds the two new product columns if they are missing (the site does the same on startup), asks SanMar and S&S about
every active style, and saves which colors and sizes to hide. Prices, stock numbers, orders and carts are not touched.
No email is sent from here; tomorrow's 4:30 AM run emails only what changes after this.

    python scripts/run_color_check_now.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask
from sqlalchemy import text

from config import Config
from models import db


def main():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    with app.app_context():
        for sql in (
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS supplier_hidden_colors TEXT",
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS supplier_sold_out_sizes TEXT",
        ):
            db.session.execute(text(sql))
        db.session.commit()
        from services.color_availability import run_color_check
        result = run_color_check(notify=False)
        print(f"Styles checked: {result['checked']}; unchecked (nothing hidden): {result['unchecked']}")
        print(f"Colors now hidden: {sum(len(v) for v in result['newly_hidden'].values())} "
              f"across {len(result['newly_hidden'])} styles")
        print(f"Sizes sold out: {sum(len(v) for v in result['sizes_out'].values())}")
        for style, names in sorted(result['newly_hidden'].items()):
            print(f"  {style}: {', '.join(names)}")


if __name__ == '__main__':
    main()
