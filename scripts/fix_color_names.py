"""
fix_color_names.py
──────────────────
Fixes corrupted/abbreviated color names in the product_color_variant table.
Run from project root in Cursor terminal:
    py -3.12 scripts/fix_color_names.py --dry-run
    py -3.12 scripts/fix_color_names.py
"""

import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

# Known bad → good mappings
COLOR_NAME_FIXES = {
    'hthr':           'Heather',
    'ath hthr':       'Athletic Heather',
    'dk hthr':        'Dark Heather',
    'v hthr':         'Vintage Heather',
    'hthr gry':       'Heather Grey',
    'hthr navy':      'Heather Navy',
    'hthr blue':      'Heather Blue',
    'hthr grn':       'Heather Green',
    'dkhthr':         'Dark Heather',
    'charcoal hthr':  'Charcoal Heather',
    's grey':         'Sport Grey',
}

import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    from app import create_app
    from models import db, ProductColorVariant

    app = create_app()
    with app.app_context():
        mode = 'DRY RUN' if args.dry_run else 'LIVE'
        print(f"\n{'='*50}")
        print(f"  Fix Color Names — {mode}")
        print(f"{'='*50}\n")

        total_fixed = 0
        for bad, good in COLOR_NAME_FIXES.items():
            variants = ProductColorVariant.query.filter(
                ProductColorVariant.color_name.ilike(bad)
            ).all()
            if not variants:
                continue
            print(f"  '{bad}' → '{good}': {len(variants)} variant(s)")
            if not args.dry_run:
                for v in variants:
                    # Check if good name already exists for this product to avoid duplicates
                    existing = ProductColorVariant.query.filter_by(
                        product_id=v.product_id,
                        color_name=good
                    ).first()
                    if existing:
                        print(f"    [SKIP] product_id={v.product_id} already has '{good}'")
                        continue
                    v.color_name = good
                    total_fixed += 1
            else:
                total_fixed += len(variants)

        if not args.dry_run:
            db.session.commit()

        print(f"\n{'DRY RUN: would fix' if args.dry_run else 'Fixed'} {total_fixed} color name(s).")
        if args.dry_run:
            print("Remove --dry-run to apply.\n")

if __name__ == '__main__':
    main()
