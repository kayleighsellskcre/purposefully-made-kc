"""
add_bella_infant_toddler.py
───────────────────────────
Upsert Bella+Canvas infant & toddler styles into the product catalog.

Prefers SanMar FTP/DIP or SOAP when credentials are present; falls back to
S&S Activewear (same Bella blanks, ghost/flat images preferred) when SanMar
is not configured locally.

    py -3.12 scripts/add_bella_infant_toddler.py --dry-run
    py -3.12 scripts/add_bella_infant_toddler.py
    py -3.12 scripts/add_bella_infant_toddler.py --source ss
    py -3.12 scripts/add_bella_infant_toddler.py --source sanmar

Active / visible: 100B, 3001B, 3001T, 3501T, 3719T
Inactive / hidden: 134B, 3413B, 3413T, 3200T
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

# Prevent create_app() from starting nightly sync jobs during this import.
os.environ['SCHEDULER_ENABLED'] = '0'

BRAND = 'Bella+Canvas'

# S&S styleIDs for reliable lookup (SanMar uses the printed style number).
PRODUCTS = [
    {
        'style_number': '100B',
        'style_id': 6166,
        'age_group': 'baby',
        'category': 'Onesie',
        'is_active': True,
        'title_hint': 'Infant Jersey Short Sleeve One Piece',
    },
    {
        'style_number': '3001B',
        'style_id': 6167,
        'age_group': 'baby',
        'category': 'Tee',
        'is_active': True,
        'title_hint': 'Infant Jersey Short Sleeve Tee',
    },
    {
        'style_number': '134B',
        'style_id': 6270,
        'age_group': 'baby',
        'category': 'Onesie',
        'is_active': False,
        'title_hint': 'Infant Triblend Short Sleeve One Piece',
    },
    {
        'style_number': '3413B',
        'style_id': 6308,
        'age_group': 'baby',
        'category': 'Tee',
        'is_active': False,
        'title_hint': 'Infant Triblend Short Sleeve Tee',
    },
    {
        'style_number': '3001T',
        'style_id': 6168,
        'age_group': 'toddler',
        'category': 'Tee',
        'is_active': True,
        'title_hint': 'Toddler Jersey Short Sleeve Tee',
    },
    {
        'style_number': '3501T',
        'style_id': 8195,
        'age_group': 'toddler',
        'category': 'Tee',
        'is_active': True,
        'title_hint': 'Toddler Jersey Long Sleeve Tee',
    },
    {
        'style_number': '3719T',
        'style_id': 2670,
        'age_group': 'toddler',
        'category': 'Hoodie',
        'is_active': True,
        'title_hint': 'Toddler Sponge Fleece Pullover Hoodie',
    },
    {
        'style_number': '3413T',
        'style_id': 6275,
        'age_group': 'toddler',
        'category': 'Tee',
        'is_active': False,
        'title_hint': 'Toddler Triblend Short Sleeve Tee',
    },
    {
        'style_number': '3200T',
        'style_id': 6170,
        'age_group': 'toddler',
        'category': 'Tee',
        'is_active': False,
        'title_hint': 'Toddler 3/4 Sleeve Baseball Tee',
    },
]


def _sanmar_ready() -> bool:
    ftp_ok = bool(os.getenv('SANMAR_FTP_USER') and os.getenv('SANMAR_FTP_PASSWORD'))
    soap_ok = bool(
        os.getenv('SANMAR_CUSTOMER_NUMBER')
        and os.getenv('SANMAR_USERNAME')
        and os.getenv('SANMAR_PASSWORD')
    )
    return ftp_ok or soap_ok


def _compose_description(parsed: dict) -> str:
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


def _retail_from_wholesale(wholesale) -> float:
    try:
        w = float(wholesale or 0)
    except (TypeError, ValueError):
        w = 0.0
    return float(math.ceil(w) + 19) if w > 0 else 0.0


def build_record_from_ss(parsed: dict, overrides: dict) -> dict:
    record = parsed.copy()
    record['brand'] = BRAND
    record['style_number'] = overrides['style_number']
    record['age_group'] = overrides['age_group']
    record['category'] = overrides['category']
    record['is_active'] = bool(overrides['is_active'])
    record['is_customer_favorite'] = False

    wholesale = record.get('wholesale_cost')
    record['base_price'] = _retail_from_wholesale(wholesale)

    composed = _compose_description(record)
    if composed:
        record['description'] = composed

    title = (record.get('name') or '').strip()
    hint = overrides.get('title_hint') or overrides['style_number']
    if not title:
        record['name'] = f'{BRAND} {hint}'
    elif BRAND.lower() not in title.lower() and 'bella' not in title.lower():
        record['name'] = f'{BRAND} {title}'
    else:
        # Normalize brand spelling to Bella+Canvas
        record['name'] = title.replace('Bella + Canvas', BRAND).replace('BELLA + CANVAS', BRAND)
        if not record['name'].lower().startswith('bella'):
            record['name'] = f'{BRAND} {record["name"]}'

    return record


def upsert_product(db, Product, ProductColorVariant, record: dict, dry_run: bool) -> str:
    style = record['style_number']
    color_variants = record.pop('color_variants', []) or []
    existing = Product.query.filter_by(style_number=style).first()
    if existing is None:
        # Also match BC-prefixed duplicates if present
        existing = Product.query.filter_by(style_number=f'BC{style}').first()

    n_colors = len(color_variants)
    sizes = record.get('available_sizes') or '[]'
    if dry_run:
        action = 'UPDATE' if existing else 'ADD'
        print(f"  [DRY {action}] {style:8s}  active={record.get('is_active')}  "
              f"age={record.get('age_group')}  cat={record.get('category')}")
        print(f"             {record.get('name')}")
        print(f"             {n_colors} colors  retail=${float(record.get('base_price') or 0):.2f}  "
              f"wholesale=${float(record.get('wholesale_cost') or 0):.2f}")
        print(f"             sizes={sizes}")
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
    # Canonical style number without BC prefix for these infant/toddler SKUs
    product_fields['style_number'] = style

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
        inv = cv.get('size_inventory')
        if isinstance(inv, dict):
            inv = json.dumps(inv)
        cv_fields = {
            'product_id': product.id,
            'color_name': color_name,
            'ss_color_id': str(cv.get('color_id', '') or ''),
            'front_image_url': cv.get('front_image'),
            'back_image_url': cv.get('back_image'),
            'side_image_url': cv.get('side_image'),
            'size_inventory': inv,
        }
        if existing_cv:
            for k, v in cv_fields.items():
                if k == 'product_id':
                    continue
                if v is not None:
                    setattr(existing_cv, k, v)
        else:
            db.session.add(ProductColorVariant(**cv_fields))

    print(f"  [{action.upper():7s}] {style:8s}  active={product.is_active}  "
          f"age={product.age_group}  cat={product.category}  "
          f"{n_colors} colors  retail=${float(product.base_price or 0):.2f}")
    return action


def import_via_ss(items, dry_run: bool) -> tuple[int, int, int]:
    from app import create_app
    from models import db, Product, ProductColorVariant
    from services.ssactivewear_api import SSActivewearAPI
    from utils.spec_sheets import resolve_spec_sheet_url

    app = create_app()
    added = updated = skipped = 0
    with app.app_context():
        api = SSActivewearAPI()
        print(f"\n{'DRY RUN — ' if dry_run else ''}Importing {len(items)} Bella+Canvas styles via S&S…\n")

        for item in items:
            style = item['style_number']
            print(f"\n── {BRAND} {style} ──────────────────────────────────────")
            try:
                style_data = api.fetch_style_data_by_style_number(
                    style,
                    brand_name='BELLA + CANVAS',
                    style_id=item.get('style_id'),
                )
                if not style_data:
                    print(f'  [WARN] {style} not found in S&S — skipping')
                    skipped += 1
                    continue

                parsed = api.parse_style_to_product(style_data)
                record = build_record_from_ss(parsed, item)

                # Spec sheet → Bella product page when possible
                class _Tmp:
                    brand = BRAND
                    style_number = style
                    spec_sheet_url = None
                sheet = resolve_spec_sheet_url(_Tmp())
                if sheet:
                    record['spec_sheet_url'] = sheet

                result = upsert_product(db, Product, ProductColorVariant, record, dry_run)
                if result == 'added':
                    added += 1
                elif result == 'updated':
                    updated += 1
            except Exception as exc:
                print(f'  [WARN] {style}: {exc} — skipping')
                import traceback
                traceback.print_exc()
                skipped += 1

        if not dry_run:
            db.session.commit()
            print(f"\nDone. Added: {added}  Updated: {updated}  Skipped: {skipped}")
        else:
            print(f"\n[DRY RUN] Would process {len(items)} styles. Skipped so far: {skipped}")
    return added, updated, skipped


def import_via_sanmar(items, dry_run: bool) -> tuple[int, int, int]:
    """Pull curated styles from SanMar SOAP (or rely on DIP if only FTP is set)."""
    from app import create_app
    from models import db, Product, ProductColorVariant
    from services.sanmar_api import SanMarAPI

    wanted = {p['style_number'].upper() for p in items}
    overrides = {p['style_number'].upper(): p for p in items}

    app = create_app()
    added = updated = skipped = 0
    with app.app_context():
        api = SanMarAPI()
        print(f"\n{'DRY RUN — ' if dry_run else ''}Fetching Bella+Canvas via SanMar SOAP…\n")
        products, notes = api.sync_curated_catalog()
        for note in notes or []:
            print(f'  [note] {note}')

        matched = []
        for pdata in products or []:
            style = (pdata.get('style_number') or '').upper().replace('BC', '', 1) if (pdata.get('style_number') or '').upper().startswith('BC') else (pdata.get('style_number') or '').upper()
            # Normalize: strip BC prefix for matching
            raw = (pdata.get('style_number') or '').upper()
            bare = raw[2:] if raw.startswith('BC') else raw
            if bare in wanted or raw in wanted:
                matched.append((bare if bare in wanted else raw, pdata))

        found = {s for s, _ in matched}
        for style in sorted(wanted - found):
            print(f'  [WARN] {style} not returned by SanMar curated sync — skipping')
            skipped += 1

        for style, pdata in matched:
            ov = overrides[style]
            print(f"\n── {BRAND} {style} ──────────────────────────────────────")
            record = pdata.copy()
            record['brand'] = BRAND
            record['style_number'] = style
            record['age_group'] = ov['age_group']
            record['category'] = ov['category']
            record['is_active'] = bool(ov['is_active'])
            record['is_customer_favorite'] = False
            if not record.get('base_price'):
                record['base_price'] = _retail_from_wholesale(record.get('wholesale_cost'))

            result = upsert_product(db, Product, ProductColorVariant, record, dry_run)
            if result == 'added':
                added += 1
            elif result == 'updated':
                updated += 1

        if not dry_run:
            db.session.commit()
            print(f"\nDone. Added: {added}  Updated: {updated}  Skipped: {skipped}")
        else:
            print(f"\n[DRY RUN] Matched {len(matched)} of {len(wanted)} styles.")
    return added, updated, skipped


def main():
    parser = argparse.ArgumentParser(description='Add Bella+Canvas infant/toddler styles')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--style', default=None, help='Only one style number')
    parser.add_argument(
        '--source',
        choices=['auto', 'ss', 'sanmar'],
        default='auto',
        help='Data source (default: auto = SanMar if creds else S&S)',
    )
    args = parser.parse_args()

    items = PRODUCTS
    if args.style:
        items = [p for p in PRODUCTS if p['style_number'].upper() == args.style.upper()]
        if not items:
            print(f'Unknown style: {args.style}')
            sys.exit(1)

    source = args.source
    if source == 'auto':
        source = 'sanmar' if _sanmar_ready() else 'ss'
        print(f'[auto] Using source={source} (SanMar ready={_sanmar_ready()})')

    if source == 'sanmar':
        if not _sanmar_ready():
            print('ERROR: SanMar credentials not set. Use --source ss or configure SANMAR_*.')
            sys.exit(1)
        import_via_sanmar(items, args.dry_run)
    else:
        import_via_ss(items, args.dry_run)


if __name__ == '__main__':
    main()
