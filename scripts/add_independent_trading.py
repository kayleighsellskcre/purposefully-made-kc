"""
add_independent_trading.py
──────────────────────────
Adds Independent Trading Co. adult / youth / toddler fleece styles via S&S.

    py -3.12 scripts/add_independent_trading.py --dry-run
    py -3.12 scripts/add_independent_trading.py
"""

import os
import sys
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

BRAND = 'Independent Trading Co.'

PRODUCTS_TO_ADD = [
    # Standard Supply — Adult + Youth
    {
        'style_number': 'SS3000',
        'style_id': 2771,
        'base_price': 38.00,
        'category': 'Sweatshirt',
        'age_group': 'adult',
    },
    {
        'style_number': 'SS3001Y',
        'style_id': 16945,
        'base_price': 34.00,
        'category': 'Sweatshirt',
        'age_group': 'youth',
    },
    {
        'style_number': 'SS4500',
        'style_id': 1828,
        'base_price': 45.00,
        'category': 'Hoodie',
        'age_group': 'adult',
    },
    {
        'style_number': 'SS4001Y',
        'style_id': 3692,
        'base_price': 40.00,
        'category': 'Hoodie',
        'age_group': 'youth',
    },
    {
        'style_number': 'SS4500Z',
        'style_id': 1829,
        'base_price': 50.00,
        'category': 'Hoodie',
        'age_group': 'adult',
    },
    {
        'style_number': 'SS4001YZ',
        'style_id': 3693,
        'base_price': 45.00,
        'category': 'Hoodie',
        'age_group': 'youth',
    },
    # Special Blend — Adult + Youth + Toddler
    {
        'style_number': 'PRM33SBP',
        'style_id': 3304,
        'base_price': 48.00,
        'category': 'Hoodie',
        'age_group': 'adult',
    },
    {
        'style_number': 'PRM15YSB',
        'style_id': 4235,
        'base_price': 44.00,
        'category': 'Hoodie',
        'age_group': 'youth',
    },
    {
        'style_number': 'PRM10TSB',
        'style_id': 4233,
        'base_price': 40.00,
        'category': 'Hoodie',
        'age_group': 'toddler',
    },
    {
        'style_number': 'PRM30SBC',
        'style_id': 3303,
        'base_price': 44.00,
        'category': 'Sweatshirt',
        'age_group': 'adult',
    },
    {
        'style_number': 'PRM15YSBC',
        'style_id': 12353,
        'base_price': 40.00,
        'category': 'Sweatshirt',
        'age_group': 'youth',
    },
    {
        'style_number': 'PRM10TSBC',
        'style_id': 12354,
        'base_price': 36.00,
        'category': 'Sweatshirt',
        'age_group': 'toddler',
    },
    # Heavyweight Premium
    {
        'style_number': 'IND4000',
        'style_id': 403,
        'base_price': 62.00,
        'category': 'Hoodie',
        'age_group': 'adult',
    },
    {
        'style_number': 'IND3000',
        'style_id': 11977,
        'base_price': 55.00,
        'category': 'Sweatshirt',
        'age_group': 'adult',
    },
]


def _compose_description(parsed: dict) -> str:
    """Prefer S&S description + fabric/spec details for the product description."""
    parts = []
    desc = (parsed.get('description') or '').strip()
    if desc:
        parts.append(desc)
    fabric = (parsed.get('fabric_details') or '').strip()
    if fabric and fabric.lower() not in desc.lower():
        parts.append(f'Fabric: {fabric}')
    fit = (parsed.get('fit_guide') or '').strip()
    if fit and fit.lower() not in desc.lower():
        parts.append(fit)
    return '\n\n'.join(parts).strip()


def build_product_record(api_data: dict, overrides: dict) -> dict:
    record = api_data.copy()
    record['brand'] = BRAND
    record['base_price'] = float(overrides['base_price'])
    record['category'] = overrides['category']
    record['age_group'] = overrides['age_group']
    record['is_active'] = True
    record['is_customer_favorite'] = False
    record['style_number'] = overrides['style_number']

    # Keep API wholesale when present
    if overrides.get('wholesale_cost') is not None:
        record['wholesale_cost'] = overrides['wholesale_cost']
    elif record.get('wholesale_cost') is None:
        record['wholesale_cost'] = None

    composed = _compose_description(record)
    if composed:
        record['description'] = composed

    # Ensure name carries the display brand
    title = (record.get('name') or '').strip()
    if title and not title.lower().startswith('independent'):
        # parse_style_to_product usually prefixes brandName already
        if BRAND.lower() not in title.lower():
            record['name'] = f'{BRAND} {title}'
    elif not title:
        record['name'] = f'{BRAND} {overrides["style_number"]}'

    return record


def upsert_product(db, Product, ProductColorVariant, record: dict, dry_run: bool) -> str:
    style = record['style_number']
    color_variants = record.pop('color_variants', [])
    existing = Product.query.filter_by(style_number=style).first()

    if dry_run:
        action = 'UPDATE' if existing else 'ADD'
        print(f"  [DRY {action}] {style:12s}  {record.get('name')}")
        print(
            f"             {len(color_variants)} colors  "
            f"age={record.get('age_group')}  cat={record.get('category')}  "
            f"retail=${record['base_price']:.2f}"
        )
        return 'dry'

    allowed = {
        'style_number', 'name', 'category', 'age_group', 'fit_type',
        'neck_style', 'sleeve_length', 'description', 'base_price',
        'wholesale_cost', 'available_sizes', 'available_colors',
        'is_active', 'is_customer_favorite', 'brand',
        'front_mockup_template', 'back_mockup_template',
        'size_chart', 'fit_guide', 'fabric_details', 'api_data',
        'spec_sheet_url',
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
        db.session.flush()
        action = 'added'

    for cv in color_variants:
        color_name = cv.get('color_name', '')
        if not color_name:
            continue
        existing_cv = ProductColorVariant.query.filter_by(
            product_id=product.id,
            color_name=color_name,
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

    print(f"  [{action.upper():7s}] {style:12s}  {record.get('name')}")
    print(
        f"             {len(color_variants)} colors  "
        f"age={record.get('age_group')}  cat={record.get('category')}  "
        f"retail=${record['base_price']:.2f}"
    )
    return action


def main():
    parser = argparse.ArgumentParser(description='Add Independent Trading Co. styles via S&S')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--style', default=None, help='Only one style number')
    args = parser.parse_args()

    from app import create_app
    from models import db, Product, ProductColorVariant
    from services.ssactivewear_api import SSActivewearAPI
    from utils.spec_sheets import ss_activewear_style_url

    app = create_app()
    with app.app_context():
        try:
            api = SSActivewearAPI()
        except ValueError as e:
            print(f'\nERROR: {e}')
            sys.exit(1)

        items = PRODUCTS_TO_ADD
        if args.style:
            items = [p for p in PRODUCTS_TO_ADD if p['style_number'].upper() == args.style.upper()]

        print(f"\n{'DRY RUN — ' if args.dry_run else ''}Processing {len(items)} Independent Trading Co. styles...\n")

        added = updated = skipped = 0
        for item in items:
            style_number = item['style_number']
            print(f"\n── {BRAND} {style_number} ──────────────────────────────────────")
            try:
                style_data = api.fetch_style_data_by_style_number(
                    style_number,
                    brand_name=BRAND,
                    style_id=item.get('style_id'),
                )
                if not style_data:
                    print(f'  [WARN] Style {style_number} not found in S&S API — skipping')
                    skipped += 1
                    continue

                n_colors = len(style_data.get('color_variants', []))
                n_sizes = len(style_data.get('sizes', []))
                print(f'  Found: {n_colors} colors, {n_sizes} sizes')

                parsed = api.parse_style_to_product(style_data)
                record = build_product_record(parsed, item)

                # Prefer public ItemSpecSheet when we know the S&S styleID
                sheet = ss_activewear_style_url(style_number)
                if sheet:
                    record['spec_sheet_url'] = sheet

                result = upsert_product(db, Product, ProductColorVariant, record, args.dry_run)
                if result == 'added':
                    added += 1
                elif result == 'updated':
                    updated += 1
            except Exception as e:
                print(f'  [WARN] {style_number}: {e} — skipping')
                import traceback
                traceback.print_exc()
                skipped += 1
                continue

        if not args.dry_run:
            db.session.commit()
            print(f"\n{'─' * 60}")
            print(f'Done!  Added: {added}  Updated: {updated}  Skipped: {skipped}')
            print(f'Successfully created/updated: {added + updated} of {len(items)}')
        else:
            print(f"\n{'─' * 60}")
            print(f'[DRY RUN] No changes. Would process {len(items)} styles. Skipped so far: {skipped}')


if __name__ == '__main__':
    main()
