"""Daily live inventory sync from SanMar and S&S Activewear.

Catalog jobs must not overwrite size_inventory with empty maps. This module
is the only place that writes warehouse quantities onto color variants.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from utils.json_fields import parse_json_list
from utils.stock import color_key, inventory_for_display, is_usable_inventory_payload, size_key


_PREFIXES = ('BC', 'CC', 'RS', 'ST', 'DT', 'PC', 'LPC', 'YPC', 'YST', 'LST')


def style_candidates(style_number, brand=None) -> list[str]:
    raw = str(style_number or '').strip()
    if not raw:
        return []
    seen = set()
    out = []

    def add(value):
        value = str(value or '').strip()
        if not value:
            return
        key = value.upper()
        if key in seen:
            return
        seen.add(key)
        out.append(value)

    add(raw)
    upper = raw.upper()
    for prefix in _PREFIXES:
        if upper.startswith(prefix) and len(upper) > len(prefix):
            rest = raw[len(prefix):]
            if rest[:1].isdigit() or prefix in ('BC', 'CC', 'RS', 'G'):
                add(rest)
    if upper.startswith('G') and len(raw) > 1 and raw[1:2].isdigit():
        add(raw[1:])
        # G18000 → G180 (SanMar often uses the short Gildan code)
        if raw.upper().endswith('00') and len(raw) > 3:
            add(raw[:-2])
            add(raw[1:-2])
    return out


def _row_qty(row) -> int:
    warehouses = row.get('warehouses')
    if isinstance(warehouses, list):
        total = 0
        for warehouse in warehouses:
            if isinstance(warehouse, dict):
                try:
                    total += int(float(warehouse.get('qty') or warehouse.get('quantity') or 0))
                except (TypeError, ValueError):
                    pass
            elif isinstance(warehouse, (int, float)):
                total += int(warehouse)
        if total:
            return max(0, total)
    for key in ('qty', 'inventory', 'availableQty', 'quantity'):
        value = row.get(key)
        if value in (None, ''):
            continue
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            continue
    return 0


def _merge_color_maps(*maps) -> dict:
    """Merge {color: {size: qty}} maps by color_key + size_key, summing qty."""
    merged = {}
    names = {}
    for mapping in maps:
        for color, sizes in (mapping or {}).items():
            ck = color_key(color)
            if not ck:
                continue
            names.setdefault(ck, color)
            bucket = merged.setdefault(ck, {})
            for size, qty in (sizes or {}).items():
                sk = size_key(size)
                if not sk:
                    continue
                try:
                    amount = int(float(qty or 0))
                except (TypeError, ValueError):
                    amount = 0
                bucket[sk] = bucket.get(sk, 0) + max(0, amount)
    return {names[ck]: sizes for ck, sizes in merged.items()}


def _fetch_sanmar(style_number, timeout=30) -> dict:
    from services.sanmar_api import SanMarAPI, check_credentials

    creds = check_credentials()
    if not creds.get('ok'):
        return {}
    api = SanMarAPI()
    for candidate in style_candidates(style_number):
        try:
            data = api.fetch_inventory_for_style(candidate, timeout=timeout)
        except TypeError:
            data = api.fetch_inventory_for_style(candidate)
        except Exception as exc:
            print(f'[inventory] SanMar {candidate}: {exc}', file=sys.stderr, flush=True)
            continue
        if data:
            return data
    return {}


def _fetch_ss(style_number, brand=None, ss_client=None, timeout=30) -> dict:
    api_key = os.getenv('SSACTIVEWEAR_API_KEY', '').strip()
    account = os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER', '').strip()
    if not api_key or not account:
        return {}
    try:
        from services.ssactivewear_api import SSActivewearAPI
        api = ss_client or SSActivewearAPI()
        candidates = style_candidates(style_number, brand)
        # S&S catalogs the printed number (3001), not BC3001.
        ss_candidates = list(dict.fromkeys(list(candidates[1:]) + list(candidates[:1])))
        return api.fetch_inventory_map(
            style_number,
            brand_name=brand,
            timeout=timeout,
            candidates=ss_candidates or candidates,
        )
    except Exception as exc:
        print(f'[inventory] S&S {style_number}: {exc}', file=sys.stderr, flush=True)
        return {}


def fetch_combined_inventory(product, ss_client=None, timeout=30) -> dict:
    style = getattr(product, 'style_number', '') or ''
    brand = getattr(product, 'brand', None)
    sanmar = _fetch_sanmar(style, timeout=timeout)
    ss = _fetch_ss(style, brand=brand, ss_client=ss_client, timeout=timeout)
    return _merge_color_maps(sanmar, ss)


def apply_inventory_to_product(product, warehouse_map) -> int:
    """Write warehouse qty onto every color variant. Returns variants updated."""
    from models import ProductColorVariant

    if not is_usable_inventory_payload(warehouse_map):
        return 0

    by_color = {color_key(color): sizes for color, sizes in warehouse_map.items()}
    shop_sizes = parse_json_list(product.available_sizes)
    variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
    matched = [v for v in variants if color_key(v.color_name) in by_color]
    if variants and not matched:
        print(
            f'[inventory] {product.style_number}: warehouse colors did not match shop colors — leaving existing qty',
            file=sys.stderr, flush=True,
        )
        return 0

    updated = 0
    now = datetime.utcnow()

    for variant in variants:
        sizes = by_color.get(color_key(variant.color_name))
        if sizes is None:
            # Confirmed fetch for this style, but this color was not returned → OOS.
            payload = {label: 0 for label in shop_sizes} if shop_sizes else {}
        else:
            labeled = {label: sizes.get(size_key(label), 0) for label in (shop_sizes or [])}
            if not labeled:
                labeled = dict(sizes)
            payload = inventory_for_display(labeled, shop_sizes) if shop_sizes else labeled
        variant.size_inventory = json.dumps(payload)
        variant.last_synced = now
        updated += 1
    return updated


def sync_product_inventory(product, ss_client=None, timeout=30) -> dict:
    warehouse_map = fetch_combined_inventory(product, ss_client=ss_client, timeout=timeout)
    if not is_usable_inventory_payload(warehouse_map):
        return {'style': product.style_number, 'updated': 0, 'skipped': True}
    updated = apply_inventory_to_product(product, warehouse_map)
    return {
        'style': product.style_number,
        'updated': updated,
        'skipped': False,
        'colors': len(warehouse_map),
    }


def sync_all_inventory(active_only=True, timeout=30) -> dict:
    """Fetch live qty for every shop style from SanMar and S&S, then save."""
    from models import Product, db

    query = Product.query
    if active_only:
        query = query.filter_by(is_active=True)
    products = query.order_by(Product.brand, Product.style_number).all()

    ss_client = None
    try:
        if os.getenv('SSACTIVEWEAR_API_KEY') and os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER'):
            from services.ssactivewear_api import SSActivewearAPI
            ss_client = SSActivewearAPI()
    except Exception as exc:
        print(f'[inventory] S&S client init failed: {exc}', file=sys.stderr, flush=True)

    stats = {
        'products': len(products),
        'updated_products': 0,
        'updated_variants': 0,
        'skipped': 0,
        'errors': 0,
        'started': datetime.utcnow().isoformat(),
    }
    print('=' * 80, file=sys.stderr, flush=True)
    print(f'LIVE INVENTORY SYNC — {len(products)} products', file=sys.stderr, flush=True)

    for product in products:
        try:
            result = sync_product_inventory(product, ss_client=ss_client, timeout=timeout)
            if result.get('skipped'):
                stats['skipped'] += 1
                print(f'  skip {product.style_number} (no warehouse data)', file=sys.stderr, flush=True)
                continue
            stats['updated_products'] += 1
            stats['updated_variants'] += result.get('updated', 0)
            db.session.commit()
            print(
                f'  {product.style_number}: {result.get("updated", 0)} colors, '
                f'{result.get("colors", 0)} warehouse colors',
                file=sys.stderr, flush=True,
            )
        except Exception as exc:
            db.session.rollback()
            stats['errors'] += 1
            print(f'  ERROR {product.style_number}: {exc}', file=sys.stderr, flush=True)

    stats['finished'] = datetime.utcnow().isoformat()
    print(
        f'LIVE INVENTORY SYNC COMPLETE — products={stats["updated_products"]} '
        f'variants={stats["updated_variants"]} skipped={stats["skipped"]} errors={stats["errors"]}',
        file=sys.stderr, flush=True,
    )
    print('=' * 80, file=sys.stderr, flush=True)
    return stats


def start_inventory_sync_thread(app):
    """Run sync_all_inventory in a daemon thread so HTTP requests can return."""
    import threading

    def _run():
        with app.app_context():
            try:
                sync_all_inventory()
            except Exception as exc:
                print(f'[inventory] background sync failed: {exc}', file=sys.stderr, flush=True)

    thread = threading.Thread(target=_run, daemon=True, name='inventory-sync')
    thread.start()
    return thread
