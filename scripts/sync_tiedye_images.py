"""Pull front/back color photos onto Port & Company tie-dye styles.

Prefers SanMar SOAP when credentials are present. Otherwise scrapes the
public dealer pages (Apparel4Print) so the shop/customizer have real photos.

    py -3.12 scripts/sync_tiedye_images.py --dry-run
    py -3.12 scripts/sync_tiedye_images.py
"""
import os
import re
import sys
import json
import argparse
from datetime import datetime
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

STYLES = ['PC147', 'PC147Y', 'LPC147V', 'PC147LS', 'PC147YLS', 'PC145', 'PC144']

A4P_PAGES = {
    'PC147': 'https://www.apparel4print.com/port-company/port-company-pc147-tie-dye-tee.html',
    'PC147Y': 'https://www.apparel4print.com/port-company/port-company-pc147y-youth-tie-dye-tee.html',
    'LPC147V': 'https://www.apparel4print.com/port-company/port-company-lpc147v-ladies-tie-dye-v-neck-tee.html',
    'PC147LS': 'https://www.apparel4print.com/port-company/port-company-pc147ls-tie-dye-long-sleeve-tee.html',
    # Youth LS often mirrors adult LS flats when a dedicated dealer page is missing.
    'PC147YLS': 'https://www.apparel4print.com/port-company/port-company-pc147ls-tie-dye-long-sleeve-tee.html',
    'PC145': 'https://www.apparel4print.com/port-company/port-company-pc145-crystal-tie-dye-tee.html',
    'PC144': 'https://www.apparel4print.com/port-company/port-company-pc144-crystal-tie-dye-pullover-hoodie.html',
}

JOES_HANDLES = {
    'PC147': 'c6ab2f5a14e54c6b844df03631557c8f-pc147-black',
    'PC147Y': 'c6ab2f5a14e54c6b844df03631557c8f-pc147y-black',
    'PC145': 'port-company-crystal-tie-dye-tee-pc145-port-company-pc145',
    'PC144': 'port-company-pc144-crystal-tie-dye-pullover-hoodie-port-co-pc144',
}

KEEP_UPPER = {'USA', 'PFD'}
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}


def normalize_color(raw, style):
    s = (raw or '').strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(rf'^(Port\s*&\s*Company\s+)?{re.escape(style)}\s*', '', s, flags=re.I)
    s = re.sub(r'\s*/\s*', '/', s)
    s = s.strip(' -')
    if not s or s.upper() == style.upper() or s.lower() in ('port & company', 'port and company'):
        return ''
    parts = []
    for word in s.split(' '):
        if '/' in word:
            parts.append('/'.join(_title_token(p) for p in word.split('/') if p))
        else:
            parts.append(_title_token(word))
    return ' '.join(p for p in parts if p)


def _title_token(word):
    if not word:
        return ''
    upper = word.upper()
    if upper in KEEP_UPPER:
        return upper
    if word.isupper() or word.islower():
        return word.title()
    return word


def _get(url, timeout=40):
    import requests
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp


def scrape_apparel4print(style):
    """Return {color: {'front_image', 'back_image'}} from dealer product photos."""
    url = A4P_PAGES[style]
    html = _get(url).text
    html = html.replace('&amp;', '&')
    hits = []
    patterns = [
        re.compile(
            r'https://www\.apparel4print\.com/(\d+)-(?:thickbox_default|large_default|cart_default)/'
            r'[^"\']+\.jpg["\'][^>]*?(?:title|alt)="([^"]*)"',
            re.I,
        ),
        re.compile(
            r'(?:title|alt)="([^"]*)"[^>]*?https://www\.apparel4print\.com/(\d+)-'
            r'(?:thickbox_default|large_default|cart_default)/',
            re.I,
        ),
    ]
    for pattern in patterns:
        for a, b in pattern.findall(html):
            if a.isdigit():
                hits.append((a, b))
            elif b.isdigit():
                hits.append((b, a))

    slug_by_id = {}
    for img_id, slug in re.findall(
        r'https://www\.apparel4print\.com/(\d+)-(?:thickbox_default|large_default|cart_default)/([^"\'?\s]+)\.jpg',
        html,
        flags=re.I,
    ):
        slug_by_id.setdefault(img_id, slug)

    grouped = OrderedDict()
    seen_ids = set()
    for img_id, title in hits:
        if img_id in seen_ids:
            continue
        color = normalize_color(title, style)
        if not color:
            continue
        seen_ids.add(img_id)
        slug = slug_by_id.get(img_id) or 'port-company'
        image_url = f'https://www.apparel4print.com/{img_id}-thickbox_default/{slug}.jpg'
        grouped.setdefault(color, [])
        if image_url not in grouped[color]:
            grouped[color].append(image_url)

    out = {}
    for color, urls in grouped.items():
        front = urls[0]
        back = urls[1] if len(urls) > 1 else urls[0]
        out[color] = {'front_image': front, 'back_image': back, 'color_hex': '', 'color_swatch': ''}
    return out


def scrape_joesusa(style):
    """Fallback: one Shopify photo per color (usually front)."""
    handle = JOES_HANDLES.get(style)
    if not handle:
        q = style.lower()
        search = _get(f'https://joesusa.com/search/suggest.json?q={q}&resources[type]=product')
        data = search.json()
        products = (((data.get('resources') or {}).get('results') or {}).get('products') or [])
        for p in products:
            h = p.get('handle') or ''
            if style.lower() in h.lower() or style.lower() in (p.get('title') or '').lower():
                handle = h
                break
    if not handle:
        return {}
    data = _get(f'https://joesusa.com/products/{handle}.json').json()
    product = data.get('product') or {}
    images_by_id = {img.get('id'): img.get('src') for img in (product.get('images') or []) if img.get('src')}
    out = {}
    for variant in product.get('variants') or []:
        color = normalize_color(variant.get('option1') or '', style)
        if not color or color in out:
            continue
        img = None
        featured = variant.get('featured_image') or {}
        img = featured.get('src')
        if not img:
            img = images_by_id.get(variant.get('image_id'))
        if not img:
            continue
        img = img.split('?')[0]
        if len(img) > 480:
            img = img[:480]
        out[color] = {'front_image': img, 'back_image': img, 'color_hex': '', 'color_swatch': ''}
    return out


def colors_from_sanmar(style, api):
    grouped = api.fetch_style(style)
    style_data = None
    for key, data in (grouped or {}).items():
        if key.upper() == style.upper():
            style_data = data
            break
    if not style_data and grouped:
        style_data = next(iter(grouped.values()))
    colors = (style_data or {}).get('color_variants') or {}
    out = {}
    for color_name, cv in colors.items():
        front = (cv.get('front_image') or '').strip()
        back = (cv.get('back_image') or '').strip() or front
        if not front:
            continue
        out[color_name] = {
            'front_image': front,
            'back_image': back,
            'color_hex': (cv.get('color_hex') or '').strip(),
            'color_swatch': (cv.get('color_swatch') or '').strip(),
        }
    return out


def apply_colors(product, colors, dry_run):
    from models import db, ProductColorVariant

    color_names = list(colors.keys())
    added = updated = 0
    if not dry_run:
        product.available_colors = json.dumps(color_names)
        first = next(iter(colors.values()))
        if first.get('front_image'):
            product.front_mockup_template = first['front_image'][:500]
        if first.get('back_image'):
            product.back_mockup_template = first['back_image'][:500]
        product.updated_at = datetime.utcnow()

    for color_name, cv in colors.items():
        front = (cv.get('front_image') or '')[:500]
        back = (cv.get('back_image') or front)[:500]
        hex_val = (cv.get('color_hex') or '').strip() or None
        swatch = (cv.get('color_swatch') or '').strip() or None
        if dry_run:
            continue
        existing = ProductColorVariant.query.filter_by(
            product_id=product.id, color_name=color_name
        ).first()
        if existing:
            existing.front_image_url = front or existing.front_image_url
            existing.back_image_url = back or existing.back_image_url
            if hex_val:
                existing.color_hex = hex_val
            if swatch:
                existing.color_swatch_url = swatch
            existing.last_synced = datetime.utcnow()
            updated += 1
        else:
            db.session.add(ProductColorVariant(
                product_id=product.id,
                color_name=color_name,
                front_image_url=front or None,
                back_image_url=back or None,
                color_hex=hex_val,
                color_swatch_url=swatch,
                last_synced=datetime.utcnow(),
            ))
            added += 1
    return added, updated, color_names


def main():
    parser = argparse.ArgumentParser(description='Sync Port & Company tie-dye color images')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--scrape-only', action='store_true', help='Print scraped colors; skip the database')
    parser.add_argument('--source', choices=['auto', 'sanmar', 'dealer'], default='auto')
    args = parser.parse_args()

    if args.scrape_only:
        for style in STYLES:
            try:
                colors = scrape_apparel4print(style)
                source = 'apparel4print'
            except Exception as e:
                print(f'  ERR   {style:12s}  apparel4print: {e}')
                colors = {}
                source = ''
            if not colors:
                try:
                    colors = scrape_joesusa(style)
                    source = 'joesusa'
                except Exception as e:
                    print(f'  ERR   {style:12s}  joesusa: {e}')
            if not colors:
                print(f'  NONE  {style}')
                continue
            backs = sum(1 for c in colors.values() if c['back_image'] != c['front_image'])
            print(f'  {style:12s}  {len(colors):2d} colors  source={source}  distinct-back={backs}')
            for name, cv in colors.items():
                print(f'         {name}: {cv["front_image"]}')
        return

    sanmar_ok = False
    api = None
    if args.source in ('auto', 'sanmar'):
        try:
            from services.sanmar_api import SanMarAPI, check_credentials
            creds = check_credentials()
            sanmar_ok = bool(creds.get('ok'))
            if sanmar_ok:
                api = SanMarAPI()
                print('SanMar credentials found — using official product images.')
            elif args.source == 'sanmar':
                print('Missing SanMar credentials:', ', '.join(creds.get('missing') or []))
                sys.exit(1)
            else:
                print('No SanMar credentials locally — using dealer product photos.')
        except Exception as e:
            if args.source == 'sanmar':
                raise
            print(f'SanMar unavailable ({e}) — using dealer product photos.')

    from app import create_app
    from models import db, Product

    print('Loading app (this can take a minute against Railway)...', flush=True)
    app = create_app()
    with app.app_context():
        added = updated = skipped = 0
        for style in STYLES:
            product = Product.query.filter_by(style_number=style).first()
            if not product:
                print(f'  MISS  {style:12s}  not in catalog')
                skipped += 1
                continue

            colors = {}
            source = ''
            if sanmar_ok and api is not None:
                try:
                    colors = colors_from_sanmar(style, api)
                    source = 'sanmar'
                except Exception as e:
                    print(f'  WARN  {style:12s}  SanMar failed: {e}')
            if not colors:
                try:
                    colors = scrape_apparel4print(style)
                    source = 'apparel4print'
                except Exception as e:
                    print(f'  WARN  {style:12s}  Apparel4Print failed: {e}')
            if not colors:
                try:
                    colors = scrape_joesusa(style)
                    source = 'joesusa'
                except Exception as e:
                    print(f'  WARN  {style:12s}  Joe\'s USA failed: {e}')
            if not colors:
                print(f'  NONE  {style:12s}  no color photos found')
                skipped += 1
                continue

            a, u, names = apply_colors(product, colors, args.dry_run)
            added += a
            updated += u
            with_back = sum(1 for c in colors.values() if c.get('back_image') and c.get('back_image') != c.get('front_image'))
            print(f'  {style:12s}  {len(names):2d} colors  source={source}  distinct-back={with_back}')
            for name in names[:8]:
                print(f'         {name}')
            if len(names) > 8:
                print(f'         ... +{len(names) - 8} more')

        if args.dry_run:
            print('\n[DRY RUN] No changes made.')
            return
        db.session.commit()
        print(f'\nDone. variants added={added} updated={updated} styles skipped={skipped}')


if __name__ == '__main__':
    main()
