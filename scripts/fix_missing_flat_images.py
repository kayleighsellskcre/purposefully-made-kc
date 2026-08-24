"""
fix_missing_flat_images.py
──────────────────────────
Fill missing front/back color variant images with garment-only flats
(S&S colorFrontImage / colorBackImage — never ModelColor).

Also seeds PC146Y color variants from PC144 when empty.

    py -3.12 scripts/fix_missing_flat_images.py --dry-run
    py -3.12 scripts/fix_missing_flat_images.py
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
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

CDN = 'https://cdn.ssactivewear.com/'
YOUTH_SIZES = json.dumps(["XS", "S", "M", "L", "XL"])
YOUTH_INV = json.dumps({s: 0 for s in ["XS", "S", "M", "L", "XL"]})

# style_number → preferred S&S styleID (disambiguates duplicate style names)
STYLE_ID_HINTS = {
    '5100': 2281,   # C2 Sport
    '5200': 2485,   # C2 Sport Youth
    '5600': 2731,   # C2 Sport Women's
    '17116': 7466,  # MV Sport
    '496': 12262,   # MV Sport
    'G64500': 2116, # Gildan Softstyle V-Neck (64V00)
    'RS3401': 2577, # Rabbit Skins 4424 infant bodysuit
}


def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())


def abs_cdn(path: str | None) -> str | None:
    if not path:
        return None
    path = str(path).strip()
    if not path:
        return None
    if path.startswith('http'):
        return path
    return CDN + path.lstrip('/')


def connect():
    import psycopg2
    return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=30)


def ss_client():
    import requests
    acct = os.environ['SSACTIVEWEAR_ACCOUNT_NUMBER']
    key = os.environ['SSACTIVEWEAR_API_KEY']
    return requests.Session(), (acct, key)


def fetch_ss_colors(sess, auth, style_id: int) -> dict[str, dict]:
    """color_norm → {name, front, back} using Color flats only (not ModelColor)."""
    r = sess.get(
        'https://api.ssactivewear.com/v2/products/',
        params={'styleid': style_id},
        auth=auth,
        timeout=90,
    )
    r.raise_for_status()
    data = r.json()
    out = {}
    if not isinstance(data, list):
        return out
    for p in data:
        name = (p.get('colorName') or '').strip()
        if not name:
            continue
        front = abs_cdn(p.get('colorFrontImage') or p.get('ghostFrontImage'))
        back = abs_cdn(p.get('colorBackImage') or p.get('ghostBackImage'))
        # Refuse on-model paths even if a field is mislabeled
        if front and 'ModelColor' in front:
            front = None
        if back and 'ModelColor' in back:
            back = None
        key = norm(name)
        if key not in out:
            out[key] = {'name': name, 'front': front, 'back': back}
        else:
            if front and not out[key]['front']:
                out[key]['front'] = front
            if back and not out[key]['back']:
                out[key]['back'] = back
    return out


def resolve_style_id(sess, auth, style_number: str, brand: str | None, catalog: list) -> int | None:
    if style_number in STYLE_ID_HINTS:
        return STYLE_ID_HINTS[style_number]
    candidates = {style_number, style_number.upper(), style_number.lower()}
    bare = re.sub(r'^[A-Za-z+&]+', '', style_number)
    if bare:
        candidates.add(bare)
        candidates.add(bare.upper())
    brand_l = (brand or '').lower()
    matches = []
    for s in catalog:
        sn = (s.get('styleName') or s.get('styleNumber') or '').strip()
        if sn not in candidates and sn.upper() not in {c.upper() for c in candidates}:
            continue
        bn = (s.get('brandName') or '').lower()
        score = 0
        if brand_l and brand_l in bn:
            score += 2
        if 'bella' in brand_l and 'bella' in bn:
            score += 2
        matches.append((score, s.get('styleID')))
    matches.sort(reverse=True)
    return matches[0][1] if matches else None


def seed_pc146y(cur, dry_run: bool):
    cur.execute("SELECT id FROM product WHERE style_number = 'PC146Y'")
    row = cur.fetchone()
    if not row:
        print('  SKIP  PC146Y not in catalog')
        return
    pid = row[0]
    cur.execute('SELECT COUNT(*) FROM product_color_variant WHERE product_id = %s', (pid,))
    if cur.fetchone()[0] > 0:
        print('  OK    PC146Y already has variants')
        return
    cur.execute("SELECT id FROM product WHERE style_number = 'PC144'")
    donor = cur.fetchone()
    if not donor:
        print('  SKIP  PC146Y: no PC144 donor')
        return
    cur.execute(
        'SELECT color_name, color_hex, color_swatch_url, front_image_url, back_image_url '
        'FROM product_color_variant WHERE product_id = %s',
        (donor[0],),
    )
    rows = cur.fetchall()
    print(f'  ADD   PC146Y variants from PC144 ({len(rows)} colors)')
    if dry_run:
        return
    color_names = []
    first_f = first_b = None
    for color_name, hex_, swatch, front, back in rows:
        color_names.append(color_name)
        if front and not first_f:
            first_f = front
        if back and not first_b:
            first_b = back
        cur.execute(
            'INSERT INTO product_color_variant '
            '(product_id, color_name, color_hex, color_swatch_url, '
            ' front_image_url, back_image_url, size_inventory) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (pid, color_name, hex_, swatch, front, back, YOUTH_INV),
        )
    cur.execute(
        'UPDATE product SET available_sizes = %s, available_colors = %s, '
        'front_mockup_template = COALESCE(%s, front_mockup_template), '
        'back_mockup_template = COALESCE(%s, back_mockup_template), '
        'is_active = TRUE, updated_at = NOW() WHERE id = %s',
        (YOUTH_SIZES, json.dumps(color_names), first_f, first_b, pid),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Fix missing flat front/back images...\n")
    sess, auth = ss_client()
    print('Loading S&S styles catalog...')
    catalog = sess.get('https://api.ssactivewear.com/v2/styles/', auth=auth, timeout=120).json()
    if not isinstance(catalog, list):
        raise SystemExit('S&S styles catalog failed')

    conn = connect()
    cur = conn.cursor()
    try:
        seed_pc146y(cur, args.dry_run)

        cur.execute("""
            SELECT p.id, p.style_number, p.brand, v.id, v.color_name,
                   v.front_image_url, v.back_image_url
            FROM product p
            JOIN product_color_variant v ON v.product_id = p.id
            WHERE p.is_active = TRUE
              AND (
                v.front_image_url IS NULL OR btrim(v.front_image_url) = ''
                OR v.back_image_url IS NULL OR btrim(v.back_image_url) = ''
              )
            ORDER BY p.style_number, v.color_name
        """)
        rows = cur.fetchall()
        print(f'Missing side(s) on {len(rows)} variant row(s)\n')

        by_product: dict[int, list] = {}
        meta = {}
        for pid, style, brand, vid, color, front, back in rows:
            by_product.setdefault(pid, []).append((vid, color, front, back))
            meta[pid] = (style, brand)

        updated = 0
        for pid, variants in by_product.items():
            style, brand = meta[pid]
            style_id = resolve_style_id(sess, auth, style, brand, catalog)
            if not style_id:
                print(f'  SKIP  {style}: no S&S styleID')
                continue
            try:
                colors = fetch_ss_colors(sess, auth, style_id)
            except Exception as e:
                print(f'  ERR   {style} styleID={style_id}: {e}')
                continue
            print(f'  {style:12s} S&S#{style_id}  {len(colors)} colors available')
            for vid, color, front, back in variants:
                match = colors.get(norm(color))
                if not match:
                    # fuzzy contains
                    for k, val in colors.items():
                        if norm(color) in k or k in norm(color):
                            match = val
                            break
                if not match:
                    print(f'    miss  {color}: no S&S color match')
                    continue
                new_f = front if (front or '').strip() else match.get('front')
                new_b = back if (back or '').strip() else match.get('back')
                if new_f == front and new_b == back:
                    continue
                print(f'    fix   {color}: front={"keep" if front else "set"} back={"keep" if back else "set"}')
                updated += 1
                if not args.dry_run:
                    cur.execute(
                        'UPDATE product_color_variant SET '
                        'front_image_url = COALESCE(NULLIF(btrim(front_image_url), \'\'), %s), '
                        'back_image_url = COALESCE(NULLIF(btrim(back_image_url), \'\'), %s) '
                        'WHERE id = %s',
                        (new_f, new_b, vid),
                    )

        if args.dry_run:
            conn.rollback()
            print(f'\n[DRY RUN] would update {updated} variants')
        else:
            conn.commit()
            print(f'\nDone. Updated {updated} variants with flat Color images.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
