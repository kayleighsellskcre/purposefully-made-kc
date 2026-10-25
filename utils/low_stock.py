"""Running low: blanks, supplies and transfers at or under the reorder number set for them.

A reorder number of 0 means "do not track this one". The morning digest mentions an item the first time it runs low and
not again until it has been restocked and runs low a second time; the Monday summary lists everything still low.
"""
from __future__ import annotations

import json

from models import ApparelInventory, Supply, TransferInventory
from utils.site_settings import get_setting, set_setting

SEEN_KEY = 'low_stock_seen'
INVENTORY_PATH = '/admin/operations/inventory'


def _tracked(row):
    return int(row.reorder_threshold or 0) > 0 and int(row.quantity or 0) <= int(row.reorder_threshold or 0)


def low_items():
    """Everything at or under its reorder number, most urgent (lowest stock) first."""
    out = []
    for row in ApparelInventory.query.all():
        if _tracked(row):
            out.append({'key': f'apparel:{row.id}', 'kind': 'Blank', 'name': f'{row.brand} {row.color} {row.size}'.strip(),
                        'qty': int(row.quantity or 0), 'reorder': int(row.reorder_threshold)})
    for row in Supply.query.all():
        if _tracked(row):
            label = (row.category or 'Supply').replace('_', ' ').title()
            out.append({'key': f'supply:{row.id}', 'kind': label, 'name': row.name, 'qty': int(row.quantity or 0),
                        'reorder': int(row.reorder_threshold)})
    for row in TransferInventory.query.all():
        if _tracked(row):
            out.append({'key': f'transfer:{row.id}', 'kind': 'Transfer', 'name': f'{row.design_name} {row.size or ""}'.strip(),
                        'qty': int(row.quantity or 0), 'reorder': int(row.reorder_threshold)})
    return sorted(out, key=lambda i: (i['qty'] - i['reorder'], i['name'].lower()))


def _seen():
    try:
        return set(json.loads(get_setting(SEEN_KEY, '[]') or '[]'))
    except ValueError:
        return set()


def newly_low():
    """Low items that were not already low the last time the digest went out."""
    seen = _seen()
    return [i for i in low_items() if i['key'] not in seen]


def mark_seen():
    """Remember what is low now. Items that were restocked drop out, so running low again is news again."""
    set_setting(SEEN_KEY, json.dumps(sorted(i['key'] for i in low_items())), 'Items already reported as running low')


def line(item):
    return f"{item['name']} ({item['kind']}): {item['qty']} left, reorder at {item['reorder']}"
