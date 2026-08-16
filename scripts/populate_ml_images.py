"""
populate_ml_images.py
─────────────────────
One-time script to pull ALL Bella+Canvas flat images from the SanMar
Media Library (Widen/medialibrary1.com) and write them into the database.

Run from the kb_apparel_site project root in Cursor terminal:

    pip install browser-cookie3 requests --break-system-packages
    python scripts/populate_ml_images.py

Requires Chrome to be logged into medialibrary1.com (the session cookie
is read automatically from your Chrome profile — Chrome can stay open).

If that fails, fall back to manual cookie:
    python scripts/populate_ml_images.py --cookie "your_session_cookie_value"
"""

import argparse
import json
import os
import sys
import re
import time
from collections import defaultdict
from datetime import datetime

import requests

# ── locate project root ───────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── load .env so DATABASE_URL etc. are available ─────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

ACCOUNT_ID  = '47526418'
API_URL     = 'https://medialibrary1.com/api/rest/asset/search'
EMBED_BASE  = f'https://embed.widencdn.net/img/{ACCOUNT_ID}'
PAGE_SIZE   = 50

BC_STYLES = [
    'BC100B','BC1010','BC1012','BC1019','BC1080','BC1200','BC1201','BC1501',
    'BC3001','BC3001B','BC3001CVC','BC3001T','BC3001Y','BC3001YCVC',
    'BC3005','BC3005CVC','BC3010','BC3010Y','BC3200','BC3413','BC3413T',
    'BC3413Y','BC3415','BC3480','BC3480CVC','BC3480Y','BC3480YCVC','BC3483',
    'BC3501','BC3501CVC','BC3501T','BC3501Y','BC3501YCVC','BC3511','BC3511Y',
    'BC3512','BC3513','BC3650','BC3655','BC3719','BC3719T','BC3719Y',
    'BC3725','BC3727','BC3729','BC3738','BC3738Y','BC3739','BC3739Y',
    'BC3787','BC3901','BC3901Y','BC3909','BC3911','BC3945','BC4540',
    'BC4610','BC4651','BC4711','BC4719','BC4737','BC4739','BC4740','BC4741',
    'BC4810GD','BC4851GD','BC6003','BC6004','BC6008','BC6110','BC6110GD',
    'BC6400','BC6400CVC','BC6405','BC6405CVC','BC6413','BC6482','BC6500',
    'BC6682','BC6824GD','BC6882GD','BC7502','BC7505','BC8413',
    'BC8800','BC8803','BC8804','BC8882',
]


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

    # Try browser_cookie3 (reads Chrome cookies automatically)
    try:
        import browser_cookie3
        chrome_cookies = browser_cookie3.chrome(domain_name='medialibrary1.com')
        sess.cookies.update(chrome_cookies)
        print("Loaded Chrome session cookies for medialibrary1.com.")
        return sess
    except Exception as e:
        print(f"browser_cookie3 failed: {e}")
        print("Try: pip install browser-cookie3")
        print("Or pass --cookie with your JSESSIONID value.")
        sys.exit(1)


def search_style(sess: requests.Session, style: str) -> dict:
    """Search Widen for all flat images of one style. Returns {color: {front: url, back: url}}"""
    image_map = {}
    page = 1

    while True:
        try:
            r = sess.post(API_URL, json={
                'query': f'{style} Flat',
                'limit': PAGE_SIZE,
                'page':  page,
            }, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [{style}] API error page {page}: {e}")
            break

        assets = data.get('assets') or []
        total  = data.get('numResults', 0)

        for asset in assets:
            name = asset.get('name', '')
            m = re.match(
                r'^(BC\w+?)_(.+?)_Flat_(Front|Back)(?:\s*\(\d+\))?\.tif$',
                name, re.IGNORECASE
            )
            if not m or m.group(1) != style:
                continue

            color = m.group(2)
            side  = m.group(3).lower()
            uuid  = asset.get('uuid', '')
            fn    = re.sub(r'\s*\(\d+\)$', '', name[:-4])  # strip .tif + "(1)" etc.
            url   = f'{EMBED_BASE}/{uuid}/1200px/{requests.utils.quote(fn)}.jpg'

            if color not in image_map:
                image_map[color] = {}
            if side not in image_map[color]:  # keep first occurrence
                image_map[color][side] = url

        if page * PAGE_SIZE >= total or not assets:
            break
        page += 1

    return image_map


def update_database(all_images: dict) -> dict:
    """Write image URLs into ProductColorVariant records."""
    from app import create_app
    from models import db, Product, ProductColorVariant

    app = create_app()
    with app.app_context():
        updated = created = skipped = 0

        for style, colors in all_images.items():
            product = Product.query.filter_by(style_number=style).first()
            if not product:
                skipped += len(colors)
                continue

            first_front = None
            first_back  = None

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

            # Set product template if not already set
            if first_front and not product.front_mockup_template:
                product.front_mockup_template = first_front
            if first_back and not product.back_mockup_template:
                product.back_mockup_template = first_back

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DB commit failed: {e}")
            return {'error': str(e)}

        return {'updated': updated, 'created': created, 'skipped': skipped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cookie', help='medialibrary1.com JSESSIONID cookie (skips browser_cookie3)')
    parser.add_argument('--dry-run', action='store_true', help='Scrape only — do not write to DB or POST')
    parser.add_argument('--styles', help='Comma-separated subset of styles to process')
    parser.add_argument('--post-live', action='store_true', help='POST scraped images directly to live Railway site')
    parser.add_argument('--admin-cookie', help='purposefullymadekc.com Flask session cookie for --post-live')
    args = parser.parse_args()

    sess = get_session(args.cookie)

    styles = BC_STYLES
    if args.styles:
        styles = [s.strip() for s in args.styles.split(',')]

    print(f"\nScraping {len(styles)} styles from SanMar Media Library...\n")

    all_images = {}
    for i, style in enumerate(styles, 1):
        img_map = search_style(sess, style)
        if img_map:
            all_images[style] = img_map
            variant_count = len(img_map)
            print(f"  [{i:3}/{len(styles)}] {style}: {variant_count} colors")
        else:
            print(f"  [{i:3}/{len(styles)}] {style}: (no flat images found)")
        time.sleep(0.1)  # be polite to the API

    total_variants = sum(len(c) for c in all_images.values())
    print(f"\nScraped {total_variants} color variants across {len(all_images)} styles.")

    # Save cache file
    cache_path = os.path.join(ROOT, 'services', 'ml_images_cache.json')
    with open(cache_path, 'w') as f:
        json.dump(all_images, f)
    print(f"Cache saved to {cache_path}")

    if args.dry_run:
        print("Dry run — skipping database update.")
        return

    # ── Option A: POST directly to the live Railway endpoint ─────────────────
    live_url = 'https://purposefullymadekc.com/admin/products/import-media-library-images'
    if args.post_live:
        print(f"\nPOSTing to {live_url}...")
        if not args.admin_cookie:
            print("ERROR: --post-live requires --admin-cookie with your purposefullymadekc.com session cookie.")
            print("  In Chrome: DevTools → Application → Cookies → purposefullymadekc.com → copy 'session' value")
            sys.exit(1)

        # Build flat images list from all_images
        flat = []
        for style, colors in all_images.items():
            for color, sides in colors.items():
                flat.append({
                    'style':     style,
                    'color':     color,
                    'front_url': sides.get('front', ''),
                    'back_url':  sides.get('back',  ''),
                })

        post_sess = requests.Session()
        post_sess.cookies.set('session', args.admin_cookie, domain='purposefullymadekc.com')
        try:
            r = post_sess.post(live_url, json={'images': flat}, timeout=60)
            print(f"Status: {r.status_code}")
            print(r.text[:500])
        except Exception as e:
            print(f"POST failed: {e}")
        return

    # ── Option B: update local database ─────────────────────────────────────
    print("\nUpdating database...")
    result = update_database(all_images)
    if 'error' in result:
        print(f"ERROR: {result['error']}")
    else:
        print(f"Done! Updated: {result['updated']} | Created: {result['created']} | Skipped: {result['skipped']}")


if __name__ == '__main__':
    main()
