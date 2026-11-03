"""Which garment colors and sizes a supplier carries right now.

The supplier is the only source of truth, for the EXACT style number: SanMar styles are read from the SanMar
API, S&S styles from the S&S API. Colors are never borrowed from a related style. A color is hidden when the
supplier does not list it, or lists it with zero stock in every size and warehouse. If the supplier returns
nothing at all for a style (outage, unknown style) nothing is hidden: a failed lookup must never empty a store.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from utils.json_fields import parse_json_list
from utils.stock import color_key, size_key

SYNC_OK_KEY = 'stock_sync_last_ok'          # inventory refresh finished
COLOR_OK_KEY = 'color_check_last_ok'        # color/size check finished


def fetch_supplier_stock(product, ss_client=None, timeout=30):
    """Return (supplier, {color: {size: qty}}) from SanMar, else S&S; (None, {}) when neither answered."""
    from services.inventory_sync import _fetch_sanmar, _fetch_ss

    style = getattr(product, 'style_number', '') or ''
    brand = getattr(product, 'brand', None)
    for supplier, fetch in (
        ('SanMar', lambda: _fetch_sanmar(style, timeout=timeout)),
        ('S&S', lambda: _fetch_ss(style, brand=brand, ss_client=ss_client, timeout=timeout)),
    ):
        data = fetch()
        if data:
            return supplier, data
    return None, {}


def _qty(value):
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def fetch_supplier_colors(product, ss_client=None, timeout=30):
    """Return (supplier, {color_key: total_qty}) or (None, {})."""
    supplier, data = fetch_supplier_stock(product, ss_client=ss_client, timeout=timeout)
    totals = {}
    for color, sizes in (data or {}).items():
        key = color_key(color)
        if key:
            totals[key] = totals.get(key, 0) + sum(_qty(v) for v in (sizes or {}).values())
    return (supplier, totals) if totals else (None, {})


def shop_color_names(product, variants=None):
    """Every color name the shop could show for this product."""
    if variants is None:
        variants = list(getattr(product, 'color_variants', []) or [])
    names = [v.color_name for v in variants if v.color_name]
    for name in parse_json_list(getattr(product, 'available_colors', None)):
        if name and name not in names:
            names.append(name)
    return names


def unavailable_colors(product, ss_client=None, timeout=30, variants=None):
    """Return dict(supplier, checked, hidden=[(name, reason)]). Never writes anything."""
    supplier, totals = fetch_supplier_colors(product, ss_client=ss_client, timeout=timeout)
    names = shop_color_names(product, variants)
    result = {'supplier': supplier, 'checked': len(names), 'hidden': []}
    if not supplier:
        return result
    for name in names:
        key = color_key(name)
        if key not in totals:
            result['hidden'].append((name, 'not carried'))
        elif totals[key] <= 0:
            result['hidden'].append((name, 'out of stock'))
    return result


def sold_out_sizes(product, stock_map, hidden_keys):
    """{color: [sizes with zero stock]} for colors that stay shown, using the shop's size list when there is one."""
    shop_sizes = parse_json_list(getattr(product, 'available_sizes', None))
    out = {}
    for color, sizes in (stock_map or {}).items():
        if color_key(color) in hidden_keys:
            continue
        have = {size_key(s): _qty(q) for s, q in (sizes or {}).items()}
        labels = shop_sizes or list(sizes or {})
        zero = [label for label in labels if have.get(size_key(label), 0) <= 0]
        if zero:
            out[color] = zero
    return out


def _record(key, note):
    try:
        from utils.site_settings import set_setting
        set_setting(key, datetime.utcnow().isoformat(timespec='seconds'), note)
    except Exception as exc:
        print(f'[colors] could not record {key}: {exc}', file=sys.stderr, flush=True)


def run_color_check(ss_client=None, timeout=30, commit=True, notify=True):
    """Check every active style against its supplier, store what to hide, email what changed.

    Returns {'checked', 'unchecked', 'newly_hidden', 'restored', 'sizes_out', 'sizes_back'} where the last four
    map style -> list of text. A style whose supplier gave no answer keeps whatever it had before. A style that
    would lose ALL of its colors is treated as "no answer" too: that looks like a bad lookup, not a real change.
    """
    from models import Product, db

    if ss_client is None and os.getenv('SSACTIVEWEAR_API_KEY') and os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER'):
        try:
            from services.ssactivewear_api import SSActivewearAPI
            ss_client = SSActivewearAPI()
        except Exception as exc:
            print(f'[colors] S&S client init failed: {exc}', file=sys.stderr, flush=True)

    summary = {'checked': 0, 'unchecked': [], 'newly_hidden': {}, 'restored': {}, 'sizes_out': {}, 'sizes_back': {}}
    for product in Product.query.filter_by(is_active=True).order_by(Product.style_number).all():
        try:
            supplier, data = fetch_supplier_stock(product, ss_client=ss_client, timeout=timeout)
            totals = {}
            for color, sizes in (data or {}).items():
                key = color_key(color)
                if key:
                    totals[key] = totals.get(key, 0) + sum(_qty(v) for v in (sizes or {}).values())
            names = shop_color_names(product)
            hidden = []
            if supplier and totals:
                hidden = [n for n in names if totals.get(color_key(n), 0) <= 0]
        except Exception as exc:
            print(f'[colors] {product.style_number}: {exc}', file=sys.stderr, flush=True)
            summary['unchecked'].append(product.style_number)
            continue
        if not supplier or not totals or (names and len(hidden) >= len(names)):
            summary['unchecked'].append(product.style_number)
            continue
        summary['checked'] += 1
        old = {color_key(n): n for n in parse_json_list(product.supplier_hidden_colors)}
        new = {color_key(n): n for n in hidden}
        fresh = [new[k] for k in new if k not in old]
        back = [old[k] for k in old if k not in new]
        if fresh:
            summary['newly_hidden'][product.style_number] = fresh
        if back:
            summary['restored'][product.style_number] = back
        product.supplier_hidden_colors = json.dumps(sorted(new.values(), key=str.lower))

        out_now = sold_out_sizes(product, data, set(new))
        try:
            out_before = json.loads(product.supplier_sold_out_sizes or '{}')
        except ValueError:
            out_before = {}
        before = {(color_key(c), size_key(s)): (c, s) for c, sizes in out_before.items() for s in sizes}
        after = {(color_key(c), size_key(s)): (c, s) for c, sizes in out_now.items() for s in sizes}
        went = [f'{after[k][0]} {after[k][1]}' for k in after if k not in before]
        came = [f'{before[k][0]} {before[k][1]}' for k in before if k not in after]
        if went:
            summary['sizes_out'][product.style_number] = went
        if came:
            summary['sizes_back'][product.style_number] = came
        product.supplier_sold_out_sizes = json.dumps(out_now)
    if commit:
        db.session.commit()
        _record(COLOR_OK_KEY, 'Last time the supplier color and size check finished')
    if notify and color_summary_sections(summary):
        send_color_summary(summary)
    return summary


def _lines(mapping):
    return [f"{style}: {', '.join(names)}" for style, names in sorted(mapping.items())]


def color_summary_sections(summary):
    spec = [
        ('newly_hidden', 'colors_hidden', 'Colors hidden from the shop', 'warn'),
        ('restored', 'colors_back', 'Colors back in the shop', 'good'),
        ('sizes_out', 'sizes_out', 'Sizes sold out (hidden)', 'warn'),
        ('sizes_back', 'sizes_back', 'Sizes back in stock', 'good'),
    ]
    sections = []
    for field, key, title, tone in spec:
        mapping = summary.get(field) or {}
        if mapping:
            sections.append({'key': key, 'title': title, 'count': sum(len(v) for v in mapping.values()), 'tone': tone,
                             'link': '/admin/products', 'link_label': 'Open products', 'lines': _lines(mapping)})
    return sections


def _deliver_sections(subject, heading, intro, sections):
    from flask import current_app
    from utils.daily_digest import _deliver
    from utils.mailer import admin_base_url
    return _deliver(subject, heading, intro, sections, admin_base_url(current_app))


def send_color_summary(summary):
    """The morning email: colors and sizes that were hidden or came back. True if sent."""
    sections = color_summary_sections(summary)
    if not sections:
        return False
    hidden = sum(s['count'] for s in sections if s['key'] == 'colors_hidden')
    parts = []
    if hidden:
        parts.append(f'{hidden} color{"s" if hidden != 1 else ""} hidden')
    if any(s['key'] == 'sizes_out' for s in sections):
        parts.append('sizes sold out')
    if not parts:
        parts.append('stock is back')
    intro = ('This is what changed overnight, straight from SanMar and S&S. A hidden color or size shows again by '
             'itself when the supplier has it in stock. Existing orders are not affected.')
    return _deliver_sections('Shop stock update: ' + ', '.join(parts), 'Shop stock changed', intro, sections)


def send_sync_problem(what):
    """Email the owner that the morning stock sync failed or did not run."""
    section = {'key': 'sync_problem', 'title': 'Stock sync problem', 'count': 1, 'tone': 'warn',
               'link': '/admin/products', 'link_label': 'Open products', 'lines': [what]}
    return _deliver_sections('Stock sync problem: check the shop',
                             'The morning stock sync needs a look',
                             'Colors and stock on the shop may be out of date until it runs again.', [section])


def _checked_today(key, now=None):
    """True when the setting `key` holds a time within the last 20 hours."""
    from utils.site_settings import get_setting
    raw = get_setting(key, '')
    try:
        then = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return False
    return (( now or datetime.utcnow()) - then).total_seconds() < 20 * 3600


def watchdog(now=None):
    """6 AM check: email if the stock sync or the color check did not finish overnight. Returns problems found."""
    problems = []
    if not _checked_today(SYNC_OK_KEY, now):
        problems.append('The overnight stock refresh did not finish (no successful run in the last 20 hours).')
    if not _checked_today(COLOR_OK_KEY, now):
        problems.append('The overnight color and size check did not finish (no successful run in the last 20 hours).')
    if problems:
        send_sync_problem(' '.join(problems))
    return problems


def live_cart_stock_error(cart, timeout=8):
    """One last look at the supplier before a customer pays. Returns an error message, or None when fine.

    Only blocks on a clear answer: if the supplier is slow or returns nothing, the morning numbers stand.
    """
    from models import Product
    from utils.stock import aggregate_cart_blanks

    grouped, labels = aggregate_cart_blanks(cart)
    cache = {}
    for (product_id, ckey, skey), qty in grouped.items():
        product = Product.query.get(product_id)
        if not product:
            continue
        if product_id not in cache:
            try:
                cache[product_id] = fetch_supplier_stock(product, timeout=timeout)
            except Exception:
                cache[product_id] = (None, {})
        supplier, data = cache[product_id]
        if not supplier or not data:
            continue
        color, size = labels[(product_id, ckey, skey)]
        have = None
        for name, sizes in data.items():
            if color_key(name) == ckey:
                have = sum(_qty(q) for s, q in sizes.items() if size_key(s) == skey)
                break
        if have is None:
            continue  # the supplier names this color differently: never block a sale on a name mismatch
        wanted = sum(q for (pid, ck, sk), q in grouped.items() if pid == product_id and ck == ckey and sk == skey)
        if have < wanted:
            if have <= 0:
                return f'Sorry, {product.name} in {color}, size {size}, just sold out. Please pick another size or color.'
            return f'Only {have} of {product.name} in {color}, size {size}, are left. Please lower the quantity.'
    return None
