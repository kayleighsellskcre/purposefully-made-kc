"""
use_generated_tiedye_flats.py
─────────────────────────────
Point the PC146 / PC146Y Gold, Orange and Red color variants at the garment-only
flat mockups in static/images/products/<style>/ (they replaced photos with people).

Saves the old image addresses to a JSON file first so every change can be undone.
Only run --apply after the flat files are live on the site.

    py -3.12 scripts/use_generated_tiedye_flats.py            # preview
    py -3.12 scripts/use_generated_tiedye_flats.py --apply
    py -3.12 scripts/use_generated_tiedye_flats.py --undo backup.json
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

STYLES = ('PC146', 'PC146Y')
COLORS = ('Gold', 'Orange', 'Red')


def main():
    import psycopg2
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--undo')
    args = ap.parse_args()
    conn = psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=30)
    cur = conn.cursor()

    if args.undo:
        for vid, front, back in json.loads(Path(args.undo).read_text()):
            cur.execute('UPDATE product_color_variant SET front_image_url=%s, back_image_url=%s WHERE id=%s',
                        (front, back, vid))
        conn.commit()
        print('Restored the old images.')
        return

    cur.execute("""SELECT v.id, p.style_number, v.color_name, v.front_image_url, v.back_image_url
                   FROM product_color_variant v JOIN product p ON p.id = v.product_id
                   WHERE p.style_number = ANY(%s) AND v.color_name = ANY(%s) ORDER BY 2, 3""",
                (list(STYLES), list(COLORS)))
    rows = cur.fetchall()
    backup = [(vid, front, back) for vid, _s, _c, front, back in rows]
    for vid, style, color, front, back in rows:
        new_front = f'/static/images/products/{style}/{style}_{color}_front_flat.jpg'
        new_back = f'/static/images/products/{style}/{style}_{color}_back_flat.jpg'
        if not (ROOT / new_front.lstrip('/')).exists() or not (ROOT / new_back.lstrip('/')).exists():
            print('  SKIP (file missing)', style, color)
            continue
        print(f'  {style:7s} {color:7s} -> {new_front}')
        if args.apply:
            cur.execute('UPDATE product_color_variant SET front_image_url=%s, back_image_url=%s WHERE id=%s',
                        (new_front, new_back, vid))
    if args.apply:
        out = ROOT / f'tiedye_flats_backup_{datetime.now():%Y%m%d_%H%M%S}.json'
        out.write_text(json.dumps(backup))
        conn.commit()
        print('Updated. Backup of the old addresses:', out)
    else:
        conn.rollback()
        print('Preview only. Add --apply once the files are live.')


if __name__ == '__main__':
    main()
