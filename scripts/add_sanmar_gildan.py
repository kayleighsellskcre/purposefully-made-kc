"""
add_sanmar_gildan.py
────────────────────
Adds two missing Gildan Softstyle styles from SanMar to the database:
  - G64500  Gildan Softstyle V-Neck Tee
  - G64400  Gildan Softstyle Long Sleeve Tee

These complement the existing G64000 (Softstyle Crew), G18500 (Hoodie),
and G18000 (Crewneck Sweatshirt) already in the catalog.

Run from project root in Cursor terminal:

    py -3.12 scripts/add_sanmar_gildan.py --dry-run   # preview only
    py -3.12 scripts/add_sanmar_gildan.py             # insert

After running, populate images by running:
    py -3.12 scripts/populate_brand_images.py --brands Gildan --cookie "YOUR_JSESSIONID"
"""

import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

ADULT_SIZES    = json.dumps(["S", "M", "L", "XL", "2XL", "3XL"])
ADULT_SIZES_XS = json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL"])

NEW_GILDAN = [
    {
        'style_number': 'G64500',
        'name': 'Gildan Softstyle V-Neck Tee',
        'brand': 'Gildan',
        'category': 'V-Neck Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'V-Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 22.00,
        'wholesale_cost': 5.98,
        'available_sizes': ADULT_SIZES,
        'description': (
            "Gildan Softstyle V-Neck Tee — the same ring-spun cotton softness as the "
            "G64000 crew, in a classic V-neck silhouette. A great budget-friendly "
            "option for customers who prefer a V-neck without sacrificing comfort."
        ),
        'fabric_details': '4.5 oz / 100% ring-spun cotton; Softstyle jersey',
        'fit_guide': 'Unisex classic fit; runs true to size.',
        'spec_sheet_url': 'https://www.sanmar.com/p/G64500',
        'is_active': True,
        'is_customer_favorite': False,
    },
    {
        'style_number': 'G64400',
        'name': 'Gildan Softstyle Long Sleeve Tee',
        'brand': 'Gildan',
        'category': 'Long Sleeve',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'base_price': 24.00,
        'wholesale_cost': 6.98,
        'available_sizes': ADULT_SIZES,
        'description': (
            "Gildan Softstyle Long Sleeve Tee — everything customers love about the "
            "G64000, extended to a full long sleeve. Ring-spun cotton that's noticeably "
            "softer than standard Gildan. Perfect for fall and winter group orders, "
            "school spirit, and events that need an affordable long sleeve option."
        ),
        'fabric_details': '4.5 oz / 100% ring-spun cotton; Softstyle jersey',
        'fit_guide': 'Unisex classic fit; runs true to size.',
        'spec_sheet_url': 'https://www.sanmar.com/p/G64400',
        'is_active': True,
        'is_customer_favorite': False,
    },
]


def main():
    parser = argparse.ArgumentParser(description='Add Gildan G64500 + G64400 from SanMar')
    parser.add_argument('--dry-run', action='store_true', help='Preview only — no DB writes')
    args = parser.parse_args()

    from app import create_app
    from models import db, Product

    app = create_app()
    with app.app_context():
        added = skipped = 0

        print(f"\n{'DRY RUN — ' if args.dry_run else ''}Adding {len(NEW_GILDAN)} Gildan Softstyle styles...\n")

        for data in NEW_GILDAN:
            style = data['style_number']
            existing = Product.query.filter_by(style_number=style).first()

            if existing:
                print(f"  SKIP  {style:12s}  already in DB — run update_product_data.py to refresh pricing")
                skipped += 1
                continue

            print(f"  ADD   {style:12s}  {data['name']}")
            print(f"         wholesale=${data['wholesale_cost']:.2f}  retail=${data['base_price']:.2f}")
            added += 1

            if not args.dry_run:
                db.session.add(Product(**data))

        print(f"\nTotal: {added} to add, {skipped} already exist.")

        if args.dry_run:
            print("\n[DRY RUN] No changes made. Remove --dry-run to apply.")
            return

        db.session.commit()
        print("\nDone! Both Gildan Softstyle styles added to database.")
        print("\nNext steps:")
        print("  1. Get a fresh SanMar JSESSIONID cookie (log in to medialibrary1.com)")
        print("  2. Run: py -3.12 scripts/populate_brand_images.py --brands Gildan --cookie \"YOUR_JSESSIONID\"")
        print("     to pull front/back flat-lay images from SanMar Media Library.")


if __name__ == '__main__':
    main()
