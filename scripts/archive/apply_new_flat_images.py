"""
apply_new_flat_images.py
────────────────────────
Point color variants at the flat garment-only mockups in static/images/products/
listed in scripts/new_flat_images_plan.json. Each entry is
[variant_id, style, color, "front" or "back", "/static/..."].

Fills ONLY the side that was empty, never replaces an image that is already there.
Saves a backup of every address it changes. Run --apply only once the files are live.

    py -3.12 scripts/apply_new_flat_images.py            # preview
    py -3.12 scripts/apply_new_flat_images.py --apply
    py -3.12 scripts/apply_new_flat_images.py --undo backup.json
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
from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=True)


def main():
    import psycopg2
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--undo')
    args = ap.parse_args()
    conn = psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=30)
    cur = conn.cursor()
    if args.undo:
        for vid, col, old in json.loads(Path(args.undo).read_text()):
            cur.execute(f'UPDATE product_color_variant SET {col}=%s WHERE id=%s', (old, vid))
        conn.commit()
        print('Restored.')
        return
    plan = json.loads((ROOT / 'scripts' / 'new_flat_images_plan.json').read_text())
    backup = []
    for vid, style, color, side, url in plan:
        col = 'front_image_url' if side == 'front' else 'back_image_url'
        if not (ROOT / url.lstrip('/')).exists():
            print('  SKIP (file missing)', style, color, side)
            continue
        cur.execute(f'SELECT {col} FROM product_color_variant WHERE id=%s', (vid,))
        row = cur.fetchone()
        if row is None or (row[0] or '').strip():
            print('  SKIP (already has an image)', style, color, side)
            continue
        print(f'  {style:9s} {color:20s} {side:5s} -> {url}')
        backup.append((vid, col, row[0]))
        if args.apply:
            cur.execute(f'UPDATE product_color_variant SET {col}=%s WHERE id=%s', (url, vid))
    if args.apply:
        out = ROOT / f'new_flat_images_backup_{datetime.now():%Y%m%d_%H%M%S}.json'
        out.write_text(json.dumps(backup))
        conn.commit()
        print('Updated. Backup:', out)
    else:
        conn.rollback()
        print('Preview only. Add --apply once the files are live.')


if __name__ == '__main__':
    main()
