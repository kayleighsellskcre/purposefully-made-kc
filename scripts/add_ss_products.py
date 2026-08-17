"""
add_ss_products.py
──────────────────
Adds MV Sport and C2 Sport products to the DB using the existing
S&S Activewear API integration. Fetches real color, size, and inventory
data from S&S, then stores it in product + product_color_variant tables.

Run from project root in Cursor terminal:

    py -3.12 scripts/add_ss_products.py --dry-run   # preview only
    py -3.12 scripts/add_ss_products.py             # insert / update
    py -3.12 scripts/add_ss_products.py --brand "MV Sport"  # one brand only

Requires: SSACTIVEWEAR_API_KEY + SSACTIVEWEAR_ACCOUNT_NUMBER in .env
"""

import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT DEFINITIONS
# (style_number, brand, wholesale_cost, base_price, description, is_favorite)
# Prices confirmed from S&S Activewear catalog / distributor sheets.
# ─────────────────────────────────────────────────────────────────────────────
PRODUCTS_TO_ADD = [

    # ── MV Sport ─────────────────────────────────────────────────────────────
    {
        'style_number': '17116',
        'brand': 'MV Sport',
        'wholesale_cost': 22.50,
        'base_price': 52.00,
        'description': (
            "MV Sport's Vintage Fleece Raglan Crewneck gives you that perfect worn-in, "
            "sporty look. The contrast raglan sleeves and vintage-wash fleece hit that "
            "sweet spot between athletic and lifestyle. Great for custom alumni gear, "
            "team spirit, and boutique collections."
        ),
        'is_customer_favorite': True,
    },
    {
        'style_number': 'W23716',
        'brand': 'MV Sport',
        'wholesale_cost': 20.00,
        'base_price': 46.00,
        'description': (
            "The MV Sport Women's Colorblocked Crop Hoodie blends sporty colorblocking "
            "with a trendy cropped silhouette. Super popular for women's group orders, "
            "athletic programs, and boutique custom apparel collections."
        ),
        'is_customer_favorite': False,
    },
    {
        'style_number': 'W25167',
        'brand': 'MV Sport',
        'wholesale_cost': 18.50,
        'base_price': 42.00,
        'description': (
            "MV Sport Women's Coastal Color Crewneck — a relaxed, fashion-forward "
            "sweatshirt with soft fleece and a versatile colorblocked look. Perfect for "
            "beach towns, resort wear, and boutique custom orders."
        ),
        'is_customer_favorite': False,
    },
    {
        'style_number': '496',
        'brand': 'MV Sport',
        'wholesale_cost': 18.00,
        'base_price': 42.00,
        'description': (
            "MV Sport Pro-Weave Crewneck — athletic-inspired crewneck with a soft "
            "smooth face and excellent print surface. A go-to for team and school "
            "spirit orders that want more style than a standard fleece crewneck."
        ),
        'is_customer_favorite': False,
    },

    # ── C2 Sport ─────────────────────────────────────────────────────────────
    {
        'style_number': '5100',
        'brand': 'C2 Sport',
        'wholesale_cost': 4.25,
        'base_price': 18.00,
        'description': (
            "C2 Sport Unisex Performance Tee — moisture-wicking, 100% polyester "
            "performance tee at a fraction of the cost of major brands. Perfect for "
            "runs, team sports, charity events, and any group order that needs "
            "athletic gear on a budget."
        ),
        'is_customer_favorite': False,
    },
    {
        'style_number': '5600',
        'brand': 'C2 Sport',
        'wholesale_cost': 4.25,
        'base_price': 18.00,
        'description': (
            "C2 Sport Women's Performance Tee — same moisture-wicking polyester "
            "as the 5100 in a fitted women's cut. Ideal for women's athletic "
            "programs, 5Ks, and school spirit apparel."
        ),
        'is_customer_favorite': False,
    },
    {
        'style_number': '5200',
        'brand': 'C2 Sport',
        'wholesale_cost': 4.00,
        'base_price': 16.00,
        'description': (
            "C2 Sport Youth Performance Tee — affordable youth-sized moisture-wicking "
            "tee for little athletes. Great for youth sports leagues, school spirit, "
            "and summer camp custom orders."
        ),
        'is_customer_favorite': False,
    },
    {
        'style_number': '5104',
        'brand': 'C2 Sport',
        'wholesale_cost': 6.50,
        'base_price': 24.00,
        'description': (
            "C2 Sport Unisex Performance Long Sleeve Tee — moisture-wicking long "
            "sleeve perfect for cooler weather training, fall events, and team "
            "warm-up gear on a budget."
        ),
        'is_customer_favorite': False,
    },
]


def build_product_record(api_data: dict, overrides: dict) -> dict:
    """
    Merge SSActivewearAPI.parse_style_to_product() output with our
    hardcoded overrides (price, description, brand, is_customer_favorite).
    """
    record = api_data.copy()

    # Always apply our controlled pricing & copy
    record['wholesale_cost'] = overrides['wholesale_cost']
    record['base_price'] = overrides['base_price']
    record['description'] = overrides['description']
    record['brand'] = overrides['brand']
    record['is_customer_favorite'] = overrides.get('is_customer_favorite', False)
    record['is_active'] = True

    return record


def upsert_product(db, Product, ProductColorVariant, record: dict, dry_run: bool) -> str:
    """Insert or update a product and its color variants. Returns 'added'/'updated'/'dry'."""
    style = record['style_number']
    color_variants = record.pop('color_variants', [])

    existing = Product.query.filter_by(style_number=style).first()

    if dry_run:
        action = 'UPDATE' if existing else 'ADD'
        colors = len(color_variants)
        print(f"  [DRY {action}] {style:12s}  {record['name']}")
        print(f"             {colors} colors  wholesale=${record['wholesale_cost']:.2f}  retail=${record['base_price']:.2f}")
        return 'dry'

    # Fields we allow on the Product model
    allowed = {
        'style_number', 'name', 'category', 'age_group', 'fit_type',
        'neck_style', 'sleeve_length', 'description', 'base_price',
        'wholesale_cost', 'available_sizes', 'available_colors',
        'is_active', 'is_customer_favorite', 'brand',
        'front_mockup_template', 'back_mockup_template',
        'size_chart', 'fit_guide', 'fabric_details', 'api_data',
    }
    product_fields = {k: v for k, v in record.items() if k in allowed}

    if existing:
        for k, v in product_fields.items():
            setattr(existing, k, v)
        product = existing
        action = 'updated'
    else:
        product = Product(**product_fields)
        db.session.add(product)
        db.session.flush()  # get product.id
        action = 'added'

    # Upsert color variants
    for cv in color_variants:
        color_name = cv.get('color_name', '')
        if not color_name:
            continue

        existing_cv = ProductColorVariant.query.filter_by(
            product_id=product.id,
            color_name=color_name
        ).first()

        cv_fields = {
            'product_id': product.id,
            'color_name': color_name,
            'ss_color_id': str(cv.get('color_id', '') or ''),
            'front_image_url': cv.get('front_image'),
            'back_image_url': cv.get('back_image'),
            'side_image_url': cv.get('side_image'),
            'size_inventory': cv.get('size_inventory'),
        }

        if existing_cv:
            for k, v in cv_fields.items():
                setattr(existing_cv, k, v)
        else:
            db.session.add(ProductColorVariant(**cv_fields))

    print(f"  [{action.upper():7s}] {style:12s}  {record['name']}")
    print(f"             {len(color_variants)} colors  wholesale=${record['wholesale_cost']:.2f}  retail=${record['base_price']:.2f}")
    return action


def main():
    parser = argparse.ArgumentParser(description='Add MV Sport + C2 Sport products via S&S API')
    parser.add_argument('--dry-run', action='store_true', help='Preview only — no DB writes')
    parser.add_argument('--brand', default=None, help='Only process this brand (e.g. "MV Sport")')
    args = parser.parse_args()

    # ── App context ───────────────────────────────────────────────────────────
    from app import create_app
    from models import db, Product, ProductColorVariant
    from services.ssactivewear_api import SSActivewearAPI

    app = create_app()
    with app.app_context():
        try:
            api = SSActivewearAPI()
        except ValueError as e:
            print(f"\nERROR: {e}")
            print("Make sure SSACTIVEWEAR_API_KEY and SSACTIVEWEAR_ACCOUNT_NUMBER are in .env")
            sys.exit(1)

        products_to_process = PRODUCTS_TO_ADD
        if args.brand:
            products_to_process = [p for p in PRODUCTS_TO_ADD if p['brand'] == args.brand]
            print(f"\nFiltering to brand: {args.brand} ({len(products_to_process)} styles)")

        print(f"\n{'DRY RUN — ' if args.dry_run else ''}Processing {len(products_to_process)} styles from S&S API...\n")

        added = updated = skipped = errors = 0

        for item in products_to_process:
            style_number = item['style_number']
            print(f"\n── {item['brand']} {style_number} ──────────────────────────────────────")

            try:
                # Fetch full style data from S&S API
                style_data = api.fetch_style_data_by_style_number(style_number)

                if not style_data:
                    print(f"  [ERROR] Style {style_number} not found in S&S API — skipping")
                    errors += 1
                    continue

                n_colors = len(style_data.get('color_variants', []))
                n_sizes = len(style_data.get('sizes', []))
                print(f"  Found: {n_colors} colors, {n_sizes} sizes")

                # Parse to our Product format
                parsed = api.parse_style_to_product(style_data)

                # Apply our controlled overrides
                record = build_product_record(parsed, item)

                # Insert / update
                result = upsert_product(db, Product, ProductColorVariant, record, args.dry_run)

                if result == 'added':
                    added += 1
                elif result == 'updated':
                    updated += 1
                elif result == 'dry':
                    pass  # dry run, count separately

            except Exception as e:
                print(f"  [ERROR] {style_number}: {e}")
                import traceback
                traceback.print_exc()
                errors += 1
                continue

        # Commit all at once
        if not args.dry_run:
            db.session.commit()
            print(f"\n{'─'*60}")
            print(f"Done!  Added: {added}  Updated: {updated}  Errors: {errors}")
            print("\nNext step: images are pulled from the S&S CDN automatically via the")
            print("front_image_url / back_image_url stored in product_color_variant.")
            print("No separate image download step needed — they reference S&S CDN directly.")
        else:
            print(f"\n{'─'*60}")
            print("[DRY RUN] No changes made. Remove --dry-run to apply.")


if __name__ == '__main__':
    main()
