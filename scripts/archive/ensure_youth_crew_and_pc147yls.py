"""
ensure_youth_crew_and_pc147yls.py
─────────────────────────────────
Upsert SanMar styles needed for group orders (direct SQL — no Flask import):

  BC3901Y   Youth Sponge Fleece Raglan Crewneck (flat front/back from static/sanmar)
  PC147YLS  Youth Tie-Dye Long Sleeve Tee (flat images cloned from PC147LS / PC147Y)

Also:
  - Replace hollow BC3945Y with BC3901Y in collections
  - Deactivate BC3945Y

Run from project root:

    py -3.12 scripts/ensure_youth_crew_and_pc147yls.py --dry-run
    py -3.12 scripts/ensure_youth_crew_and_pc147yls.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

YOUTH_SIZES = ["XS", "S", "M", "L", "XL"]
YOUTH_SIZES_JSON = json.dumps(YOUTH_SIZES)
YOUTH_INV = json.dumps({s: 0 for s in YOUTH_SIZES})


def _norm_color(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())


def _scan_sanmar_folder(folder: Path, folder_name: str) -> dict[str, dict]:
    file_map: dict[str, dict] = {}
    if not folder.is_dir():
        return file_map
    pattern = re.compile(
        rf'^{re.escape(folder_name)}_(.+?)_(front|back)\.jpe?g$',
        re.IGNORECASE,
    )
    for f in folder.iterdir():
        if not f.is_file():
            continue
        m = pattern.match(f.name)
        if not m:
            continue
        raw_color = m.group(1).replace('_', ' ')
        side = m.group(2).lower()
        key = _norm_color(raw_color)
        entry = file_map.setdefault(key, {'color_name': raw_color})
        entry['color_name'] = raw_color
        entry[side] = f'/static/sanmar/{folder_name}/{f.name}'
    return file_map


def connect():
    import psycopg2
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is not set')
    return psycopg2.connect(url, connect_timeout=30)


def product_id(cur, style: str):
    cur.execute('SELECT id FROM product WHERE style_number = %s', (style,))
    row = cur.fetchone()
    return row[0] if row else None


def upsert_product(cur, style: str, fields: dict, dry_run: bool) -> int | None:
    pid = product_id(cur, style)
    cols = list(fields.keys())
    if pid is None:
        print(f'  ADD   {style}')
        if dry_run:
            return None
        placeholders = ', '.join(['%s'] * (len(cols) + 1))
        col_sql = ', '.join(['style_number'] + cols)
        cur.execute(
            f'INSERT INTO product ({col_sql}) VALUES ({placeholders}) RETURNING id',
            [style] + [fields[c] for c in cols],
        )
        return cur.fetchone()[0]

    print(f'  UPDATE {style} id={pid}')
    if dry_run:
        return pid
    sets = ', '.join(f'{c} = %s' for c in cols)
    cur.execute(
        f'UPDATE product SET {sets}, updated_at = NOW() WHERE id = %s',
        [fields[c] for c in cols] + [pid],
    )
    return pid


def upsert_variant(cur, product_id_: int, color_name: str, front: str | None,
                   back: str | None, dry_run: bool, extra: dict | None = None):
    cur.execute(
        'SELECT id, front_image_url, back_image_url, size_inventory '
        'FROM product_color_variant '
        'WHERE product_id = %s AND lower(color_name) = lower(%s)',
        (product_id_, color_name),
    )
    row = cur.fetchone()
    if dry_run:
        return
    inv = YOUTH_INV
    hex_ = (extra or {}).get('color_hex')
    swatch = (extra or {}).get('color_swatch_url')
    if row is None:
        cur.execute(
            'INSERT INTO product_color_variant '
            '(product_id, color_name, color_hex, color_swatch_url, '
            ' front_image_url, back_image_url, size_inventory) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s)',
            (product_id_, color_name, hex_, swatch, front, back, inv),
        )
        print(f'    + color {color_name}')
        return
    vid = row[0]
    cur.execute(
        'UPDATE product_color_variant SET '
        'color_name = %s, '
        'front_image_url = COALESCE(%s, front_image_url), '
        'back_image_url = COALESCE(%s, back_image_url), '
        'size_inventory = CASE WHEN size_inventory IS NULL OR size_inventory = \'\' '
        '  OR size_inventory = \'{}\' THEN %s ELSE size_inventory END '
        'WHERE id = %s',
        (color_name, front, back, inv, vid),
    )


def ensure_bc3901y(cur, dry_run: bool) -> int | None:
    sanmar_map = _scan_sanmar_folder(ROOT / 'static' / 'sanmar' / '3901Y', '3901Y')
    colors = [v['color_name'] for v in sanmar_map.values()]
    first_front = next((v.get('front') for v in sanmar_map.values() if v.get('front')), None)
    first_back = next((v.get('back') for v in sanmar_map.values() if v.get('back')), None)
    fields = {
        'name': 'BELLA+CANVAS Youth Sponge Fleece Raglan Crewneck Sweatshirt BC3901Y',
        'brand': 'Bella+Canvas',
        'category': 'Sweatshirt',
        'age_group': 'youth',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'base_price': 42.00,
        'wholesale_cost': 20.98,
        'available_sizes': YOUTH_SIZES_JSON,
        'available_colors': json.dumps(colors),
        'description': (
            "Youth Sponge Fleece Raglan Crewneck — the same soft Bella+Canvas "
            "sponge fleece as the adult BC3901, sized for kids. Flat front and "
            "back mockups for group-order customizing."
        ),
        'fabric_details': '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        'fit_guide': 'Youth sizing; true to size. Relaxed fit.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3901Y.pdf',
        'is_active': True,
        'front_mockup_template': first_front,
        'back_mockup_template': first_back,
    }
    print(f'  colors from static/sanmar/3901Y: {len(sanmar_map)}')
    pid = upsert_product(cur, 'BC3901Y', fields, dry_run)
    if pid is None or dry_run:
        return pid
    for paths in sanmar_map.values():
        upsert_variant(cur, pid, paths['color_name'], paths.get('front'), paths.get('back'), dry_run)
    return pid


def fix_hollow_bc3945y(cur, bc3901y_id: int | None, dry_run: bool):
    hollow_id = product_id(cur, 'BC3945Y')
    if hollow_id is None:
        print('  SKIP  BC3945Y not present')
        return
    cur.execute(
        'SELECT collection_id FROM collection_products WHERE product_id = %s',
        (hollow_id,),
    )
    coll_ids = [r[0] for r in cur.fetchall()]
    print(f'  FIX   BC3945Y id={hollow_id} in {len(coll_ids)} collection(s)')
    if dry_run:
        return
    for cid in coll_ids:
        if bc3901y_id:
            cur.execute(
                'INSERT INTO collection_products (collection_id, product_id) '
                'VALUES (%s, %s) ON CONFLICT DO NOTHING',
                (cid, bc3901y_id),
            )
            print(f'    collection {cid}: + BC3901Y')
        cur.execute(
            'DELETE FROM collection_products WHERE collection_id = %s AND product_id = %s',
            (cid, hollow_id),
        )
        print(f'    collection {cid}: - BC3945Y')
    cur.execute(
        'UPDATE product SET is_active = FALSE, available_sizes = %s, updated_at = NOW() '
        'WHERE id = %s',
        (json.dumps([]), hollow_id),
    )
    print('    deactivated BC3945Y')


def ensure_pc147yls(cur, dry_run: bool) -> int | None:
    fields = {
        'name': 'Port & Company Youth Tie-Dye Long Sleeve Tee',
        'brand': 'Port & Company',
        'category': 'Long Sleeve',
        'age_group': 'youth',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'base_price': 28.00,
        'wholesale_cost': 12.80,
        'available_sizes': YOUTH_SIZES_JSON,
        'description': (
            "Youth Tie-Dye Long Sleeve Tee — vibrant prepared-for-dye color with "
            "rib-knit cuffs, sized for kids. Great for camps, fall spirit wear, "
            "and matching family group orders."
        ),
        'fabric_details': '5.4 oz / 100% cotton; rib knit cuffs; prepared-for-dye; tear-away label',
        'fit_guide': 'Youth classic fit; sizes XS–XL. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147YLS.pdf',
        'is_active': True,
    }
    pid = upsert_product(cur, 'PC147YLS', fields, dry_run)

    donor_id = None
    donor_style = None
    for style in ('PC147LS', 'PC147Y', 'PC147'):
        donor_id = product_id(cur, style)
        if donor_id:
            donor_style = style
            break
    if not donor_id:
        print('    WARN no donor styles with images (PC147LS/PC147Y/PC147)')
        return pid

    cur.execute(
        'SELECT color_name, color_hex, color_swatch_url, front_image_url, back_image_url '
        'FROM product_color_variant WHERE product_id = %s ORDER BY color_name',
        (donor_id,),
    )
    rows = cur.fetchall()
    print(f'    cloning color flats from {donor_style} ({len(rows)} colors)')
    if dry_run or pid is None:
        return pid

    color_names = []
    first_front = first_back = None
    for color_name, color_hex, swatch, front, back in rows:
        color_names.append(color_name)
        if front and not first_front:
            first_front = front
        if back and not first_back:
            first_back = back
        upsert_variant(
            cur, pid, color_name, front, back, dry_run,
            {'color_hex': color_hex, 'color_swatch_url': swatch},
        )

    cur.execute(
        'UPDATE product SET available_colors = %s, '
        'front_mockup_template = COALESCE(%s, front_mockup_template), '
        'back_mockup_template = COALESCE(%s, back_mockup_template), '
        'updated_at = NOW() WHERE id = %s',
        (json.dumps(color_names), first_front, first_back, pid),
    )
    return pid


def ensure_collection_8(cur, product_ids: list[int | None], dry_run: bool):
    cur.execute('SELECT id, name FROM collection WHERE id = 8')
    row = cur.fetchone()
    if not row:
        print('  SKIP  collection 8 not found')
        return
    cid, name = row
    for pid in product_ids:
        if not pid:
            continue
        cur.execute(
            'SELECT 1 FROM collection_products WHERE collection_id = %s AND product_id = %s',
            (cid, pid),
        )
        if cur.fetchone():
            cur.execute('SELECT style_number FROM product WHERE id = %s', (pid,))
            style = cur.fetchone()[0]
            print(f'  OK    collection 8: already has {style}')
            continue
        cur.execute('SELECT style_number FROM product WHERE id = %s', (pid,))
        style = cur.fetchone()[0]
        print(f'  ADD   collection 8 ({name}): {style}')
        if not dry_run:
            cur.execute(
                'INSERT INTO collection_products (collection_id, product_id) '
                'VALUES (%s, %s) ON CONFLICT DO NOTHING',
                (cid, pid),
            )


def main():
    parser = argparse.ArgumentParser(description='Ensure BC3901Y + PC147YLS for shop/group orders')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Ensuring youth crew + PC147YLS...\n")
    conn = connect()
    try:
        cur = conn.cursor()
        bc_id = ensure_bc3901y(cur, args.dry_run)
        fix_hollow_bc3945y(cur, bc_id, args.dry_run)
        pc_id = ensure_pc147yls(cur, args.dry_run)
        # After dry-run, ids may be None for new products — look up existing for collection check
        if args.dry_run:
            bc_id = bc_id or product_id(cur, 'BC3901Y')
            pc_id = pc_id or product_id(cur, 'PC147YLS')
        ensure_collection_8(cur, [bc_id, pc_id], args.dry_run)
        if args.dry_run:
            conn.rollback()
            print('\n[DRY RUN] No changes committed.')
        else:
            conn.commit()
            print('\nDone. BC3901Y and PC147YLS are active for shop / group orders.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
