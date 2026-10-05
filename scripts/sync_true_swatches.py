"""
sync_true_swatches.py
─────────────────────
Make color dots match the real garment.

1. Download SanMar's official fabric swatch GIFs into
   static/sanmar/front/SDL/COLOR_SQUARE_IMAGE/ (the path the catalog already
   stores in color_swatch_url, which was never uploaded).
2. Fill color_hex on active variants that have none, from the swatch image or
   the manufacturer's flat photo of that shirt. Supplier hex codes are never
   overwritten.

    python scripts/sync_true_swatches.py --dry-run   # downloads swatches, previews hex
    python scripts/sync_true_swatches.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

import requests  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from utils.swatches import (  # noqa: E402
    SANMAR_SWATCH_CDN,
    SANMAR_SWATCH_PREFIX,
    local_static_path,
    true_color_hex,
)


def _engine():
    url = os.environ['DATABASE_URL']
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return create_engine(url)


def download_swatches(conn):
    names = [
        row[0][len(SANMAR_SWATCH_PREFIX):]
        for row in conn.execute(text(
            "SELECT DISTINCT color_swatch_url FROM product_color_variant "
            "WHERE color_swatch_url LIKE :prefix"
        ), {'prefix': SANMAR_SWATCH_PREFIX + '%'})
    ]
    fetched = missing = 0
    for name in names:
        if not name or '/' in name or '\\' in name:
            continue
        dest = local_static_path(SANMAR_SWATCH_PREFIX + name)
        if os.path.isfile(dest):
            continue
        resp = requests.get(SANMAR_SWATCH_CDN + name, timeout=20)
        if resp.status_code != 200 or not resp.headers.get('Content-Type', '').startswith('image/'):
            missing += 1
            print(f'  not on SanMar CDN: {name}')
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as fh:
            fh.write(resp.content)
        fetched += 1
    print(f'Swatch images: {len(names)} referenced, {fetched} downloaded, {missing} unavailable')


def fill_hex(conn, dry_run):
    rows = conn.execute(text(
        "SELECT v.id, v.color_swatch_url, v.front_image_url, v.color_name, p.style_number "
        "FROM product_color_variant v JOIN product p ON p.id = v.product_id "
        "WHERE p.is_active AND (v.color_hex IS NULL OR v.color_hex = '')"
    )).fetchall()
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        sampled = list(pool.map(lambda r: true_color_hex(r[1], r[2]), rows))
    filled = 0
    for (vid, swatch, front, color, style), hex_value in zip(rows, sampled):
        if not hex_value:
            continue
        filled += 1
        if dry_run:
            if filled <= 15:
                print(f'  {style} {color}: {hex_value}')
            continue
        conn.execute(
            text("UPDATE product_color_variant SET color_hex = :hex WHERE id = :id "
                 "AND (color_hex IS NULL OR color_hex = '')"),
            {'hex': hex_value, 'id': vid},
        )
    print(f'Color hex: {filled} of {len(rows)} missing colors sampled from real images')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    engine = _engine()
    with engine.connect() as conn:
        download_swatches(conn)
        fill_hex(conn, args.dry_run)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()


if __name__ == '__main__':
    main()
