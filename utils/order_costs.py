"""Blank-shirt cost and due-date defaults for new orders."""
from datetime import datetime, timedelta


PRODUCTION_LEAD_DAYS = 14


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
    """Fill due date and blank-shirt COGS when they are still empty."""
    changed = False
    if not order.due_date:
        order.due_date = default_due_date(order.created_at)
        changed = True
    if order.cost_of_goods is None:
        cogs = shirt_cogs_for_order(order)
        if cogs is not None:
            order.cost_of_goods = cogs
            if order.total is not None:
                order.profit = round(float(order.total) - cogs, 2)
            changed = True
    return changed
