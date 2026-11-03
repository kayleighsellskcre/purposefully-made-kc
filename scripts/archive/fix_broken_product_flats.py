"""
fix_broken_product_flats.py
────────────────────────────
1) PC147YLS / PC147LS: replace short-sleeve PC147_* flats with true PC147LS flats
   (BigTop dealer) when available; otherwise clear so picture-day shows.
2) Bella styles with broken /static/sanmar/front/SDL/... paths: replace with
   S&S garment flats, or copy from a duplicate color that already has Widen/CDN.
3) Collapse duplicate colors (Athletic Heather vs athleticheather).

    py -3.12 scripts/fix_broken_product_flats.py --dry-run
    py -3.12 scripts/fix_broken_product_flats.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

BELLA_STYLES = ['BC3739', 'BC8800', 'BC3480', 'BC6400CVC', 'BC3005', 'BC3005CVC']
TIEDYE_LS = ['PC147LS', 'PC147YLS']
CDN = 'https://cdn.ssactivewear.com/'
SHOP = 'https://www.bigtopshirtshop.com'
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    )
}
PLACEHOLDER = '/static/img/placeholder-product.svg'


def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())


def connect():
    import psycopg2
    return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=30)


def abs_cdn(path: str | None) -> str | None:
    if not path:
        return None
    path = str(path).strip()
    if not path:
        return None
    if path.startswith('http'):
        return path
    return CDN + path.lstrip('/')


def is_broken_url(url: str | None) -> bool:
    if not url:
        return True
    u = url.strip()
    if not u or u == PLACEHOLDER:
        return True
    if '/static/sanmar/front/SDL/' in u:
        return True
    if u.startswith('/static/') and not (ROOT / u.lstrip('/').replace('/', os.sep)).exists():
        # relative static path that isn't on disk
        return True
    return False


def is_short_sleeve_pc147(url: str | None) -> bool:
    """True when URL is adult short-sleeve PC147 flat (not LS / Y / YLS)."""
    if not url:
        return False
    name = url.split('/')[-1].lower()
    if 'pc147yls' in name or 'pc147ls' in name or 'pc147y_' in name or 'pc147y-' in name:
        return False
    return bool(re.search(r'(^|[_-])pc147[_-]', name)) and 'pc147ls' not in name


def score_url(url: str | None) -> int:
    if not url or is_broken_url(url):
        return 0
    u = url.lower()
    if 'widencdn' in u and 'flat' in u:
        return 5
    if 'shopify' in u and 'flat' in u:
        return 4
    if 'ssactivewear' in u and 'modelcolor' not in u:
        return 3
    if u.startswith('http'):
        return 2
    return 1


def display_color_name(a: str, b: str) -> str:
    """Prefer Title Case / spaced names over jammed lowercase."""
    def rank(s):
        spaces = s.count(' ')
        lower_jam = 1 if s.islower() and ' ' not in s else 0
        return (spaces, -lower_jam, -len(s))
    return a if rank(a) >= rank(b) else b


# ── BigTop PC147LS flats ──────────────────────────────────────────────────────

def _get(url, timeout=40):
    import requests
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def search_pc147ls_handles():
    found = []
    for page in range(1, 6):
        url = f'{SHOP}/search?q={quote("PC147LS")}&type=product'
        if page > 1:
            url += f'&page={page}'
        html = _get(url).text
        page_handles = re.findall(r'/products/(port-company-[a-z0-9-]+)', html, flags=re.I)
        if not page_handles:
            break
        found.extend(page_handles)
    out = []
    for h in sorted(set(found)):
        hl = h.lower()
        if 'pc147yls' in hl:
            continue
        if '-pc147ls-' in hl or hl.endswith('-pc147ls'):
            out.append(h)
    return out


def color_from_title(title: str) -> str:
    t = (title or '').strip()
    if ' - ' in t:
        t = t.rsplit(' - ', 1)[-1]
    t = re.sub(r'\bPC147LS\b', '', t, flags=re.I).strip(' -')
    t = t.replace('Turquoise Blue', 'Turquoise').replace('Royal Blue', 'Royal')
    return t


def flats_from_handle(handle: str):
    data = _get(f'{SHOP}/products/{handle}.json').json()
    product = data.get('product') or {}
    color = color_from_title(product.get('title') or '')
    front = back = None
    for img in product.get('images') or []:
        src = (img.get('src') or '').strip().split('?')[0]
        alt = (img.get('alt') or '').lower()
        name = src.lower()
        if not src:
            continue
        if 'model' in alt or '_model_' in name:
            continue
        blob = alt + ' ' + name
        if 'flat_front' in name or 'flat front' in alt:
            front = src
        elif 'flat_back' in name or 'flat back' in alt:
            back = src
        elif 'flat' in blob and 'front' in blob and not front:
            front = src
        elif 'flat' in blob and 'back' in blob and not back:
            back = src
    return color, front, back


def load_pc147ls_flat_map() -> dict[str, dict]:
    print('  Scraping BigTop for PC147LS flats...')
    handles = search_pc147ls_handles()
    print(f'  found {len(handles)} PC147LS dealer pages')
    out = {}
    aliases = {
        'kellygreen': 'kelly',
        'royalblue': 'royal',
        'turquoiseblue': 'turquoise',
    }
    for handle in handles:
        try:
            color, front, back = flats_from_handle(handle)
        except Exception as e:
            print(f'    skip {handle}: {e}')
            continue
        if not front and not back:
            continue
        key = norm(color)
        if not key:
            continue
        key = aliases.get(key, key)
        display = {
            'kelly': 'Kelly',
            'royal': 'Royal',
            'turquoise': 'Turquoise',
        }.get(key, color)
        if key not in out:
            out[key] = {'name': display, 'front': front, 'back': back}
            print(f'    + {display}: front={bool(front)} back={bool(back)}')
        else:
            if front and not out[key]['front']:
                out[key]['front'] = front
            if back and not out[key]['back']:
                out[key]['back'] = back
    return out


def fix_tiedye_ls(cur, flat_map: dict[str, dict], dry_run: bool):
    print('\n=== Fix PC147LS / PC147YLS short-sleeve mis-images ===')
    for style in TIEDYE_LS:
        cur.execute(
            'SELECT id, front_mockup_template, back_mockup_template '
            'FROM product WHERE upper(style_number)=upper(%s)',
            (style,),
        )
        row = cur.fetchone()
        if not row:
            print(f'  MISS {style}')
            continue
        pid = row[0]
        cur.execute(
            'SELECT id, color_name, front_image_url, back_image_url '
            'FROM product_color_variant WHERE product_id=%s',
            (pid,),
        )
        variants = cur.fetchall()
        first_front = first_back = None
        fixed = cleared = ok = 0
        for vid, color, front, back in variants:
            key = norm(color)
            donor = flat_map.get(key)
            needs = is_short_sleeve_pc147(front) or is_short_sleeve_pc147(back) or is_broken_url(front)
            if donor and (donor.get('front') or donor.get('back')):
                nf = donor.get('front') or front
                nb = donor.get('back') or back
                # Prefer LS donor whenever we have one for this color
                if nf != front or nb != back or needs:
                    print(f'  {style} {color}: set PC147LS flats')
                    fixed += 1
                    if not dry_run:
                        cur.execute(
                            'UPDATE product_color_variant SET front_image_url=%s, '
                            'back_image_url=%s, last_synced=%s WHERE id=%s',
                            (nf, nb, datetime.utcnow(), vid),
                        )
                    front, back = nf, nb
                else:
                    ok += 1
            elif needs:
                print(f'  {style} {color}: no LS flat — clear to picture-day')
                cleared += 1
                if not dry_run:
                    cur.execute(
                        'UPDATE product_color_variant SET front_image_url=NULL, '
                        'back_image_url=NULL, last_synced=%s WHERE id=%s',
                        (datetime.utcnow(), vid),
                    )
                front = back = None
            else:
                ok += 1
            if front and not first_front:
                first_front = front
            if back and not first_back:
                first_back = back
        if not dry_run and (first_front or first_back):
            cur.execute(
                'UPDATE product SET '
                'front_mockup_template=COALESCE(%s, front_mockup_template), '
                'back_mockup_template=COALESCE(%s, back_mockup_template), '
                'updated_at=NOW() WHERE id=%s',
                (first_front, first_back, pid),
            )
        print(f'  {style}: fixed={fixed} cleared={cleared} ok={ok}')


# ── S&S + Bella broken SDL ────────────────────────────────────────────────────

def ss_client():
    import requests
    acct = os.environ['SSACTIVEWEAR_ACCOUNT_NUMBER']
    key = os.environ['SSACTIVEWEAR_API_KEY']
    return requests.Session(), (acct, key)


def fetch_ss_colors(sess, auth, style_id: int) -> dict[str, dict]:
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
        front = abs_cdn(p.get('ghostFrontImage') or p.get('colorFrontImage'))
        back = abs_cdn(p.get('ghostBackImage') or p.get('colorBackImage'))
        if front and 'ModelColor' in front:
            front = abs_cdn(p.get('ghostFrontImage'))
        if back and 'ModelColor' in back:
            back = abs_cdn(p.get('ghostBackImage'))
        if front and 'ModelColor' in (front or ''):
            front = None
        if back and 'ModelColor' in (back or ''):
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


def resolve_style_id(sess, auth, style_number: str, catalog: list) -> int | None:
    candidates = {style_number, style_number.upper()}
    bare = re.sub(r'^[A-Za-z+&]+', '', style_number)
    if bare:
        candidates.add(bare)
        candidates.add(bare.upper())
    matches = []
    for s in catalog:
        sn = (s.get('styleName') or s.get('styleNumber') or '').strip()
        if sn.upper() not in {c.upper() for c in candidates}:
            continue
        bn = (s.get('brandName') or '').lower()
        score = 2 if 'bella' in bn else 0
        matches.append((score, s.get('styleID')))
    matches.sort(reverse=True)
    return matches[0][1] if matches else None


def fix_bella(cur, dry_run: bool):
    print('\n=== Fix Bella broken SDL / missing flats ===')
    sess, auth = ss_client()
    catalog = sess.get('https://api.ssactivewear.com/v2/styles/', auth=auth, timeout=120).json()
    if not isinstance(catalog, list):
        raise SystemExit('S&S styles catalog failed')

    for style in BELLA_STYLES:
        cur.execute(
            'SELECT id FROM product WHERE upper(style_number)=upper(%s)',
            (style,),
        )
        row = cur.fetchone()
        if not row:
            print(f'  MISS {style}')
            continue
        pid = row[0]
        sid = resolve_style_id(sess, auth, style, catalog)
        ss_colors = fetch_ss_colors(sess, auth, sid) if sid else {}
        print(f'  {style}: S&S styleID={sid} colors={len(ss_colors)}')

        cur.execute(
            'SELECT id, color_name, front_image_url, back_image_url '
            'FROM product_color_variant WHERE product_id=%s ORDER BY id',
            (pid,),
        )
        variants = cur.fetchall()

        # Group by normalized color
        groups: dict[str, list] = {}
        for v in variants:
            groups.setdefault(norm(v[1]), []).append(v)

        updated = deleted = 0
        first_front = first_back = None
        keep_names = []

        for key, rows in groups.items():
            # Pick best URLs across the group
            best_front = best_back = None
            best_name = rows[0][1]
            for _vid, cname, front, back in rows:
                best_name = display_color_name(best_name, cname)
                if score_url(front) > score_url(best_front):
                    best_front = front
                if score_url(back) > score_url(best_back):
                    best_back = back

            ss = ss_colors.get(key)
            if ss:
                if score_url(ss.get('front')) > score_url(best_front):
                    best_front = ss['front']
                if score_url(ss.get('back')) > score_url(best_back):
                    best_back = ss['back']
                best_name = display_color_name(best_name, ss['name'])

            if is_broken_url(best_front):
                best_front = None
            if is_broken_url(best_back):
                best_back = None

            # Keep lowest id as survivor; delete the rest
            rows_sorted = sorted(rows, key=lambda r: r[0])
            keep_id = rows_sorted[0][0]
            drop_ids = [r[0] for r in rows_sorted[1:]]

            before = next(r for r in rows if r[0] == keep_id)
            changed = (
                before[1] != best_name
                or (before[2] or None) != best_front
                or (before[3] or None) != best_back
            )
            if changed or drop_ids:
                status = 'FLAT' if best_front else 'PICTURE-DAY'
                print(f'    {best_name}: {status}'
                      + (f' (merge {len(drop_ids)} dupes)' if drop_ids else '')
                      + (f' was={ (before[2] or "")[:50]}' if is_broken_url(before[2]) else ''))
            if not dry_run:
                cur.execute(
                    'UPDATE product_color_variant SET color_name=%s, '
                    'front_image_url=%s, back_image_url=%s, last_synced=%s '
                    'WHERE id=%s',
                    (best_name, best_front, best_back, datetime.utcnow(), keep_id),
                )
                updated += 1
                for did in drop_ids:
                    cur.execute('DELETE FROM product_color_variant WHERE id=%s', (did,))
                    deleted += 1

            keep_names.append(best_name)
            if best_front and not first_front:
                first_front = best_front
            if best_back and not first_back:
                first_back = best_back

        # Also add any S&S colors we don't have at all? User asked to fix images
        # for existing styles — don't explode the color list with new S&S-only colors.

        if not dry_run:
            cur.execute(
                'UPDATE product SET available_colors=%s, '
                'front_mockup_template=COALESCE(%s, front_mockup_template), '
                'back_mockup_template=COALESCE(%s, back_mockup_template), '
                'updated_at=NOW() WHERE id=%s',
                (json.dumps(sorted(keep_names)), first_front, first_back, pid),
            )
        print(f'  {style}: updated={updated} deleted_dupes={deleted}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Fixing broken / wrong product flats...\n")

    flat_map = load_pc147ls_flat_map()
    conn = connect()
    try:
        cur = conn.cursor()
        fix_tiedye_ls(cur, flat_map, args.dry_run)
        fix_bella(cur, args.dry_run)
        if args.dry_run:
            conn.rollback()
            print('\n[DRY RUN] No changes committed.')
        else:
            conn.commit()
            print('\nDone. DB updated.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
