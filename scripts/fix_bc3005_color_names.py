"""Give BC3005's run-together color names proper spelling (blackheather -> Black Heather, ...).

Dry run by default; pass --apply to write. Renames the color on the product's color variants and in its
Available colors list only. Orders keep the color text they were placed with. Matching ignores spaces and
case, so inventory and mockup lookups keep working.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RENAMES = {
    'blackheather': 'Black Heather', 'blackmarble': 'Black Marble',
    'heathergrassgreen': 'Heather Grass Green', 'heathernavy': 'Heather Navy',
    'heatherred': 'Heather Red', 'heatherslate': 'Heather Slate',
    'heathertrueroyal': 'Heather True Royal', 'maroonmarble': 'Maroon Marble',
    'stonemarble': 'Stone Marble', 'whitemarble': 'White Marble', 'whiteslub': 'White Slub',
}


def fix_names(product, variants, apply=False):
    """Return [(old, new)] renames for this product; writes them only when apply is true."""
    from utils.json_fields import parse_json_list
    changes = []
    taken = {v.color_name.lower() for v in variants}
    for v in variants:
        new = RENAMES.get((v.color_name or '').strip().lower())
        if new and new.lower() not in taken:
            changes.append((v.color_name, new))
            if apply:
                v.color_name = new
    colors = parse_json_list(product.available_colors)
    fixed = [RENAMES.get(c.strip().lower(), c) for c in colors]
    if fixed != colors:
        if apply:
            product.available_colors = json.dumps(fixed)
    return changes


def main():
    apply = '--apply' in sys.argv
    from flask import Flask
    from config import Config
    from models import Product, ProductColorVariant, db
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    with app.app_context():
        product = Product.query.options(db.defer(Product.supplier_hidden_colors), db.defer(Product.supplier_sold_out_sizes)).filter_by(style_number='BC3005').first()
        if not product:
            print('BC3005 not found')
            return 1
        variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
        for old, new in fix_names(product, variants, apply):
            print(f'  {old!r} -> {new!r}')
        if apply:
            db.session.commit()
            print('Saved.')
        else:
            print('Dry run only. Nothing saved. Add --apply to write.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
