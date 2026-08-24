"""Replace on-model Port & Company tie-dye photos with garment-only flat front/back.

Source: BigTopShirtShop product JSON (SanMar flats labeled Flat Front / Flat Back).

    py -3.12 scripts/load_tiedye_flats.py --dry-run
    py -3.12 scripts/load_tiedye_flats.py
"""
import os
import re
import sys
import json
from datetime import datetime
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

STYLES = ['PC147', 'PC147Y', 'LPC147V', 'PC147LS', 'PC147YLS', 'PC145', 'PC144']
SHOP = 'https://www.bigtopshirtshop.com'
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    )
}


def _get(url, timeout=40):
    import requests
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def search_handles(query, style=None):
    style = style or query.split()[0]
    found = []
    for page in range(1, 8):
        url = f'{SHOP}/search?q={quote(query)}&type=product'
        if page > 1:
            url += f'&page={page}'
        html = _get(url).text
        page_handles = re.findall(r'/products/(port-company-[a-z0-9-]+)', html, flags=re.I)
        if not page_handles:
            break
        found.extend(page_handles)
    handles = sorted(set(found))
    token = f'-{style.lower()}-'
    token_end = f'-{style.lower()}'
    out = []
    for h in handles:
        hl = h.lower()
        if token in hl or hl.endswith(token_end):
            if style.upper() == 'PC147' and (
                'pc147y' in hl or 'pc147ls' in hl or 'pc147yls' in hl or 'lpc147' in hl
            ):
                continue
            if style.upper() == 'PC147LS' and 'pc147yls' in hl:
                continue
            if style.upper() == 'PC147Y' and 'pc147yls' in hl:
                continue
            out.append(h)
    return out


def color_from_title(title, style):
    t = (title or '').strip()
    if ' - ' in t:
        t = t.rsplit(' - ', 1)[-1]
    t = re.sub(rf'\b{re.escape(style)}\b', '', t, flags=re.I).strip(' -')
    t = t.replace('Turquoise Blue', 'Turquoise').replace('Royal Blue', 'Royal')
    return t


def normalize(name):
    s = (name or '').lower()
    s = s.replace('&', 'and')
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s


COLOR_ALIASES = {
    'turquoiseblue': 'Turquoise',
    'royalblue': 'Royal',
    'island': 'Island Spiral',
    'blackgalaxy': 'Black Galaxy Spiral',
    'watercolor': 'Watercolor Spiral',
    'lagoonblue': 'Lagoon Colorburst',
    'lagoon': 'Lagoon Colorburst',
    'sherbetorange': 'Sherbet Colorburst',
    'sherbet': 'Sherbet Colorburst',
    'kellygreen': 'Kelly',
    'navyblue': 'Navy',
    'blacktealgreen': 'Black/Teal',
    'tealgreen': 'Teal',
    'jeweltone': 'Jeweltone Colorburst',
    'lemonlimegreen': 'Lemon Lime',
    'planetearth': 'Planet Earth Colorburst',
}


def match_existing(color, existing):
    n = normalize(color)
    by_norm = {normalize(x): x for x in existing}
    if n in by_norm:
        return by_norm[n]
    alias = COLOR_ALIASES.get(n)
    if alias:
        return by_norm.get(normalize(alias))
    return None


def flats_from_product(handle):
    data = _get(f'{SHOP}/products/{handle}.json').json()
    product = data.get('product') or {}
    color = color_from_title(product.get('title') or '', '')
    front = back = None
    for img in product.get('images') or []:
        src = (img.get('src') or '').strip()
        alt = (img.get('alt') or '').lower()
        name = src.lower()
        if not src:
            continue
        if 'model' in alt or '_model_' in name:
            continue
        blob = alt + ' ' + name
        if 'flat_front' in name or 'flat front' in alt:
            front = src.split('?')[0]
        elif 'flat_back' in name or 'flat back' in alt:
            back = src.split('?')[0]
        elif 'flat' in blob and 'front' in blob and not front:
            front = src.split('?')[0]
        elif 'flat' in blob and 'back' in blob and not back:
            back = src.split('?')[0]
    if front and len(front) > 500:
        front = front[:500]
    if back and len(back) > 500:
        back = back[:500]
    return color, front, back


def main():
    dry = '--dry-run' in sys.argv
    from app import create_app
    from models import db, Product, ProductColorVariant

    print('Loading app...', flush=True)
    app = create_app()
    with app.app_context():
        updated = missing_style = 0
        for style in STYLES:
            product = Product.query.filter_by(style_number=style).first()
            if not product:
                print(f'  MISS  {style}')
                missing_style += 1
                continue
            variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
            existing = [v.color_name for v in variants]
            try:
                handles = search_handles(style, style)
            except Exception as e:
                print(f'  ERR   {style} search: {e}')
                continue
            print(f'  {style:12s}  {len(handles)} dealer pages  {len(existing)} colors in catalog')
            seen_handles = set()
            matched_names = set()
            first_front = first_back = None
            matched = 0

            def apply_handle(handle):
                nonlocal first_front, first_back, matched, updated
                if handle in seen_handles:
                    return
                seen_handles.add(handle)
                try:
                    color, front, back = flats_from_product(handle)
                except Exception as e:
                    print(f'         skip {handle}: {e}')
                    return
                if not front and not back:
                    print(f'         no flats  {handle}  ({color})')
                    return
                target = match_existing(color, existing)
                if not target:
                    print(f'         unmatched color {color!r} from {handle}')
                    return
                if target in matched_names:
                    return
                variant = next(v for v in variants if v.color_name == target)
                print(f'         {target}: front={bool(front)} back={bool(back)}')
                matched += 1
                matched_names.add(target)
                if dry:
                    return
                if front:
                    variant.front_image_url = front
                    first_front = first_front or front
                if back:
                    variant.back_image_url = back
                    first_back = first_back or back
                variant.last_synced = datetime.utcnow()
                updated += 1

            for handle in handles:
                apply_handle(handle)
            leftover = [c for c in existing if c not in matched_names]
            for color in leftover:
                try:
                    extra = search_handles(f'{style} {color}', style)
                except Exception:
                    extra = []
                for handle in extra:
                    apply_handle(handle)
                    if color in matched_names:
                        break
            if not dry and first_front:
                product.front_mockup_template = first_front
            if not dry and first_back:
                product.back_mockup_template = first_back
            still = [c for c in existing if c not in matched_names]
            print(f'         matched {matched}/{len(existing)}' + (f'  still missing: {still}' if still else ''))

        if dry:
            print('\n[DRY RUN] No changes made.')
            return
        db.session.commit()
        print(f'\nDone. variants updated={updated} styles missing={missing_style}')


if __name__ == '__main__':
    main()
