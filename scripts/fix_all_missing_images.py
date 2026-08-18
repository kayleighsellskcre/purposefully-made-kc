"""
fix_all_missing_images.py
─────────────────────────
Finds ALL active products that have color variants missing front_image_url
and fills them from S&S Activewear API.

Uses fuzzy color-name matching so even slightly different names get matched
(e.g. "Heather Slate" ↔ "Dark Heather Slate", case differences, etc.)

Run from project root in Cursor terminal:
    py -3.12 scripts/fix_all_missing_images.py --dry-run          # preview only
    py -3.12 scripts/fix_all_missing_images.py                     # apply updates
    py -3.12 scripts/fix_all_missing_images.py --product-id 212    # one product only
    py -3.12 scripts/fix_all_missing_images.py --style G64500      # by style number
"""

import os, sys, argparse, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

# ── Brand name mapping: our DB brand → S&S brandName ──────────────────────────
BRAND_MAP = {
    'Bella+Canvas':   'BELLA + CANVAS',
    'Bella + Canvas': 'BELLA + CANVAS',
    'BELLA + CANVAS': 'BELLA + CANVAS',
    'Gildan':         'Gildan',
    'Rabbit Skins':   'Rabbit Skins',
    'Next Level':     'Next Level',
    'Comfort Colors': 'Comfort Colors',
    'ComfortWash':    'ComfortWash by Hanes',
    'Comfort Wash':   'ComfortWash by Hanes',
    'Hanes':          'Hanes',
    'Alternative':    'Alternative',
    'MV Sport':       'MV Sport',
    'C2 Sport':       'C2 Sport',
    'Team 365':       'Team 365',
    'Badger':         'Badger',
    'Augusta':        'Augusta Sportswear',
    'Holloway':       'Holloway',
    'Russell Athletic': 'Russell Athletic',
    'Independent':    'Independent Trading Co.',
    'Lane Seven':     'Lane Seven',
    'LAT':            'LAT',
    'Bayside':        'Bayside',
    'Threadfast':     'Threadfast Apparel',
    'Tultex':         'Tultex',
    # These brands are NOT in S&S — skip gracefully
    'Port & Company': None,
    'Port Authority': None,
    'Sport-Tek':      None,
    'District':       None,
}

# ── Hard-coded style ID overrides (confirmed from find_ss_styles.py) ───────────
# Add more here as you confirm them
STYLE_ID_OVERRIDES = {
    'G64500': 2116,   # S&S: 64V00 Unisex Softstyle V-Neck
    'RS3401': 2577,   # S&S: 4424 Infant Fine Jersey Bodysuit
}


def normalize_color(s):
    """Lowercase, remove punctuation/spaces for fuzzy matching."""
    s = (s or '').lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


def fuzzy_match_color(db_color, ss_colors_map):
    """
    Try to match db_color against a dict keyed by S&S color names.
    Returns the matched S&S color name, or None.
    Tries: exact → case-insensitive → strip spaces → normalized.
    """
    if db_color in ss_colors_map:
        return db_color
    lower = db_color.lower()
    for k in ss_colors_map:
        if k.lower() == lower:
            return k
    stripped = db_color.strip()
    for k in ss_colors_map:
        if k.strip() == stripped:
            return k
    norm = normalize_color(db_color)
    for k in ss_colors_map:
        if normalize_color(k) == norm:
            return k
    # Partial: db color is contained in ss color or vice versa
    for k in ss_colors_map:
        kn = normalize_color(k)
        if norm and (norm in kn or kn in norm):
            return k
    return None


def find_ss_style_id(api, product, all_ss_styles):
    """
    Find the S&S styleID for a product. Tries in order:
    1. Hard-coded override in STYLE_ID_OVERRIDES
    2. Exact styleNumber match in S&S catalog
    3. Normalized style number match (strip leading brand prefix)
    Returns styleID (int) or None.
    """
    # 1. Hard-coded override
    if product.style_number in STYLE_ID_OVERRIDES:
        return STYLE_ID_OVERRIDES[product.style_number]

    style_num = product.style_number or ''
    # Build candidates to try
    candidates = set()
    candidates.add(style_num.upper())
    candidates.add(style_num.lower())
    # Strip common brand prefixes: G→Gildan, BC→Bella, CC→Comfort Colors, RS→Rabbit Skins, etc.
    stripped = re.sub(r'^(BC|CC|RS|G|NL|DT|SL|ST|PC|PA|MV|C2|DM)(?=[0-9])', '', style_num, flags=re.I)
    if stripped != style_num:
        candidates.add(stripped.upper())
        candidates.add(stripped.lower())

    for s in all_ss_styles:
        snum = (s.get('styleNumber') or s.get('styleName') or '').strip()
        if snum.upper() in candidates:
            return s.get('styleID')

    return None


def get_ss_styles_for_brand(api, brand_name):
    """Fetch all S&S styles for a given brand name."""
    import requests as req_lib
    try:
        resp = req_lib.get(
            f"{api.api_url}/v2/styles",
            auth=(api.account_number, api.api_key),
            timeout=120
        )
        resp.raise_for_status()
        all_styles = resp.json() if isinstance(resp.json(), list) else []
    except Exception as e:
        print(f"  ERROR fetching S&S catalog: {e}")
        return [], []

    brand_lower = brand_name.lower()
    brand_styles = [
        s for s in all_styles
        if brand_lower in (s.get('brandName', '') or '').lower()
    ]
    return brand_styles, all_styles


def main():
    parser = argparse.ArgumentParser(description='Fix missing product color variant images from S&S')
    parser.add_argument('--dry-run', action='store_true', help='Preview only — no DB changes')
    parser.add_argument('--product-id', type=int, default=None, help='Only fix a specific product by ID')
    parser.add_argument('--style', default=None, help='Only fix a specific style number (e.g. G64500)')
    parser.add_argument('--force', action='store_true', help='Update ALL variants, not just missing ones')
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

        mode = 'DRY RUN' if args.dry_run else 'LIVE'
        print(f"\n{'='*60}")
        print(f"  Fix All Missing Images — {mode}")
        print(f"{'='*60}\n")

        # ── Find products to process ───────────────────────────────────────────
        query = Product.query.filter_by(is_active=True)
        if args.product_id:
            query = query.filter_by(id=args.product_id)
        if args.style:
            query = query.filter_by(style_number=args.style)

        all_products = query.all()
        print(f"Scanning {len(all_products)} active product(s)...\n")

        # Filter to those with at least one missing image (unless --force)
        if not args.force:
            target_products = []
            for p in all_products:
                missing = ProductColorVariant.query.filter_by(
                    product_id=p.id
                ).filter(
                    ProductColorVariant.front_image_url == None
                ).count()
                if missing > 0:
                    target_products.append((p, missing))
        else:
            target_products = [(p, 'ALL') for p in all_products]

        if not target_products:
            print("✅  No products with missing images found! Everything looks good.")
            return

        print(f"Found {len(target_products)} product(s) with missing images:\n")
        for p, missing in target_products:
            total = ProductColorVariant.query.filter_by(product_id=p.id).count()
            print(f"  [{p.id}] {p.style_number} — {p.name[:50]} ({missing}/{total} missing)")

        print()

        # ── Process each product ───────────────────────────────────────────────
        grand_total_updated = 0
        grand_total_created = 0
        grand_total_skipped = 0

        # Cache S&S catalog per brand to avoid refetching
        ss_catalog_cache = {}  # brand → (brand_styles, all_styles)

        for product, _ in target_products:
            print(f"\n── [{product.id}] {product.style_number} — {product.brand} ──────────────────────")

            db_brand = (product.brand or '').strip()
            ss_brand = BRAND_MAP.get(db_brand, db_brand)

            # Brand explicitly not in S&S — skip cleanly
            if ss_brand is None:
                print(f"  ℹ️  '{db_brand}' is not carried by S&S — skipping (no S&S source for this brand)")
                grand_total_skipped += 1
                continue

            # Fetch S&S catalog for this brand (cached)
            if ss_brand not in ss_catalog_cache:
                print(f"  Fetching S&S catalog for brand '{ss_brand}'...")
                brand_styles, all_styles = get_ss_styles_for_brand(api, ss_brand)
                ss_catalog_cache[ss_brand] = (brand_styles, all_styles)
                print(f"  Found {len(brand_styles)} S&S styles for '{ss_brand}'")
            else:
                brand_styles, all_styles = ss_catalog_cache[ss_brand]

            # Find S&S styleID
            style_id = find_ss_style_id(api, product, brand_styles or all_styles)
            if not style_id:
                print(f"  ⚠️  Could not find S&S styleID for {product.style_number} — skipping")
                print(f"       Tip: run 'py -3.12 scripts/find_ss_styles.py --brand \"{ss_brand}\" --search \"{product.style_number}\"'")
                grand_total_skipped += 1
                continue

            print(f"  S&S styleID={style_id}")

            # Fetch color/image data from S&S
            print(f"  Fetching color data from S&S...")
            style_data = api.get_style_details(style_id)
            if not style_data:
                print(f"  ERROR: could not fetch style details — skipping")
                grand_total_skipped += 1
                continue

            color_variants_ss = style_data.get('color_variants', [])
            print(f"  S&S returned {len(color_variants_ss)} color variants")

            # Build S&S color → image map
            ss_image_map = {}
            for cv in color_variants_ss:
                color = (cv.get('color_name') or '').strip()
                front = cv.get('front_image') or cv.get('front_image_url')
                back  = cv.get('back_image')  or cv.get('back_image_url')
                if color and front:
                    ss_image_map[color] = {'front': front, 'back': back}

            print(f"  S&S has images for {len(ss_image_map)} colors")

            if not ss_image_map:
                print(f"  ⚠️  No image data returned from S&S — skipping")
                grand_total_skipped += 1
                continue

            # Get DB variants to update
            if args.force:
                db_variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
            else:
                db_variants = ProductColorVariant.query.filter_by(
                    product_id=product.id
                ).filter(
                    ProductColorVariant.front_image_url == None
                ).all()

            print(f"  DB variants to process: {len(db_variants)}")

            updated = 0
            no_match = []

            for variant in db_variants:
                db_color = (variant.color_name or '').strip()
                matched_key = fuzzy_match_color(db_color, ss_image_map)

                if args.dry_run:
                    if matched_key:
                        print(f"    [DRY] '{db_color}' → S&S '{matched_key}'  {ss_image_map[matched_key]['front'][:60]}")
                        updated += 1
                    else:
                        no_match.append(db_color)
                    continue

                if matched_key:
                    variant.front_image_url = ss_image_map[matched_key]['front']
                    if ss_image_map[matched_key].get('back'):
                        variant.back_image_url = ss_image_map[matched_key]['back']
                    updated += 1
                else:
                    no_match.append(db_color)

            if not args.dry_run:
                db.session.commit()

            print(f"  ✅  Updated: {updated}  |  No S&S match: {len(no_match)}")
            if no_match:
                print(f"  Colors with no S&S match (will still show no image):")
                for c in no_match:
                    print(f"    • {c}")

            grand_total_updated += updated
            grand_total_skipped += len(no_match)

        # ── Summary ────────────────────────────────────────────────────────────
        print(f"\n{'='*60}")
        if args.dry_run:
            print(f"  DRY RUN complete — no DB changes made")
            print(f"  Would update: {grand_total_updated} variants")
            print(f"  No S&S match: {grand_total_skipped} variants")
            print(f"\n  Remove --dry-run to apply these changes.")
        else:
            print(f"  Done! Updated {grand_total_updated} color variant(s) with images from S&S.")
            if grand_total_skipped:
                print(f"  {grand_total_skipped} color(s) had no S&S match — check names manually.")
        print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
