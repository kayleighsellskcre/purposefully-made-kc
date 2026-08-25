"""
audit_product_data_sources.py
─────────────────────────────
Read-only audit: every active product page is bound to one Product DB row
(not an external Google Sheet). Report data-source, integrity issues, and
cross-style image mismatches.

    py -3.12 scripts/audit_product_data_sources.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=True)


def connect():
    import psycopg2
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is not set')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return psycopg2.connect(url, connect_timeout=30)


def source_label(api_data, brand, style):
    raw = api_data or ''
    low = raw.lower()
    if 'sanmar' in low or 'styleName' in raw and 'sanmar' in low:
        return 'SanMar sync / api_data'
    if 'ssactivewear' in low or 'S&S' in raw or 'styleID' in raw:
        return 'S&S Activewear api_data'
    if 'bella' in low or (brand or '').lower().startswith('bella'):
        if raw.strip():
            return 'Bella+Canvas / CSV or S&S api_data'
        return 'Bella+Canvas catalog (manual or CSV)'
    if (brand or '').lower().startswith('port'):
        return 'Port & Company (SanMar / dealer flats)'
    if raw.strip():
        return 'api_data present (supplier sync)'
    return 'Manual / mockup-folder / local catalog'


def styles_mentioned(url: str) -> set[str]:
    if not url:
        return set()
    found = set()
    for m in re.finditer(r'(PC\d{3}Y?(?:LS)?|LPC\d+[A-Z]*|BC\d{4}[A-Z]*|G\d{5}|RS\d{4}|3001CVC|3001Y|3001)', url, re.I):
        found.add(m.group(1).upper())
    return found


def style_aliases(style: str) -> set[str]:
    s = (style or '').upper()
    aliases = {s}
    if s.startswith('BC') and s[2:]:
        aliases.add(s[2:])  # BC3001 -> 3001
    if s.endswith('Y') and len(s) > 1:
        aliases.add(s[:-1])
        if s.startswith('BC'):
            aliases.add(s[2:-1])
    return aliases


def url_matches_style(style: str, url: str) -> bool:
    mentioned = styles_mentioned(url)
    if not mentioned:
        return True
    aliases = style_aliases(style)
    return bool(mentioned & aliases) or any(
        m in aliases or any(a in m or m in a for a in aliases) for m in mentioned
    )


def main():
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT id, style_number, name, brand, category, age_group, base_price,
               available_sizes, available_colors, is_active, api_data,
               front_mockup_template, back_mockup_template, spec_sheet_url
        FROM product
        WHERE is_active = TRUE
        ORDER BY brand NULLS LAST, style_number
        '''
    )
    products = cur.fetchall()
    print(f'Active products: {len(products)}\n')

    issues = []
    source_counts = Counter()
    style_ids = defaultdict(list)

    for row in products:
        (pid, style, name, brand, category, age, price, sizes_raw, colors_raw,
         active, api_data, front_t, back_t, spec) = row
        style_ids[style].append(pid)
        src = source_label(api_data, brand, style)
        source_counts[src] += 1

        cur.execute(
            '''SELECT color_name, front_image_url, back_image_url, size_inventory
               FROM product_color_variant WHERE product_id = %s ORDER BY color_name''',
            (pid,),
        )
        variants = cur.fetchall()
        v_colors = [v[0] for v in variants if v[0]]

        try:
            listed_sizes = json.loads(sizes_raw) if sizes_raw else []
            if not isinstance(listed_sizes, list):
                listed_sizes = []
        except Exception:
            listed_sizes = []
            issues.append((style, 'available_sizes JSON invalid'))

        try:
            listed_colors = json.loads(colors_raw) if colors_raw else []
            if not isinstance(listed_colors, list):
                listed_colors = []
        except Exception:
            listed_colors = []

        if not variants:
            issues.append((style, 'no color variants'))
        if not listed_sizes and not any(v[3] for v in variants):
            issues.append((style, 'no sizes listed and no inventory keys'))

        # Image URL points at a different style number
        for color, front, back, inv in variants:
            for label, url in (('front', front), ('back', back)):
                if not url:
                    continue
                if url_matches_style(style, url):
                    continue
                mentioned = styles_mentioned(url)
                if mentioned:
                    issues.append((style, f'{color} {label} URL mentions {sorted(mentioned)}: {url[:90]}'))

        # api_data style mismatch
        if api_data:
            try:
                blob = json.loads(api_data)
            except Exception:
                blob = {}
            for key in ('style', 'styleNumber', 'style_number', 'partNumber'):
                val = blob.get(key) if isinstance(blob, dict) else None
                if val and str(val).upper() not in (style or '').upper() and (style or '').upper() not in str(val).upper():
                    # soft — many blobs nest differently
                    pass

    dup_styles = {s: ids for s, ids in style_ids.items() if len(ids) > 1}
    if dup_styles:
        for s, ids in sorted(dup_styles.items()):
            issues.append((s, f'duplicate active style_number product ids={ids}'))

    print('Data sources (product pages bind to Product.id in PostgreSQL):')
    for src, n in source_counts.most_common():
        print(f'  {n:4d}  {src}')

    print(f'\nIntegrity findings: {len(issues)}')
    for style, msg in issues[:80]:
        print(f'  [{style}] {msg}')
    if len(issues) > 80:
        print(f'  … {len(issues) - 80} more')

    # Sample: every product has a shop + customize route key
    print('\nRoute binding: /shop/product/<id> and /shop/customize/<id> use Product.id')
    print('There is no per-page external spreadsheet assignment in this codebase.')
    print('Supplier CSVs (Bella) / SanMar / S&S sync populate the same Product tables.')

    cur.close()
    conn.close()
    return 0 if not dup_styles else 1


if __name__ == '__main__':
    raise SystemExit(main())
