"""Each product's own size chart (chest width laid flat, body length) from the manufacturer's measurements published
through the S&S Activewear API. Used by the Products page button and by scripts/fill_size_charts.py.

A product that already has a chart is left alone unless force is set. Styles S&S does not carry (Port & Company,
Sport-Tek, District and a few more) come back in `missing`: those need numbers from SanMar's spec sheets.
"""
from __future__ import annotations

import json
import re

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


def fill_size_charts(dry_run=False, force=False, say=None):
    """Run inside an app context. Returns {'saved': n, 'skipped': n, 'missing': [...], 'checked': [...]}."""
    import requests
    from models import Product, db
    from services.ssactivewear_api import SSActivewearAPI

    say = say or (lambda line: None)
    api = SSActivewearAPI()
    bybrand = {}
    for s in api.get_styles('all'):
        bybrand.setdefault(_norm(s.get('brandName')), {}).setdefault(_norm(s.get('styleName')), []).append(s)

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
        if product.size_chart and not force:
            skipped += 1
            continue
        resp = requests.get(f"{api.api_url}/v2/specs/?style={found['styleID']}", auth=(api.account_number, api.api_key), timeout=40)
        chart = build_chart(resp.json() if resp.ok else [])
        if len(chart) < 3:
            missing.append(product.style_number)
            continue
        problem = _odd(chart)
        if problem:
            say(f'CHECK      {product.style_number:10s} not saved: {problem}')
            missing.append(f'{product.style_number} (looks wrong at S&S: {problem})')
            continue
        first = next(iter(chart))
        last = list(chart)[-1]
        say(f"{'would save' if dry_run else 'saved':10s} {product.style_number:10s} {len(chart)} sizes: {first} chest {chart[first]['chest']} x {chart[first]['length']}  ...  {last} chest {chart[last]['chest']} x {chart[last]['length']}")
        if not dry_run:
            product.size_chart = json.dumps(chart)
        saved += 1
    if not dry_run:
        db.session.commit()
    return {'saved': saved, 'skipped': skipped, 'missing': missing}


def start_fill_thread(app, force=False):
    """Run it in the background so the page does not wait. The result lands in the admin inbox when it is done."""
    import threading

    def work():
        with app.app_context():
            try:
                r = fill_size_charts(force=force)
                text = f"{r['saved']} size charts saved, {r['skipped']} already had one."
                if r['missing']:
                    text += f" {len(r['missing'])} styles need numbers from the SanMar spec sheets: " + ', '.join(r['missing'][:40])
                title = 'Size charts filled in'
            except Exception as exc:
                from models import db
                db.session.rollback()
                app.logger.exception('size chart fill failed')
                title, text = 'Size charts could not be filled in', f'Nothing was lost. The supplier connection said: {exc}'
            try:
                from utils.admin_notifications import create_notification
                create_notification(kind='system', title=title, preview=text[:200], body=text, from_name='Site', from_email='',
                                    url='/admin/products')
            except Exception:
                app.logger.exception('size chart notification failed')

    threading.Thread(target=work, daemon=True).start()
