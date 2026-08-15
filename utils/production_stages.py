"""One production-stage list for workflow, orders, and labels."""
from sqlalchemy import or_

from models import Order

STAGES = [
    ('order_received', 'Order Received', 'All new/paid orders'),
    ('waiting_supplies', 'Waiting on Supplies', 'Awaiting blanks or transfers'),
    ('ready_to_press', 'Ready to Press', 'Supplies in, ready to heat'),
    ('pressed', 'Pressed', 'Print applied'),
    ('packaged_ready', 'Packaged & Ready', 'Ready for pickup/ship'),
]

STAGE_LABELS = {sid: name for sid, name, _desc in STAGES}

# production_stage → (order.status, production_stage)
STAGE_MAP = {
    'order_received': ('new', 'order_received'),
    'waiting_supplies': ('new', 'waiting_supplies'),
    'ready_to_press': ('in_production', 'ready_to_press'),
    'pressed': ('in_production', 'pressed'),
    'packaged_ready': ('ready', 'packaged_ready'),
}

OPEN_STATUSES = ('new', 'paid', 'in_production', 'ready')
DONE_STATUSES = ('completed', 'shipped', 'picked_up', 'cancelled')


def apply_stage(order, stage):
    if stage not in STAGE_MAP:
        return False
    order.status, order.production_stage = STAGE_MAP[stage]
    return True


def orders_for_stage(stage_id):
    query = Order.query
    if stage_id == 'order_received':
        return query.filter(
            Order.status.in_(['new', 'paid']),
            or_(
                Order.production_stage == None,
                Order.production_stage == '',
                Order.production_stage == 'order_received',
            ),
        )
    if stage_id == 'packaged_ready':
        return query.filter(
            or_(Order.status == 'ready', Order.production_stage == 'packaged_ready')
        ).filter(~Order.status.in_(DONE_STATUSES))
    if stage_id in STAGE_LABELS:
        return query.filter(
            Order.status.in_(OPEN_STATUSES),
            Order.production_stage == stage_id,
        )
    return query.filter(Order.status.in_(OPEN_STATUSES))


def normalize_stage_arg(value):
    """Map old status filters onto production stages."""
    if not value:
        return 'order_received'
    aliases = {
        'new': 'order_received',
        'paid': 'order_received',
        'in_production': 'ready_to_press',
        'ready': 'packaged_ready',
        'all': 'all',
    }
    return aliases.get(value, value if value in STAGE_LABELS or value == 'all' else 'order_received')
