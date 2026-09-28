"""
add_comfort_colors_9360.py
──────────────────────────
Adds Comfort Colors 9360 Heavyweight Ring Spun Tank Top from SanMar,
with every color and garment-only (no model) front/back mockups.

Cost uses the same formula as the rest of the shop:
    retail = ceil(SanMar wholesale) + $19

    py -3.12 scripts/add_comfort_colors_9360.py --dry-run
    py -3.12 scripts/add_comfort_colors_9360.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))
os.environ['SCHEDULER_ENABLED'] = '0'

BRAND = 'Comfort Colors'
CANONICAL_STYLE = 'CC9360'
SANMAR_STYLE_TRIES = ('9360', 'C9360', 'CC9360')
SS_STYLE_ID = 2437
SPEC_URL = (
    'https://www.ssactivewear.com/ShopNow/ItemSpecSheet.aspx'
    f'?ID={SS_STYLE_ID}&LanguageCode=en'
)
NAME = 'Comfort Colors Heavyweight Ring Spun Tank Top'
DESCRIPTION = (
    'The Comfort Colors 9360 Heavyweight Ring Spun Tank Top. Same garment-dyed '
    '6.1 oz ring-spun cotton as the 1717 tee, cut as a relaxed tank with bound '
    'neck and armholes. Lived-in color and a broken-in feel right out of the bag.'
)
FABRIC = '6.1 oz / 100% ring-spun cotton, garment-dyed'
FABRIC_SUMMARY = '100% ring-spun cotton, garment-dyed heavyweight tank'
FIT_GUIDE = 'Unisex relaxed fit. Runs slightly large; size down for a closer fit.'
_MODEL_RE = re.compile(r'model', re.I)


def _retail_from_wholesale(wholesale) -> float:
    try:
        w = float(wholesale or 0)
    except (TypeError, ValueError):
        w = 0.0
    return float(math.ceil(w) + 19) if w > 0 else 0.0


def _color_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())


def _is_model_url(url: str | None) -> bool:
    return bool(url and _MODEL_RE.search(url))


def _garment_url(url: str | None) -> str:
    if not url or _is_model_url(url):
        return ''
    return url


def _find_existing(Product, *styles):
    for style in styles:
        product = Product.query.filter_by(style_number=style).first()
        if product:
            return product
    return None


def _fetch_sanmar_style():
    from services.sanmar_api import SanMarAPI, check_credentials, style_is_allowed

    creds = check_credentials()
    if not creds['ok']:
        print(f'  [SanMar] Missing credentials: {", ".join(creds["missing"])}')
        return None

    api = SanMarAPI()
    allowed = list(SANMAR_STYLE_TRIES)
    for try_style in SANMAR_STYLE_TRIES:
        try:
            grouped = api.fetch_style(try_style, timeout=45)
        except Exception as exc:
            print(f'  [SanMar] style {try_style}: {exc}')
            continue
        for extra_style, data in (grouped or {}).items():
            if style_is_allowed(extra_style, allowed):
                product = api._to_product(data, brand_name=BRAND)
                if product:
                    print(f'  [SanMar] loaded {extra_style} '
                          f'({len(product.get("color_variants") or [])} colors)')
                    return product
    return None


def _ss_ready() -> bool:
    return bool(os.getenv('SSACTIVEWEAR_API_KEY') and os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER'))


def _fetch_ss_style_data():
    from services.ssactivewear_api import SSActivewearAPI

    if not _ss_ready():
        return None
    api = SSActivewearAPI()
    return api.fetch_style_data_by_style_number(
        '9360', brand_name='COMFORT COLORS', style_id=SS_STYLE_ID,
    )


def _variants_from_ss(style_data: dict) -> list[dict]:
    variants = []
    for cv in style_data.get('color_variants') or []:
        name = cv.get('color_name') or ''
        if not name:
            continue
        sizes = cv.get('sizes') or {}
        variants.append({
            'color_name': name,
            'color_id': cv.get('color_id'),
            'front_image': _garment_url(cv.get('front_image')),
            'back_image': _garment_url(cv.get('back_image')),
            'side_image': _garment_url(cv.get('side_image')),
            'size_inventory': json.dumps(sizes) if isinstance(sizes, dict) else sizes,
        })
    return variants


def _product_from_ss(style_data: dict) -> dict:
    variants = _variants_from_ss(style_data)
    colors = [cv['color_name'] for cv in variants]
    sizes = style_data.get('sizes') or []
    wholesale = style_data.get('wholesalePrice') or 0
    return {
        'style_number': CANONICAL_STYLE,
        'wholesale_cost': round(float(wholesale or 0), 2),
        'available_sizes': json.dumps(sizes) if sizes else json.dumps(
            ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL']
        ),
        'available_colors': json.dumps(colors),
        'color_variants': variants,
    }


def _fetch_ss_flats():
    """Ghost / color flats from S&S, used when SanMar sent a model shot."""
    try:
        style_data = _fetch_ss_style_data()
        if not style_data:
            return {}
        flats = {}
        for cv in _variants_from_ss(style_data):
            name = cv.get('color_name') or ''
            if name and (cv.get('front_image') or cv.get('back_image')):
                flats[_color_key(name)] = {
                    'front': cv.get('front_image'),
                    'back': cv.get('back_image'),
                    'color_id': cv.get('color_id'),
                }
        print(f'  [S&S] {len(flats)} garment-only color flats available as backup')
        return flats
    except Exception as exc:
        print(f'  [S&S] could not load flats: {exc}')
        return {}


def _merge_flats(variants: list[dict], ss_flats: dict) -> list[dict]:
    merged = []
    for cv in variants:
        row = dict(cv)
        front = _garment_url(row.get('front_image'))
        back = _garment_url(row.get('back_image'))
        backup = ss_flats.get(_color_key(row.get('color_name') or '')) or {}
        row['front_image'] = front or backup.get('front') or ''
        row['back_image'] = back or backup.get('back') or ''
        if backup.get('color_id') and not row.get('color_id'):
            row['color_id'] = backup['color_id']
        merged.append(row)
    return merged


def _build_record(sanmar_product: dict, ss_flats: dict) -> dict:
    variants = _merge_flats(sanmar_product.get('color_variants') or [], ss_flats)
    colors = [cv.get('color_name') for cv in variants if cv.get('color_name')]
    wholesale = sanmar_product.get('wholesale_cost') or 0
    first_front = next((cv['front_image'] for cv in variants if cv.get('front_image')), '')
    first_back = next((cv['back_image'] for cv in variants if cv.get('back_image')), '')
    return {
        'style_number': CANONICAL_STYLE,
        'name': NAME,
        'brand': BRAND,
        'category': 'Tank',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Tank',
        'sleeve_length': 'Sleeveless',
        'description': DESCRIPTION,
        'fabric_details': FABRIC,
        'fabric_summary': FABRIC_SUMMARY,
        'fit_guide': FIT_GUIDE,
        'softness_rating': 3,
        'base_price': _retail_from_wholesale(wholesale),
        'wholesale_cost': round(float(wholesale or 0), 2),
        'available_sizes': sanmar_product.get('available_sizes') or json.dumps(
            ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL']
        ),
        'available_colors': json.dumps(colors),
        'is_active': True,
        'is_customer_favorite': False,
        'spec_sheet_url': SPEC_URL,
        'front_mockup_template': first_front,
        'back_mockup_template': first_back,
        'color_variants': variants,
    }


def upsert(db, Product, ProductColorVariant, record: dict, dry_run: bool) -> str:
    variants = record.pop('color_variants', []) or []
    existing = _find_existing(Product, CANONICAL_STYLE, '9360', 'C9360')
    missing_photos = [
        cv.get('color_name') for cv in variants
        if not (cv.get('front_image') and cv.get('back_image'))
    ]

    print(f"  name:      {record['name']}")
    print(f"  wholesale: ${record['wholesale_cost']:.2f}")
    print(f"  retail:    ${record['base_price']:.2f}  (ceil(cost) + $19)")
    print(f"  colors:    {len(variants)}")
    print(f"  sizes:     {record['available_sizes']}")
    if missing_photos:
        print(f"  missing garment front+back: {', '.join(missing_photos[:12])}"
              f"{'…' if len(missing_photos) > 12 else ''}")

    if dry_run:
        return 'dry'

    allowed = {
        'style_number', 'name', 'category', 'age_group', 'fit_type',
        'neck_style', 'sleeve_length', 'description', 'base_price',
        'wholesale_cost', 'available_sizes', 'available_colors',
        'is_active', 'is_customer_favorite', 'brand',
        'front_mockup_template', 'back_mockup_template',
        'fit_guide', 'fabric_details', 'fabric_summary',
        'softness_rating', 'spec_sheet_url',
    }
    fields = {k: v for k, v in record.items() if k in allowed}

    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
        product = existing
        action = 'updated'
    else:
        product = Product(**fields)
        db.session.add(product)
        db.session.flush()
        action = 'added'

    for cv in variants:
        color_name = cv.get('color_name') or ''
        if not color_name:
            continue
        row = ProductColorVariant.query.filter_by(
            product_id=product.id, color_name=color_name,
        ).first()
        inv = cv.get('size_inventory')
        if isinstance(inv, dict):
            inv = json.dumps(inv)
        payload = {
            'color_hex': cv.get('color_hex') or None,
            'color_swatch_url': cv.get('color_swatch') or None,
            'front_image_url': cv.get('front_image') or None,
            'back_image_url': cv.get('back_image') or None,
            'side_image_url': cv.get('side_image') or None,
            'size_inventory': inv,
            'ss_color_id': str(cv.get('color_id') or '') or None,
            'last_synced': datetime.utcnow(),
        }
        if row:
            for key, value in payload.items():
                if value is not None:
                    setattr(row, key, value)
        else:
            db.session.add(ProductColorVariant(
                product_id=product.id,
                color_name=color_name,
                **{k: v for k, v in payload.items() if v is not None},
            ))
    return action


def main():
    parser = argparse.ArgumentParser(
        description='Add Comfort Colors 9360 tank from SanMar',
    )
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Comfort Colors 9360 tank\n")

    sanmar_product = _fetch_sanmar_style()
    ss_style = None
    if not sanmar_product:
        print('  [SanMar] not available locally; loading 9360 from S&S with garment-only flats.')
        try:
            ss_style = _fetch_ss_style_data()
        except Exception as exc:
            print(f'ERROR: could not load 9360 from S&S: {exc}')
            sys.exit(1)
        if not ss_style:
            print('ERROR: Style 9360 was not returned. Add SANMAR_* credentials or check S&S.')
            sys.exit(1)
        sanmar_product = _product_from_ss(ss_style)

    ss_flats = {} if ss_style else _fetch_ss_flats()
    record = _build_record(sanmar_product, ss_flats)

    from app import create_app
    from models import db, Product, ProductColorVariant

    app = create_app()
    with app.app_context():
        action = upsert(db, Product, ProductColorVariant, record, args.dry_run)
        if args.dry_run:
            print('\n[DRY RUN] No database changes.')
            return
        db.session.commit()
        print(f'\nDone. Product {action} as {CANONICAL_STYLE}.')
        print('Framing tank mockups onto the Comfort Colors shop card...')
        from scripts.frame_cc9360_mockups import run as frame_run
        framed = frame_run(db, Product, ProductColorVariant, dry_run=False)
        print(f"  framed {framed['saved']} images"
              f"  failed={len(framed['failed'])}")


if __name__ == '__main__':
    main()
