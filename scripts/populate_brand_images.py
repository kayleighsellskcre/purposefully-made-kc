"""
populate_brand_images.py
────────────────────────
Generalized version of populate_ml_images.py.
Scrapes flat front/back images from SanMar Media Library (Widen/medialibrary1.com)
for ALL brands, not just Bella+Canvas.

Run from project root in Cursor terminal:

    python scripts/populate_brand_images.py --brands all
    python scripts/populate_brand_images.py --brands CC,PC,ST,DT,RS,STTU,STSW,G
    python scripts/populate_brand_images.py --brands CC          # just Comfort Colors
    python scripts/populate_brand_images.py --dry-run --brands all  # no DB write

Requires Chrome logged into medialibrary1.com.
If browser_cookie3 fails, use --cookie YOUR_JSESSIONID_VALUE.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

ACCOUNT_NAME = 'medialibrary1'   # Correct: account NAME, not numeric ID
API_URL      = 'https://medialibrary1.com/api/rest/asset/search'
EMBED_BASE   = f'https://embed.widencdn.net/img/{ACCOUNT_NAME}'
PAGE_SIZE    = 50

# ── All styles to scrape, grouped by brand prefix ─────────────────────────────
BRAND_STYLES = {
    # Bella+Canvas (core keeps only — trimmed by trim_bc_styles.py)
    'BC': [
        # Women's Micro Rib series (added to catalog Aug 2026)
        'BC1010', 'BC1012', 'BC1019', 'BC1080', 'BC1200', 'BC1201', 'BC1501',
        # Core unisex tees
        'BC3001', 'BC3001CVC', 'BC3001Y', 'BC3001YCVC',
        'BC3005', 'BC3005CVC',
        'BC3413', 'BC3413Y',
        'BC3480', 'BC3480CVC',
        'BC3501', 'BC3501CVC',
        'BC3719', 'BC3719Y',
        'BC3739', 'BC3787', 'BC3945',
        'BC6400', 'BC6400CVC',
        'BC8800',
    ],
    # Comfort Colors
    'CC': ['CC1717', 'CC1566', 'CC1466'],
    # Port & Company
    'PC': ['PC54', 'PC78H', 'LPC54', 'PC147', 'PC147Y', 'LPC147V', 'PC147LS', 'PC145', 'PC144'],
    # Sport-Tek
    'ST': ['ST350', 'ST254', 'LST350'],
    # District
    'DT': ['DT6000', 'DM130', 'DT8000'],
    # Rabbit Skins (RS3401 not in SanMar media library — omitted)
    'RS': ['RS3321', 'RS4400'],
    # Stanley/Stella (SanMar uses their own style numbers but media library may use brand codes)
    'STTU': ['STTU755', 'STTU169', 'STSW013'],
    # Gildan (G500 renamed to G64000 in DB — keep G64000 here)
    'G': ['G64000', 'G64500', 'G64400', 'G18500', 'G18000'],
}

# Maps style_number → (search_query_prefix, filename_prefix_in_Widen)
# Default (when not listed) is (style, style): searches "{style} Flat", matches "{style}_*_Flat_*"
# Discovered naming conventions:
#   - Comfort Colors: Widen uses bare number only (no "CC" prefix) in filenames and search
#   - Gildan: strip the "G" prefix (G500 → "5000", etc.)
#   - Stanley/Stella: SanMar assigned alternate style codes in the library (STTU755 → SXU041, etc.)
STYLE_SEARCH_MAP = {
    # Comfort Colors
    'CC1717': ('1717', '1717'),
    'CC1566': ('1566', '1566'),
    'CC1466': ('1466', '1466'),
    # Gildan (strip "G" prefix for Widen search — G64000 → "64000", etc.)
    'G64000': ('64000', '64000'),
    'G64500': ('64500', '64500'),
    'G64400': ('64400', '64400'),
    'G18500': ('18500', '18500'),
    'G18000': ('18000', '18000'),
    # Stanley/Stella (SanMar media library codes)
    'STTU755': ('SXU041', 'SXU041'),
    'STTU169': ('SXW002', 'SXW002'),
    'STSW013': ('SXU003', 'SXU003'),
}


def get_session(manual_cookie: str | None) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0',
    })
    if manual_cookie:
        sess.cookies.set('JSESSIONID', manual_cookie, domain='medialibrary1.com')
        print("Using manual session cookie.")
        return sess

    try:
        import browser_cookie3
        sess.cookies.update(browser_cookie3.chrome(domain_name='medialibrary1.com'))
        print("Loaded Chrome session cookies for medialibrary1.com.")
        return sess
    except Exception as e:
        print(f"browser_cookie3 failed: {e}")
        print("Tip: pip install browser-cookie3  OR  pass --cookie YOUR_JSESSIONID")
        sys.exit(1)


def build_embed_url(asset: dict, size: int = 600) -> str:
    """
    Build the correct Widen embed URL using the 'templated' preview field.
    Falls back to hash-based URL construction if templated isn't available.
    Format: https://embed.widencdn.net/img/{account_name}/{hash}/{size}px/{filename}
    """
    previews = asset.get('previews', {})
    templated = previews.get('templated', '')

    if templated:
        # Replace {size} placeholder, remove @{scale}x suffix if present
        url = re.sub(r'\{size\}', str(size), templated)
        url = re.sub(r'@\{scale\}x', '', url)
        url = re.sub(r'@\d+x', '', url)
        return url

    # Fallback: construct from asset hash/uuid
    # Try 'hash' field, then fall back to first 8 chars of uuid
    asset_hash = asset.get('hash', asset.get('uuid', '')[:8])
    filename = asset.get('filename', asset.get('name', '').replace('.tif', ''))
    filename = re.sub(r'\s*\(\d+\)$', '', filename)  # strip "(1)" duplicates
    return f'{EMBED_BASE}/{asset_hash}/{size}px/{requests.utils.quote(filename)}.jpg'


def search_style(sess: requests.Session, style: str) -> dict:
    """
    Search Widen for all flat images of one style.
    Returns {color_name: {front: url, back: url}}
    """
    image_map = {}
    search_prefix, filename_prefix = STYLE_SEARCH_MAP.get(style, (style, style))
    search_query = search_prefix + ' Flat'
    page = 1

    while True:
        try:
            r = sess.post(API_URL, json={
                'query': search_query,
                'limit': PAGE_SIZE,
                'page':  page,
            }, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [{style}] API error page {page}: {e}")
            break

        assets = data.get('assets') or []
        total  = data.get('numResults', 0)

        for asset in assets:
            name = asset.get('name', '')
            # Match: {PREFIX}_{ColorName}_Flat_{Front|Back}[_(number)].tif
            m = re.match(
                rf'^({re.escape(filename_prefix)})_(.+?)_Flat_(Front|Back)(?:_\d+)?(?:\s*\(\d+\))?\.tif$',
                name, re.IGNORECASE
            )
            if not m:
                continue

            color = m.group(2).replace('_', ' ')
            side  = m.group(3).lower()  # 'front' or 'back'
            url   = build_embed_url(asset)

            if color not in image_map:
                image_map[color] = {}
            if side not in image_map[color]:  # keep first match
                image_map[color][side] = url

        if page * PAGE_SIZE >= total or not assets:
            break
        page += 1
        time.sleep(0.05)

    return image_map


def update_database(all_images: dict, verbose: bool = False) -> dict:
    """Write scraped image URLs into ProductColorVariant records."""
    from app import create_app
    from models import db, Product, ProductColorVariant

    app = create_app()
    with app.app_context():
        updated = created = skipped = 0

        for style, colors in all_images.items():
            product = Product.query.filter_by(style_number=style).first()
            if not product:
                if verbose:
                    print(f"  [SKIP] {style} — no matching Product in DB")
                skipped += len(colors)
                continue

            first_front = first_back = None

            for color, sides in colors.items():
                front_url = sides.get('front', '')
                back_url  = sides.get('back', '')
                if not front_url and not back_url:
                    skipped += 1
                    continue

                variant = ProductColorVariant.query.filter(
                    ProductColorVariant.product_id == product.id,
                    db.func.lower(ProductColorVariant.color_name) == color.lower()
                ).first()

                if variant:
                    if front_url: variant.front_image_url = front_url
                    if back_url:  variant.back_image_url  = back_url
                    variant.last_synced = datetime.utcnow()
                    updated += 1
                else:
                    db.session.add(ProductColorVariant(
                        product_id=product.id,
                        color_name=color,
                        front_image_url=front_url,
                        back_image_url=back_url,
                        last_synced=datetime.utcnow(),
                    ))
                    created += 1

                if not first_front and front_url: first_front = front_url
                if not first_back  and back_url:  first_back  = back_url

            if first_front and not product.front_mockup_template:
                product.front_mockup_template = first_front
            if first_back and not product.back_mockup_template:
                product.back_mockup_template = first_back

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}

        return {'updated': updated, 'created': created, 'skipped': skipped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cookie',  help='medialibrary1.com JSESSIONID cookie value')
    parser.add_argument('--brands',  default='all',
                        help='Comma-separated brand prefixes (e.g. CC,PC,G) or "all"')
    parser.add_argument('--dry-run', action='store_true', help='Scrape only — no DB write')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    # Full brand name → key aliases (case-insensitive)
    BRAND_ALIASES = {
        'GILDAN': 'G',
        'BELLA+CANVAS': 'BC',
        'BELLA': 'BC',
        'BELLACANVAS': 'BC',
        'COMFORT COLORS': 'CC',
        'COMFORTCOLORS': 'CC',
        'PORT & COMPANY': 'PC',
        'PORT AND COMPANY': 'PC',
        'SPORT-TEK': 'ST',
        'SPORTTEK': 'ST',
        'DISTRICT': 'DT',
        'RABBIT SKINS': 'RS',
        'RABBITSKINS': 'RS',
        'STANLEY/STELLA': 'STTU',
        'STANLEY STELLA': 'STTU',
    }

    # Resolve which brands to process
    if args.brands.lower() == 'all':
        selected_brands = list(BRAND_STYLES.keys())
    else:
        raw = [b.strip().upper() for b in args.brands.split(',')]
        selected_brands = [BRAND_ALIASES.get(b, b) for b in raw]

    styles_to_process = []
    for brand in selected_brands:
        # Allow matching by any prefix in the style number
        if brand in BRAND_STYLES:
            styles_to_process.extend(BRAND_STYLES[brand])
        else:
            # Try to find matching styles by prefix
            matched = [s for bk, sl in BRAND_STYLES.items() for s in sl if s.upper().startswith(brand)]
            if matched:
                styles_to_process.extend(matched)
            else:
                print(f"Warning: brand '{brand}' not found. Available: {list(BRAND_STYLES.keys())}")

    if not styles_to_process:
        print("No styles to process. Exiting.")
        sys.exit(1)

    print(f"\nScraping {len(styles_to_process)} styles from SanMar Media Library...")
    print(f"Brands: {', '.join(selected_brands)}\n")

    sess = get_session(args.cookie)

    all_images = {}
    for i, style in enumerate(styles_to_process, 1):
        img_map = search_style(sess, style)
        if img_map:
            all_images[style] = img_map
            print(f"  [{i:3}/{len(styles_to_process)}] {style:14s} {len(img_map)} colors found")
        else:
            print(f"  [{i:3}/{len(styles_to_process)}] {style:14s} (no flat images found — may need manual check)")
        time.sleep(0.15)

    total_variants = sum(len(c) for c in all_images.values())
    print(f"\nScraped {total_variants} color variants across {len(all_images)} styles.")

    # Save cache
    cache_path = os.path.join(ROOT, 'services', 'ml_images_cache_all_brands.json')
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w') as f:
        json.dump(all_images, f, indent=2)
    print(f"Cache saved to {cache_path}")

    if args.dry_run:
        print("\n[DRY RUN] Skipping database update.")
        return

    print("\nUpdating database...")
    result = update_database(all_images, verbose=args.verbose)

    if 'error' in result:
        print(f"ERROR: {result['error']}")
    else:
        print(f"Done!  Updated: {result['updated']} | Created: {result['created']} | Skipped: {result['skipped']}")
        print("\nIf any styles showed '(no flat images found)' above, the naming convention")
        print("in the Widen media library may differ for that brand. Check medialibrary1.com")
        print("manually and note the actual filename pattern, then update the regex in this script.")


if __name__ == '__main__':
    main()
