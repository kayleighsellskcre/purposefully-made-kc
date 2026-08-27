"""
ensure_pc146_tiedye_hoodies.py
──────────────────────────────
Ensure the REGULAR Port & Company Tie-Dye pullover hoodies exist correctly:

  PC146   Adult Tie-Dye Pullover Hooded Sweatshirt
  PC146Y  Youth Tie-Dye Pullover Hooded Sweatshirt

These are NOT Crystal Tie-Dye (PC144 / PC145). PC146Y was previously seeded
with Crystal colors/images from PC144 — this script replaces that.

Also activates both styles so they appear in shop + group-order product pickers.

    py -3.12 scripts/ensure_pc146_tiedye_hoodies.py --dry-run
    py -3.12 scripts/ensure_pc146_tiedye_hoodies.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=True)

ADULT_SIZES = ["S", "M", "L", "XL", "2XL", "3XL", "4XL"]
YOUTH_SIZES = ["XS", "S", "M", "L", "XL"]

PC146 = {
    'style_number': 'PC146',
    'name': 'Port & Company Tie-Dye Pullover Hooded Sweatshirt',
    'brand': 'Port & Company',
    'category': 'Hoodie',
    'age_group': 'adult',
    'fit_type': 'Unisex',
    'neck_style': 'Hooded',
    'sleeve_length': 'Long Sleeve',
    'base_price': 51.00,
    'wholesale_cost': 32.06,
    'available_sizes': json.dumps(ADULT_SIZES),
    'description': (
        "Port & Company Tie-Dye Pullover Hooded Sweatshirt — the classic spiral "
        "tie-dye hoodie (not crystal). Hand-dyed 80/20 fleece with a two-ply hood, "
        "dyed-to-match drawcords, and a front pouch pocket. Perfect for group orders "
        "that want the regular PC147 look in a hoodie."
    ),
    'fabric_details': '7.8 oz / 80% cotton, 20% polyester fleece; prepared-for-dye; tear-away label',
    'fit_guide': 'Unisex classic fit; true to size. Each garment has slight color variation from the tie-dye process.',
    'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC146.pdf',
    'is_active': True,
    'is_customer_favorite': True,
}

PC146Y = {
    'style_number': 'PC146Y',
    'name': 'Port & Company Youth Tie-Dye Pullover Hooded Sweatshirt',
    'brand': 'Port & Company',
    'category': 'Hoodie',
    'age_group': 'youth',
    'fit_type': 'Unisex',
    'neck_style': 'Hooded',
    'sleeve_length': 'Long Sleeve',
    'base_price': 45.00,
    'wholesale_cost': 24.00,
    'available_sizes': json.dumps(YOUTH_SIZES),
    'description': (
        "Youth Tie-Dye Pullover Hooded Sweatshirt — the regular (non-crystal) PC146 "
        "hoodie sized for kids. Hand-dyed fleece with a two-ply hood (no drawcord) "
        "and front pouch pocket. Pairs with the youth PC147Y tee for matching sets."
    ),
    'fabric_details': '7.8 oz / 80% cotton, 20% polyester fleece; prepared-for-dye; no drawcord; tear-away label',
    'fit_guide': 'Youth classic fit; sizes XS–XL. Each garment has slight color variation.',
    'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC146Y.pdf',
    'is_active': True,
    'is_customer_favorite': False,
}


def connect():
    import psycopg2
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is not set')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return psycopg2.connect(url, connect_timeout=30)


def upsert_product(cur, data, dry_run: bool) -> int:
    style = data['style_number']
    cur.execute('SELECT id, name FROM product WHERE style_number = %s', (style,))
    row = cur.fetchone()
    fields = [
        'name', 'brand', 'category', 'age_group', 'fit_type', 'neck_style',
        'sleeve_length', 'base_price', 'wholesale_cost', 'available_sizes',
        'description', 'fabric_details', 'fit_guide', 'spec_sheet_url',
        'is_active', 'is_customer_favorite',
    ]
    if row:
        pid, old_name = row
        print(f'  UPDATE {style:8s}  was: {old_name}')
        if not dry_run:
            sets = ', '.join(f'{f} = %s' for f in fields)
            cur.execute(
                f'UPDATE product SET {sets}, updated_at = %s WHERE id = %s',
                [data[f] for f in fields] + [datetime.utcnow(), pid],
            )
        return pid

    print(f'  ADD    {style:8s}  {data["name"]}')
    if dry_run:
        return -1
    cols = ['style_number'] + fields + ['created_at', 'updated_at']
    placeholders = ', '.join(['%s'] * len(cols))
    cur.execute(
        f'INSERT INTO product ({", ".join(cols)}) VALUES ({placeholders}) RETURNING id',
        [data['style_number']] + [data[f] for f in fields] + [datetime.utcnow(), datetime.utcnow()],
    )
    return cur.fetchone()[0]


def replace_variants(cur, product_id: int, style: str, colors: dict, dry_run: bool):
    """Replace all color variants with scraped regular tie-dye colors."""
    cur.execute(
        'SELECT color_name FROM product_color_variant WHERE product_id = %s ORDER BY color_name',
        (product_id,),
    )
    old = [r[0] for r in cur.fetchall()]
    print(f'         old colors ({len(old)}): {", ".join(old) or "(none)"}')
    print(f'         new colors ({len(colors)}): {", ".join(colors.keys())}')

    if dry_run or product_id < 0:
        return

    cur.execute('DELETE FROM product_color_variant WHERE product_id = %s', (product_id,))
    color_names = []
    first_front = first_back = None
    for color_name, cv in colors.items():
        front = (cv.get('front_image') or '')[:500] or None
        back = (cv.get('back_image') or front or '')[:500] or None
        if first_front is None and front:
            first_front, first_back = front, back
        color_names.append(color_name)
        cur.execute(
            """
            INSERT INTO product_color_variant
                (product_id, color_name, front_image_url, back_image_url,
                 color_hex, color_swatch_url, last_synced)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                product_id,
                color_name,
                front,
                back,
                (cv.get('color_hex') or None),
                (cv.get('color_swatch') or None),
                datetime.utcnow(),
            ),
        )

    cur.execute(
        """
        UPDATE product
        SET available_colors = %s,
            front_mockup_template = COALESCE(%s, front_mockup_template),
            back_mockup_template = COALESCE(%s, back_mockup_template),
            updated_at = %s
        WHERE id = %s
        """,
        (json.dumps(color_names), first_front, first_back, datetime.utcnow(), product_id),
    )


def scrape_colors(style: str) -> dict:
    import importlib.util
    path = ROOT / 'scripts' / 'sync_tiedye_images.py'
    spec = importlib.util.spec_from_file_location('sync_tiedye_images', path)
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)

    sync.A4P_PAGES['PC146'] = (
        'https://www.apparel4print.com/port-company/'
        'port-company-pc146-tie-dye-pullover-hooded-sweatshirt.html'
    )
    sync.A4P_PAGES['PC146Y'] = (
        'https://www.apparel4print.com/port-company/'
        'port-company-pc146y-youth-tie-dye-pullover-hooded-sweatshirt.html'
    )

    try:
        colors = sync.scrape_apparel4print(style)
        if colors:
            print(f'         scraped {len(colors)} colors from Apparel4Print')
            return colors
    except Exception as exc:
        print(f'         Apparel4Print failed for {style}: {exc}')

    try:
        colors = sync.scrape_joesusa(style)
        if colors:
            print(f'         scraped {len(colors)} colors from JoesUSA fallback')
            return colors
    except Exception as exc:
        print(f'         JoesUSA failed for {style}: {exc}')
    return {}


def main():
    parser = argparse.ArgumentParser(description='Ensure PC146 / PC146Y regular tie-dye hoodies')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Ensuring PC146 + PC146Y (regular Tie-Dye hoodies)...\n")

    conn = connect()
    try:
        cur = conn.cursor()
        for data in (PC146, PC146Y):
            style = data['style_number']
            print(f'── {style} ──')
            pid = upsert_product(cur, data, args.dry_run)
            colors = scrape_colors(style)
            if not colors:
                print(f'  WARN  no colors scraped for {style} — product metadata only')
            else:
                replace_variants(cur, pid, style, colors, args.dry_run)
            print()

        if args.dry_run:
            conn.rollback()
            print('[DRY RUN] No changes written.')
        else:
            conn.commit()
            print('Done. PC146 / PC146Y are active with regular Tie-Dye colors.')
            print('They will show in Shop and in the group-order product picker.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
