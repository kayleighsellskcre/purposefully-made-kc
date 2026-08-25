"""
fix_pc146_flat_images.py
─────────────────────────
1. Remove orphan Solid/Deep Heather files under static/images/products/PC146Y
   (they were leaking into the shop carousel as fake colors).
2. Replace PC146 / PC146Y apparel4print (often on-model) photos with garment-only
   flat front/back images from BigTopShirtShop.
3. When youth flats have no back, copy the matching adult PC146 flat back.

    py -3.12 scripts/fix_pc146_flat_images.py --dry-run
    py -3.12 scripts/fix_pc146_flat_images.py
"""
from __future__ import annotations

import argparse
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

ORPHAN_DIR = ROOT / 'static' / 'images' / 'products' / 'PC146Y'
ORPHAN_PREFIXES = (
    'PC146Y_Solid_',
    'PC146Y_deepheather',
    'PC146Y_Deep_Heather',
)


def connect():
    import psycopg2
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is not set')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return psycopg2.connect(url, connect_timeout=30)


def delete_orphans(dry_run: bool) -> int:
    if not ORPHAN_DIR.is_dir():
        print('  OK    no PC146Y local folder')
        return 0
    removed = 0
    for path in sorted(ORPHAN_DIR.iterdir()):
        if not path.is_file():
            continue
        if any(path.name.startswith(p) for p in ORPHAN_PREFIXES):
            print(f'  DEL   {path.relative_to(ROOT)}')
            removed += 1
            if not dry_run:
                path.unlink()
    leftover = [p.name for p in ORPHAN_DIR.iterdir() if p.is_file()] if ORPHAN_DIR.is_dir() else []
    if leftover:
        print(f'  KEEP  remaining in PC146Y/: {leftover}')
    elif removed:
        print('  OK    PC146Y orphan mockups removed')
    return removed


def load_flats(styles, dry_run: bool):
    """Apply BigTop flat URLs for the given styles via existing helpers."""
    import scripts.load_tiedye_flats as flats

    conn = connect()
    cur = conn.cursor()
    updated = 0
    try:
        for style in styles:
            cur.execute(
                'SELECT id FROM product WHERE style_number = %s',
                (style,),
            )
            row = cur.fetchone()
            if not row:
                print(f'  MISS  {style}')
                continue
            pid = row[0]
            cur.execute(
                'SELECT id, color_name, front_image_url, back_image_url '
                'FROM product_color_variant WHERE product_id = %s ORDER BY color_name',
                (pid,),
            )
            variants = cur.fetchall()
            existing = [v[1] for v in variants]
            by_color = {v[1]: v for v in variants}
            try:
                handles = flats.search_handles(style, style)
            except Exception as e:
                print(f'  ERR   {style} search: {e}')
                continue
            print(f'  {style:8s}  {len(handles)} dealer pages, {len(existing)} catalog colors')
            matched = set()
            first_front = first_back = None
            for handle in handles:
                try:
                    color, front, back = flats.flats_from_product(handle)
                except Exception as e:
                    print(f'         skip {handle}: {e}')
                    continue
                if not front and not back:
                    continue
                target = flats.match_existing(color, existing)
                if not target or target in matched:
                    continue
                vid, _, old_f, old_b = by_color[target]
                print(f'         {target}: flat front={bool(front)} back={bool(back)}')
                matched.add(target)
                if dry_run:
                    continue
                if front:
                    cur.execute(
                        'UPDATE product_color_variant SET front_image_url = %s, last_synced = %s WHERE id = %s',
                        (front[:500], datetime.utcnow(), vid),
                    )
                    first_front = first_front or front
                    updated += 1
                if back:
                    cur.execute(
                        'UPDATE product_color_variant SET back_image_url = %s, last_synced = %s WHERE id = %s',
                        (back[:500], datetime.utcnow(), vid),
                    )
                    first_back = first_back or back
            still = [c for c in existing if c not in matched]
            if still:
                print(f'         still no BigTop flat: {still}')
            if not dry_run and first_front:
                cur.execute(
                    'UPDATE product SET front_mockup_template = %s, updated_at = %s WHERE id = %s',
                    (first_front[:500], datetime.utcnow(), pid),
                )
            if not dry_run and first_back:
                cur.execute(
                    'UPDATE product SET back_mockup_template = %s, updated_at = %s WHERE id = %s',
                    (first_back[:500], datetime.utcnow(), pid),
                )

        # Youth backs: copy adult PC146 flat backs for matching color names
        cur.execute("SELECT id FROM product WHERE style_number = 'PC146'")
        adult = cur.fetchone()
        cur.execute("SELECT id FROM product WHERE style_number = 'PC146Y'")
        youth = cur.fetchone()
        if adult and youth:
            cur.execute(
                'SELECT color_name, back_image_url FROM product_color_variant '
                'WHERE product_id = %s AND back_image_url ILIKE %s',
                (adult[0], '%flat%'),
            )
            adult_backs = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute(
                'SELECT id, color_name, back_image_url FROM product_color_variant WHERE product_id = %s',
                (youth[0],),
            )
            for vid, color, back in cur.fetchall():
                donor = adult_backs.get(color)
                if not donor:
                    continue
                if back and 'flat' in (back or '').lower():
                    continue
                print(f'  COPY  PC146Y {color} back ← PC146 flat back')
                if not dry_run:
                    cur.execute(
                        'UPDATE product_color_variant SET back_image_url = %s, last_synced = %s WHERE id = %s',
                        (donor[:500], datetime.utcnow(), vid),
                    )
                    updated += 1

        if dry_run:
            conn.rollback()
            print('\n[DRY RUN] No DB changes.')
        else:
            conn.commit()
            print(f'\nDone. variant image updates≈{updated}')
    finally:
        cur.close()
        conn.close()
    return updated


def main():
    parser = argparse.ArgumentParser(description='PC146/PC146Y flat images + orphan cleanup')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Fixing PC146 / PC146Y images...\n")
    print('Orphan local files:')
    delete_orphans(args.dry_run)
    print('\nFlat catalog images:')
    load_flats(['PC146', 'PC146Y'], args.dry_run)


if __name__ == '__main__':
    main()
