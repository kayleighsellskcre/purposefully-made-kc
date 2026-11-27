"""
fill_size_charts.py
───────────────────
Saves each product's own size chart (chest width laid flat, body length, sleeve) from the manufacturer's measurements
published through the S&S Activewear API, so every style shows its own correct numbers instead of one general chart.

    python scripts/fill_size_charts.py --dry-run     # shows what would be saved, changes nothing
    python scripts/fill_size_charts.py               # saves the charts

Styles S&S does not carry (Port & Company, Sport-Tek, District, Stanley/Stella and a few more) are listed at the end:
those need numbers from SanMar's spec sheets. A product that already has a chart is left alone unless --force.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))
os.environ['SCHEDULER_ENABLED'] = '0'

PREFIXES = ('bc', 'cc', 'g', 'ind', 'pc', 'rs', 'st', 'dt')
BRAND_ALIASES = {
    'bellacanvas': ['bellacanvas', 'bella'], 'portcompany': ['portcompany'], 'independenttradingco': ['independenttradingco', 'independenttrading'],
    'district': ['district'], 'sporttek': ['sporttek'], 'rabbitskins': ['rabbitskins'], 'c2sport': ['c2sport'], 'mvsport': ['mvsport'],
    'stanleystella': ['stanleystella'], 'gildan': ['gildan'], 'comfortcolors': ['comfortcolors'],
}


def _norm(text):
    return re.sub(r'[^a-z0-9]', '', str(text or '').lower())


def _number(raw):
    """'26 3/5' -> 26.6, '28 1/2' -> 28.5, '20' -> 20.0; None when it is not a measurement."""
    raw = str(raw or '').strip().replace('"', '')
    m = re.fullmatch(r'(\d+)(?:\s+(\d+)/(\d+))?', raw)
    if m:
        whole, num, den = m.groups()
        return int(whole) + (int(num) / int(den) if num and den and int(den) else 0.0)
    m = re.fullmatch(r'(\d+)/(\d+)', raw)
    if m and int(m.group(2)):
        return int(m.group(1)) / int(m.group(2))
    try:
        return float(raw)
    except ValueError:
        return None


def _show(value):
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def build_chart(specs):
    """{size: {'chest': '20', 'length': '28', 'sleeve': '8.5'}} in size order, from the manufacturer's spec rows."""
    from utils.sizes import sort_sizes
    by_size = {}
    for row in specs or []:
        name = (row.get('specName') or '').lower()
        size = row.get('sizeName')
        value = _number(row.get('value'))
        if not size or value is None or 'tolerance' in name:
            continue
        if name.startswith('chest width'):
            key = 'chest'
        elif name == 'body length' or name == 'body length front':
            key = 'length'
        elif name.startswith('sleeve length'):
            key = 'sleeve'
        else:
            continue
        by_size.setdefault(size, {}).setdefault(key, _show(value))
    ordered = {}
    for size in sort_sizes(list(by_size.keys())):
        entry = by_size[size]
        if entry.get('chest') and entry.get('length'):
            ordered[size] = entry
    return ordered


def _odd(chart):
    """A reason this chart cannot be right, or ''. A bigger size should never be narrower or shorter than the one before it."""
    previous = None
    for size, row in chart.items():
        chest, length = float(row['chest']), float(row['length'])
        if previous and (chest < previous[1] - 0.01 or length < previous[2] - 0.01):
            return f'{size} is smaller than {previous[0]}'
        previous = (size, chest, length)
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='replace a chart a product already has')
    args = ap.parse_args()

    import requests
    from app import create_app
    from models import Product, db
    from services.ssactivewear_api import SSActivewearAPI

    api = SSActivewearAPI()
    catalog = api.get_styles('all')
    bybrand = {}
    for s in catalog:
        bybrand.setdefault(_norm(s.get('brandName')), {}).setdefault(_norm(s.get('styleName')), []).append(s)

    app = create_app()
    with app.app_context():
        saved, skipped, missing = 0, 0, []
        for product in Product.query.order_by(Product.brand, Product.style_number).all():
            brand = _norm(product.brand)
            keys = [k for k in bybrand if any(k.startswith(a) or a.startswith(k) for a in BRAND_ALIASES.get(brand, [brand]))]
            style = _norm(product.style_number)
            candidates = [style] + [style[len(p):] for p in PREFIXES if style.startswith(p) and p != style]
            found = next((bybrand[k][c][0] for k in keys for c in candidates if c in bybrand[k]), None)
            if found is None:
                missing.append(product.style_number)
                continue
            if product.size_chart and not args.force:
                skipped += 1
                continue
            resp = requests.get(f"{api.api_url}/v2/specs/?style={found['styleID']}", auth=(api.account_number, api.api_key), timeout=40)
            chart = build_chart(resp.json() if resp.ok else [])
            if len(chart) < 3:
                missing.append(product.style_number)
                continue
            problem = _odd(chart)
            if problem:
                print(f'CHECK      {product.style_number:10s} not saved: {problem}')
                missing.append(f'{product.style_number} (looks wrong at S&S: {problem})')
                continue
            first = next(iter(chart))
            last = list(chart)[-1]
            print(f"{'would save' if args.dry_run else 'saved':10s} {product.style_number:10s} {len(chart)} sizes: {first} chest {chart[first]['chest']} x {chart[first]['length']}  ...  {last} chest {chart[last]['chest']} x {chart[last]['length']}")
            if not args.dry_run:
                product.size_chart = json.dumps(chart)
            saved += 1
        if not args.dry_run:
            db.session.commit()
        print(f"\n{saved} charts {'would be ' if args.dry_run else ''}saved, {skipped} already had one.")
        print(f"Not available from S&S ({len(missing)}): {', '.join(missing)}")


if __name__ == '__main__':
    main()
