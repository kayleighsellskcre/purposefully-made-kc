"""
fix_images_from_ss.py
─────────────────────
Finds products that are missing images in our DB and pulls their
front/back image URLs from S&S Activewear's API.

Targets: G64500 (Gildan Softstyle V-Neck) + RS3401 (Rabbit Skins Infant Bodysuit)
         — and any other active product with no images that S&S carries.

Run from project root in Cursor terminal:
    py -3.12 scripts/fix_images_from_ss.py --dry-run   # preview only
    py -3.12 scripts/fix_images_from_ss.py             # apply updates
"""

import os, sys, argparse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

# Styles to fix — style_number as stored in our DB → S&S styleID (confirmed from find_ss_styles.py)
# G64500 = SanMar style number; S&S lists it as 64V00 (styleID 2116)
# RS3401 = SanMar style number; S&S styleID set below (fill in after find_ss_styles.py --brand "Rabbit Skins")
TARGET_STYLES = {
    'G64500':  {'brand': 'Gildan',       'ss_style_id': 2116},   # S&S: 64V00 Unisex Softstyle V-Neck
    'RS3401':  {'brand': 'Rabbit Skins', 'ss_style_id': 2577},   # S&S: 4424 Infant Fine Jersey Bodysuit
}

def find_ss_style_id(api, style_number, brand_name):
    """Search S&S catalog for a style and return its styleID."""
    import requests
    print(f"  Searching S&S catalog for {style_number} ({brand_name})...")
    try:
        resp = requests.get(
            f"{api.api_url}/v2/styles",
            auth=(api.account_number, api.api_key),
            timeout=120
        )
        resp.raise_for_status()
        all_styles = resp.json() if isinstance(resp.json(), list) else []
    except Exception as e:
        print(f"    ERROR fetching catalog: {e}")
        return None

    # Search by style number match
    style_lower = style_number.lower().replace('g', '', 1) if style_number.startswith('G') else style_number.lower()
    matches = [
        s for s in all_styles
        if (
            str(s.get('styleNumber') or s.get('styleName') or '').lower() == style_number.lower()
            or str(s.get('styleNumber') or s.get('styleName') or '').lower() == style_lower
        )
        and brand_name.lower() in (s.get('brandName', '') or '').lower()
    ]

    if not matches:
        # Broader search — just style number, any brand
        matches = [
            s for s in all_styles
            if str(s.get('styleNumber') or s.get('styleName') or '').lower() in [
                style_number.lower(), style_lower
            ]
        ]

    if matches:
        m = matches[0]
        sid = m.get('styleID')
        found_brand = m.get('brandName', '')
        found_style = m.get('styleNumber') or m.get('styleName', '')
        print(f"    Found: styleID={sid}  style={found_style}  brand={found_brand}")
        return sid
    else:
        print(f"    Not found in S&S catalog.")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    from app import create_app
    from models import db, Product, ProductColorVariant
    from services.ssactivewear_api import SSActivewearAPI

    app = create_app()
    with app.app_context():
        try:
            api = SSActivewearAPI()
        except ValueError as e:
            print(f"\nERROR: {e}")
            sys.exit(1)

        print(f"\n{'DRY RUN — ' if args.dry_run else ''}Fixing missing images from S&S API...\n")

        total_updated = 0

        for style_number, info in TARGET_STYLES.items():
            print(f"\n── {info['brand']} {style_number} ──────────────────────────────────")

            # Check if product exists in our DB
            product = Product.query.filter_by(style_number=style_number).first()
            if not product:
                print(f"  Product {style_number} not in DB — skipping")
                continue

            # Check existing color variants
            variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
            missing = [v for v in variants if not v.front_image_url]
            print(f"  DB: {len(variants)} color variants, {len(missing)} missing front images")

            # Use confirmed S&S styleID directly — no catalog search needed
            style_id = info['ss_style_id']
            print(f"  Using confirmed S&S styleID={style_id}")

            # Fetch full style details (colors + images)
            print(f"  Fetching color/image data from S&S...")
            style_data = api.get_style_details(style_id)
            if not style_data:
                print(f"  ERROR: could not fetch style details")
                continue

            color_variants = style_data.get('color_variants', [])
            print(f"  S&S returned {len(color_variants)} color variants")

            if not color_variants:
                print(f"  No color variants found — skipping")
                continue

            # Build color → image URL map from S&S
            ss_image_map = {}
            for cv in color_variants:
                color = (cv.get('color_name') or '').strip()
                front = cv.get('front_image') or cv.get('front_image_url')
                back  = cv.get('back_image')  or cv.get('back_image_url')
                if color and front:
                    ss_image_map[color.lower()] = {'front': front, 'back': back}

            print(f"  S&S has images for {len(ss_image_map)} colors")

            if args.dry_run:
                for color, urls in list(ss_image_map.items())[:5]:
                    front_preview = (urls.get('front') or '')[:80]
                    print(f"    [DRY] {color}: {front_preview}")
                if len(ss_image_map) > 5:
                    print(f"    ... and {len(ss_image_map) - 5} more colors")
                continue

            # Update DB variants that are missing images
            updated = 0
            created = 0
            for cv in color_variants:
                color_name = (cv.get('color_name') or '').strip()
                front = cv.get('front_image') or cv.get('front_image_url')
                back  = cv.get('back_image')  or cv.get('back_image_url')

                if not color_name or not front:
                    continue

                existing = ProductColorVariant.query.filter_by(
                    product_id=product.id,
                    color_name=color_name
                ).first()

                if existing:
                    if not existing.front_image_url:
                        existing.front_image_url = front
                        existing.back_image_url  = back
                        updated += 1
                    elif front and existing.front_image_url != front:
                        existing.front_image_url = front
                        existing.back_image_url  = back
                        updated += 1
                else:
                    # Create new variant with image
                    new_cv = ProductColorVariant(
                        product_id=product.id,
                        color_name=color_name,
                        front_image_url=front,
                        back_image_url=back,
                        ss_color_id=str(cv.get('color_id', '') or ''),
                        size_inventory=cv.get('size_inventory'),
                    )
                    db.session.add(new_cv)
                    created += 1

            db.session.commit()
            print(f"  Done! Updated: {updated}  Created: {created}")
            total_updated += updated + created

        print(f"\n{'─'*60}")
        if args.dry_run:
            print("[DRY RUN] No changes made. Remove --dry-run to apply.")
        else:
            print(f"Total color variants updated/created: {total_updated}")
            print("\nImages will now load from S&S CDN on the shop page.")


if __name__ == '__main__':
    main()
