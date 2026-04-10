"""
Syncs the FULL Bella+Canvas catalog from S&S Activewear.
Fetches every style returned by the API for the Bella+Canvas brand,
enriches each one with color variants and per-size inventory,
then upserts into the Product + ProductColorVariant tables.

Usage:
    python sync_all_bella_canvas.py            # sync everything
    python sync_all_bella_canvas.py --limit 5  # test with first 5 styles
"""
import sys
import argparse
from app import create_app
from models import db, Product, ProductColorVariant
from services.ssactivewear_api import SSActivewearAPI
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument('--limit', type=int, default=None, help='Limit number of styles (for testing)')
args = parser.parse_args()

app = create_app()

with app.app_context():
    print("=" * 80)
    print("SYNCING FULL BELLA+CANVAS CATALOG FROM S&S ACTIVEWEAR")
    if args.limit:
        print(f"  *** TEST MODE: limited to first {args.limit} styles ***")
    print("=" * 80)

    try:
        api = SSActivewearAPI()

        print("\nConnecting to S&S Activewear API and fetching all Bella+Canvas styles...")
        products_data = api.sync_bella_canvas_catalog(limit=args.limit)

        if not products_data:
            print("\nERROR: No products returned from API. Check credentials and API access.")
            sys.exit(1)

        print(f"\nReceived {len(products_data)} styles from API — writing to database...\n")

        added = 0
        updated = 0
        variants_added = 0
        variants_updated = 0
        errors = []

        for idx, product_data in enumerate(products_data, 1):
            color_variants_data = product_data.pop('color_variants', [])
            style_num = product_data.get('style_number', 'UNKNOWN')

            print(f"  [{idx}/{len(products_data)}] {style_num} — {product_data.get('name', '')}")

            try:
                existing = Product.query.filter_by(style_number=style_num).first()

                if existing:
                    for key, value in product_data.items():
                        if hasattr(existing, key) and value is not None:
                            setattr(existing, key, value)
                    existing.is_active = True
                    product = existing
                    updated += 1
                    print(f"    [updated]")
                else:
                    product_data['is_active'] = True
                    product = Product(**product_data)
                    db.session.add(product)
                    added += 1
                    print(f"    [new]")

                db.session.flush()

                print(f"    -> {len(color_variants_data)} color variants")
                for variant_data in color_variants_data:
                    color_name = variant_data.get('color_name', '')
                    if not color_name:
                        continue

                    existing_variant = ProductColorVariant.query.filter_by(
                        product_id=product.id,
                        color_name=color_name
                    ).first()

                    if existing_variant:
                        existing_variant.front_image_url = variant_data.get('front_image') or existing_variant.front_image_url
                        existing_variant.back_image_url  = variant_data.get('back_image')  or existing_variant.back_image_url
                        existing_variant.side_image_url  = variant_data.get('side_image')  or existing_variant.side_image_url
                        existing_variant.size_inventory  = variant_data.get('size_inventory')
                        existing_variant.ss_color_id     = variant_data.get('color_id')
                        existing_variant.last_synced     = datetime.utcnow()
                        variants_updated += 1
                    else:
                        new_variant = ProductColorVariant(
                            product_id=product.id,
                            color_name=color_name,
                            front_image_url=variant_data.get('front_image'),
                            back_image_url=variant_data.get('back_image'),
                            side_image_url=variant_data.get('side_image'),
                            size_inventory=variant_data.get('size_inventory'),
                            ss_color_id=variant_data.get('color_id'),
                            last_synced=datetime.utcnow()
                        )
                        db.session.add(new_variant)
                        variants_added += 1

            except Exception as e:
                print(f"    ERROR processing {style_num}: {e}")
                errors.append((style_num, str(e)))
                db.session.rollback()
                continue

        db.session.commit()

        print("\n" + "=" * 80)
        print("SYNC COMPLETE!")
        print("=" * 80)
        print(f"  Products added:          {added}")
        print(f"  Products updated:        {updated}")
        print(f"  Color variants added:    {variants_added}")
        print(f"  Color variants updated:  {variants_updated}")
        print(f"  Total products in DB:    {Product.query.count()}")
        if errors:
            print(f"\n  Styles with errors ({len(errors)}):")
            for style, err in errors:
                print(f"    - {style}: {err}")
        print("=" * 80)

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        sys.exit(1)
