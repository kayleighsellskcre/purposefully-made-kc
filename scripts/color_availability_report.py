"""READ-ONLY report: how many shop colors each style would lose if the shop only showed colors the
supplier (SanMar / S&S) carries with stock. Changes nothing. Writes a JSON copy next to the printout.

    python scripts/color_availability_report.py [out.json]
"""
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask
from config import Config
from models import Product, ProductColorVariant, db


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    rows = []
    with app.app_context():
        from services.color_availability import unavailable_colors
        ss_client = None
        if os.getenv('SSACTIVEWEAR_API_KEY') and os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER'):
            from services.ssactivewear_api import SSActivewearAPI
            ss_client = SSActivewearAPI()
        products = Product.query.options(db.defer(Product.supplier_hidden_colors), db.defer(Product.supplier_sold_out_sizes)).filter_by(is_active=True).order_by(Product.brand, Product.style_number).all()
        by_product = {}
        for v in ProductColorVariant.query.all():
            by_product.setdefault(v.product_id, []).append(v)
        for p in products:
            res = unavailable_colors(p, ss_client=ss_client, variants=by_product.get(p.id, []))
            rows.append({'style': p.style_number, 'brand': p.brand, 'supplier': res['supplier'],
                         'colors': res['checked'], 'hidden': res['hidden']})
            print(f"{p.style_number:14} {str(p.brand)[:18]:18} {str(res['supplier']):7} "
                  f"{res['checked']:3} colors, {len(res['hidden']):3} would hide", flush=True)
    lost = sum(len(r['hidden']) for r in rows)
    affected = sum(1 for r in rows if r['hidden'])
    unchecked = [r['style'] for r in rows if not r['supplier']]
    print(f"\nTOTAL: {lost} colors across {affected} of {len(rows)} styles; "
          f"{len(unchecked)} styles unchecked (supplier returned nothing, nothing hidden)")
    if out_path:
        Path(out_path).write_text(json.dumps(rows, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
