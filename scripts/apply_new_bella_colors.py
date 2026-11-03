"""Add the Bella+Canvas colors listed in scripts/new_bella_colors_plan.json to the shop.

Creates one color entry per color (with its flat front/back mockups) on BC3005, BC3480 and BC8800. A color the
product already has is skipped, nothing existing is changed, and orders are never touched. Saves a backup of the
new rows so --undo can remove exactly those. Run --apply only once the image files are live on the site, then run
scripts/sync_live_inventory.py so the new colors get their stock numbers.

    python scripts/apply_new_bella_colors.py            # preview
    python scripts/apply_new_bella_colors.py --apply
    python scripts/apply_new_bella_colors.py --undo new_bella_colors_backup_<time>.json
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=True)


def key(name):
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower().replace('grey', 'gray'))


def main():
    import psycopg2
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--undo')
    args = ap.parse_args()
    url = os.environ['DATABASE_URL']
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    conn = psycopg2.connect(url, connect_timeout=30)
    cur = conn.cursor()
    if args.undo:
        ids = json.loads(Path(args.undo).read_text())
        for vid in ids:
            cur.execute('DELETE FROM product_color_variant WHERE id=%s', (vid,))
        conn.commit()
        print(f'Removed {len(ids)} color entries.')
        return
    plan = json.loads((ROOT / 'scripts' / 'new_bella_colors_plan.json').read_text(encoding='utf-8'))
    created = []
    for item in plan:
        cur.execute('SELECT id FROM product WHERE style_number=%s', (item['style'],))
        row = cur.fetchone()
        if not row:
            print('  SKIP (style not found)', item['style'])
            continue
        pid = row[0]
        cur.execute('SELECT color_name FROM product_color_variant WHERE product_id=%s', (pid,))
        if key(item['color']) in {key(r[0]) for r in cur.fetchall()}:
            print('  SKIP (already there)', item['style'], item['color'])
            continue
        if not (ROOT / item['front'].lstrip('/')).exists() or not (ROOT / item['back'].lstrip('/')).exists():
            print('  SKIP (image missing)', item['style'], item['color'])
            continue
        print(f"  {item['style']:7s} {item['color']:26s} {item['hex']}")
        if args.apply:
            cur.execute(
                'INSERT INTO product_color_variant (product_id, color_name, color_hex, color_swatch_url, '
                'front_image_url, back_image_url, size_inventory, last_synced) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                (pid, item['color'], item['hex'], item.get('swatch') or None, item['front'], item['back'],
                 '{}', datetime.utcnow()))
            created.append(cur.fetchone()[0])
    if args.apply:
        conn.commit()
        backup = ROOT / f"new_bella_colors_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
        backup.write_text(json.dumps(created), encoding='utf-8')
        print(f'Added {len(created)} colors. Backup: {backup.name} (undo with --undo {backup.name})')
    else:
        print('Preview only. Nothing saved. Add --apply to write.')


if __name__ == '__main__':
    main()
