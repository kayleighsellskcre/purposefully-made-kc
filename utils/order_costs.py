"""Blank-shirt cost, DTF transfer pricing, and due-date defaults for orders."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

PRODUCTION_LEAD_DAYS = 14

# Server-side only — never under static/ or a public route.
_COSTS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'costs.json'

DEFAULT_DTF_COSTS = {
    'dtf_per_sq_in': 0.05,
    'dtf_gang_sheet_per_foot': 11.50,
    'dtf_vendor': 'JiffyShirts.com',
    'dtf_notes': '',
}


def costs_file_path():
    return _COSTS_PATH


def get_dtf_costs():
    """Read DTF transfer pricing from data/costs.json (creates defaults if missing)."""
    path = costs_file_path()
    data = dict(DEFAULT_DTF_COSTS)
    if path.is_file():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                data.update({k: loaded[k] for k in DEFAULT_DTF_COSTS if k in loaded})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    else:
        save_dtf_costs(data)
    # Normalize types for callers
    try:
        data['dtf_per_sq_in'] = float(data.get('dtf_per_sq_in', DEFAULT_DTF_COSTS['dtf_per_sq_in']))
    except (TypeError, ValueError):
        data['dtf_per_sq_in'] = DEFAULT_DTF_COSTS['dtf_per_sq_in']
    try:
        data['dtf_gang_sheet_per_foot'] = float(
            data.get('dtf_gang_sheet_per_foot', DEFAULT_DTF_COSTS['dtf_gang_sheet_per_foot'])
        )
    except (TypeError, ValueError):
        data['dtf_gang_sheet_per_foot'] = DEFAULT_DTF_COSTS['dtf_gang_sheet_per_foot']
    data['dtf_vendor'] = str(data.get('dtf_vendor') or DEFAULT_DTF_COSTS['dtf_vendor'])
    data['dtf_notes'] = str(data.get('dtf_notes') or '')
    return data


def save_dtf_costs(payload):
    """Write DTF transfer pricing to data/costs.json. Creates data/ if needed."""
    path = costs_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = dict(DEFAULT_DTF_COSTS)
    if isinstance(payload, dict):
        current.update({k: payload[k] for k in DEFAULT_DTF_COSTS if k in payload})
    try:
        current['dtf_per_sq_in'] = round(float(current['dtf_per_sq_in']), 4)
    except (TypeError, ValueError):
        current['dtf_per_sq_in'] = DEFAULT_DTF_COSTS['dtf_per_sq_in']
    try:
        current['dtf_gang_sheet_per_foot'] = round(float(current['dtf_gang_sheet_per_foot']), 2)
    except (TypeError, ValueError):
        current['dtf_gang_sheet_per_foot'] = DEFAULT_DTF_COSTS['dtf_gang_sheet_per_foot']
    current['dtf_vendor'] = str(current.get('dtf_vendor') or DEFAULT_DTF_COSTS['dtf_vendor']).strip()
    current['dtf_notes'] = str(current.get('dtf_notes') or '').strip()
    tmp = path.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(current, f, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(tmp, path)
    return current


def default_due_date(placed_at=None):
    start = placed_at or datetime.utcnow()
    return start + timedelta(days=PRODUCTION_LEAD_DAYS)


def shirt_unit_cost(product):
    """Distributor / warehouse cost for one blank garment."""
    if not product:
        return None
    cost = getattr(product, 'wholesale_cost', None)
    if cost is None:
        return None
    try:
        number = float(cost)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number, 2)


def shirt_cogs_for_order(order):
    """Sum of blank-shirt costs. Transfer costs are added later by admin."""
    total = 0.0
    found = False
    items = order.items.all() if hasattr(order.items, 'all') else list(order.items or [])
    for item in items:
        unit = shirt_unit_cost(getattr(item, 'product', None))
        if unit is None:
            continue
        qty = getattr(item, 'quantity', None) or 1
        total += unit * qty
        found = True
    return round(total, 2) if found else None


def apply_order_defaults(order):
    """Fill due date and COGS (blank wholesale + DTF) when they are still empty."""
    changed = False
    if not order.due_date:
        order.due_date = default_due_date(order.created_at)
        changed = True
    if order.cost_of_goods is None:
        # Prefer full blank + DTF; fall back to blank-only if breakdown is empty.
        breakdown = order_cost_breakdown(order)
        cogs = breakdown.get('total_cogs')
        if cogs is None or (cogs == 0 and shirt_cogs_for_order(order) is None):
            cogs = shirt_cogs_for_order(order)
        if cogs is not None:
            order.cost_of_goods = round(float(cogs), 2)
            if order.total is not None:
                order.profit = round(float(order.total) - order.cost_of_goods, 2)
            changed = True
    return changed


def _safe_float(value, default=None):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _print_area_sq_in(item, production=None):
    """Square inches for DTF from stored dims, else production front/back."""
    w = _safe_float(getattr(item, 'print_width', None))
    h = _safe_float(getattr(item, 'print_height', None))
    if w and h and w > 0 and h > 0:
        return round(w * h, 4)

    area = 0.0
    prod = production or {}
    front = prod.get('front') if isinstance(prod, dict) else getattr(prod, 'front', None)
    if isinstance(front, dict):
        fw = _safe_float(front.get('width') or front.get('width_in'))
        fh = _safe_float(front.get('height') or front.get('height_in'))
        if fw and fh and fw > 0 and fh > 0:
            area += fw * fh
    back = prod.get('back') if isinstance(prod, dict) else getattr(prod, 'back', None)
    if isinstance(back, dict):
        # Prefer combined back layout when present (name+number sheet)
        bw = _safe_float(back.get('combined_width') or back.get('width'))
        bh = _safe_float(back.get('combined_height') or back.get('height'))
        if bw and bh and bw > 0 and bh > 0:
            area += bw * bh
    return round(area, 4) if area > 0 else 0.0


def margin_band(margin_pct):
    """Return css band key for profit margin coloring."""
    if margin_pct is None:
        return 'unknown'
    if margin_pct > 40:
        return 'good'
    if margin_pct >= 20:
        return 'ok'
    return 'low'


def item_cost_breakdown(item, dtf_rate=None, production=None):
    """Per-line blank + DTF cost vs what the customer paid."""
    if dtf_rate is None:
        dtf_rate = get_dtf_costs().get('dtf_per_sq_in', DEFAULT_DTF_COSTS['dtf_per_sq_in'])
    dtf_rate = _safe_float(dtf_rate, DEFAULT_DTF_COSTS['dtf_per_sq_in']) or 0.0

    qty = int(getattr(item, 'quantity', None) or 1)
    if qty < 1:
        qty = 1

    blank_unit = shirt_unit_cost(getattr(item, 'product', None))
    blank_unit = blank_unit if blank_unit is not None else 0.0
    blank_cost = round(blank_unit * qty, 2)

    sq_in = _print_area_sq_in(item, production=production)
    dtf_unit = round(sq_in * dtf_rate, 4) if sq_in else 0.0
    dtf_cost = round(dtf_unit * qty, 2)

    item_cost = round(blank_cost + dtf_cost, 2)

    customer_paid = _safe_float(getattr(item, 'subtotal', None))
    if customer_paid is None:
        unit = _safe_float(getattr(item, 'unit_price', None), 0.0) or 0.0
        customer_paid = round(unit * qty, 2)
    else:
        customer_paid = round(customer_paid, 2)

    profit = round(customer_paid - item_cost, 2)
    margin_pct = None
    if customer_paid > 0:
        margin_pct = round((profit / customer_paid) * 100.0, 1)

    return {
        'item_id': getattr(item, 'id', None),
        'quantity': qty,
        'blank_unit': blank_unit,
        'blank_cost': blank_cost,
        'print_sq_in': sq_in,
        'dtf_rate': dtf_rate,
        'dtf_cost': dtf_cost,
        'item_cost': item_cost,
        'customer_paid': customer_paid,
        'profit': profit,
        'margin_pct': margin_pct,
        'margin_band': margin_band(margin_pct),
        'missing_blank': shirt_unit_cost(getattr(item, 'product', None)) is None,
        'missing_print_size': sq_in <= 0,
    }


def order_cost_breakdown(order, item_productions=None):
    """Full order cost breakdown + totals for admin order detail."""
    dtf_rate = get_dtf_costs().get('dtf_per_sq_in', DEFAULT_DTF_COSTS['dtf_per_sq_in'])
    prod_by_id = {}
    if item_productions:
        for row in item_productions:
            item = row[0] if isinstance(row, (list, tuple)) else row
            prod = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else None
            if getattr(item, 'id', None) is not None:
                prod_by_id[item.id] = prod

    items = order.items.all() if hasattr(order.items, 'all') else list(order.items or [])
    lines = []
    total_cogs = 0.0
    total_paid = 0.0
    for item in items:
        line = item_cost_breakdown(
            item,
            dtf_rate=dtf_rate,
            production=prod_by_id.get(getattr(item, 'id', None)),
        )
        lines.append(line)
        total_cogs += line['item_cost']
        total_paid += line['customer_paid']

    total_cogs = round(total_cogs, 2)
    # Prefer order.total (includes shipping/tax) for "customer paid" at order level
    order_paid = _safe_float(getattr(order, 'total', None))
    if order_paid is None:
        order_paid = round(total_paid, 2)
    else:
        order_paid = round(order_paid, 2)
    total_profit = round(order_paid - total_cogs, 2)
    overall_margin = None
    if order_paid > 0:
        overall_margin = round((total_profit / order_paid) * 100.0, 1)

    return {
        'lines': lines,
        'lines_by_item_id': {line['item_id']: line for line in lines if line['item_id'] is not None},
        'total_cogs': total_cogs,
        'total_customer_paid': order_paid,
        'total_items_paid': round(total_paid, 2),
        'total_profit': total_profit,
        'overall_margin_pct': overall_margin,
        'overall_margin_band': margin_band(overall_margin),
        'dtf_rate': dtf_rate,
    }


def apply_calculated_cogs(order, breakdown=None):
    """Persist calculated COGS + profit onto the order row. Returns True if changed."""
    if breakdown is None:
        breakdown = order_cost_breakdown(order)
    cogs = breakdown['total_cogs']
    # Profit vs order total (what customer paid for the whole order)
    paid = breakdown['total_customer_paid']
    profit = round(paid - cogs, 2)
    changed = False
    if order.cost_of_goods != cogs:
        order.cost_of_goods = cogs
        changed = True
    if order.profit != profit:
        order.profit = profit
        changed = True
    return changed