"""Shared Daily Operations floor: one sequence, filters carried page to page."""
from flask import request, url_for
from urllib.parse import urlencode

from utils.production_stages import STAGE_LABELS, normalize_stage_arg, orders_for_stages

DAILY_ENDPOINTS = {
    'admin.orders',
    'admin.completed_orders',
    'admin.order_detail',
    'admin.production_workflow',
    'admin.production_master',
    'admin.transfer_production',
    'admin.order_transfer_summary',
    'admin.print_labels',
    'admin.dtf_batch_sheets',
    'admin.production_bulk_sheet',
    'admin.blank_apparel_list',
    'admin.custom_design_requests',
    'admin.custom_design_request_detail',
    'admin.production',
}

FLOW_STEPS = [
    {
        'id': 'orders',
        'num': '1',
        'label': 'Orders',
        'hint': 'See what came in',
        'endpoint': 'admin.orders',
        'active_eps': ('admin.orders', 'admin.order_detail', 'admin.completed_orders'),
        'params': {'stage': ['order_received']},
    },
    {
        'id': 'workflow',
        'num': '2',
        'label': 'Workflow',
        'hint': 'Move each order forward',
        'endpoint': 'admin.production_workflow',
        'active_eps': ('admin.production_workflow',),
        'params': {},
    },
    {
        'id': 'blanks',
        'num': '3',
        'label': 'Order blanks',
        'hint': 'Buy shirts before you press',
        'endpoint': 'admin.production_master',
        'active_eps': ('admin.production_master', 'admin.blank_apparel_list', 'admin.production'),
        'params': {'stage': ['order_received', 'waiting_supplies']},
    },
    {
        'id': 'press',
        'num': '4',
        'label': 'Press',
        'hint': 'Press sheets and DTF',
        'endpoint': 'admin.transfer_production',
        'active_eps': ('admin.transfer_production', 'admin.order_transfer_summary', 'admin.dtf_batch_sheets', 'admin.production_bulk_sheet'),
        'params': {'stage': ['ready_to_press', 'pressed']},
    },
    {
        'id': 'pack',
        'num': '5',
        'label': 'Pack & labels',
        'hint': 'Print labels and send home',
        'endpoint': 'admin.print_labels',
        'active_eps': ('admin.print_labels',),
        'params': {'stage': ['pressed', 'packaged_ready']},
    },
]

STAGE_TOOLS = {
    'order_received': [
        ('admin.orders', 'Open orders', {'stage': ['order_received']}),
        ('admin.production_master', 'Order blanks', {'stage': ['order_received', 'waiting_supplies']}),
    ],
    'waiting_supplies': [
        ('admin.production_master', 'Blank + design list', {'stage': ['waiting_supplies']}),
        ('admin.blank_apparel_list', 'Purchase list', {'stage': ['waiting_supplies']}),
    ],
    'ready_to_press': [
        ('admin.transfer_production', 'Press sheets', {'stage': ['ready_to_press']}),
        ('admin.dtf_batch_sheets', 'DTF batches', {'stage': ['ready_to_press']}),
    ],
    'pressed': [
        ('admin.print_labels', 'Print labels', {'stage': ['pressed']}),
        ('admin.transfer_production', 'Press sheets', {'stage': ['pressed']}),
    ],
    'packaged_ready': [
        ('admin.print_labels', 'Print labels', {'stage': ['packaged_ready']}),
        ('admin.orders', 'Ready orders', {'stage': ['packaged_ready']}),
    ],
}


def current_collection():
    return (request.args.get('collection') or '').strip()


def ops_url(endpoint, **extra):
    """Build an operations URL and keep the current group-order filter."""
    collection = extra.pop('collection', None)
    if collection is None:
        collection = current_collection()
    stages = extra.pop('stage', None)
    pairs = []
    if stages:
        if isinstance(stages, (list, tuple)):
            for stage in stages:
                if stage:
                    pairs.append(('stage', stage))
        else:
            pairs.append(('stage', stages))
    if collection:
        pairs.append(('collection', collection))
    for key, value in extra.items():
        if value in (None, '', [], ()):
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((key, item))
        else:
            pairs.append((key, value))
    base = url_for(endpoint)
    return f'{base}?{urlencode(pairs)}' if pairs else base


def requested_stages(default_stages):
    raw = request.args.getlist('stage') or request.args.getlist('status')
    if not raw:
        return list(default_stages)
    stages = []
    seen = set()
    for value in raw:
        if value in ('new', 'paid'):
            mapped = ['order_received']
        elif value == 'in_production':
            mapped = ['ready_to_press', 'pressed']
        elif value == 'ready':
            mapped = ['packaged_ready']
        else:
            mapped = [normalize_stage_arg(value)]
        for stage in mapped:
            if stage == 'all':
                return ['all']
            if stage in STAGE_LABELS and stage not in seen:
                seen.add(stage)
                stages.append(stage)
    return stages or list(default_stages)


def ops_order_query(default_stages):
    """Orders for a Daily Operations tool, using production stages + optional group."""
    stages = requested_stages(default_stages)
    query = orders_for_stages(stages)
    collection_id = current_collection() or None
    if collection_id:
        query = query.filter_by(collection_id=collection_id)
    return query, stages, collection_id


def template_context():
    endpoint = request.endpoint or ''
    collection = current_collection()
    steps = []
    for step in FLOW_STEPS:
        steps.append({
            'id': step['id'],
            'num': step['num'],
            'label': step['label'],
            'hint': step['hint'],
            'url': ops_url(step['endpoint'], **step.get('params') or {}),
            'active': endpoint in step['active_eps'],
        })
    collections = []
    try:
        from models import Collection
        collections = Collection.query.order_by(Collection.name).all()
    except Exception:
        collections = []
    return {
        'ops_show_flow': endpoint in DAILY_ENDPOINTS,
        'ops_flow_steps': steps,
        'ops_collection': collection,
        'ops_collections': collections,
        'ops_url': ops_url,
        'ops_stage_tools': STAGE_TOOLS,
    }
