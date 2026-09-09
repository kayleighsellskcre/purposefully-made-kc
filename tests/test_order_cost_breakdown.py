"""Admin order cost breakdown (blank + DTF)."""
from types import SimpleNamespace

from utils.order_costs import (
    item_cost_breakdown,
    order_cost_breakdown,
    apply_calculated_cogs,
    margin_band,
)


def test_item_cost_breakdown_basic():
    product = SimpleNamespace(wholesale_cost=8.50)
    item = SimpleNamespace(
        id=1,
        product=product,
        quantity=2,
        unit_price=28.00,
        subtotal=56.00,
        print_width=10.0,
        print_height=10.0,
    )
    line = item_cost_breakdown(item, dtf_rate=0.05)
    assert line['blank_cost'] == 17.00
    assert line['dtf_cost'] == 10.00  # 100 sq in * 0.05 * 2
    assert line['item_cost'] == 27.00
    assert line['customer_paid'] == 56.00
    assert line['profit'] == 29.00
    assert line['margin_band'] == 'good'
    assert line['margin_pct'] > 40


def test_item_uses_production_dims_when_missing_print_size():
    product = SimpleNamespace(wholesale_cost=5.0)
    item = SimpleNamespace(
        id=2,
        product=product,
        quantity=1,
        unit_price=30.0,
        subtotal=30.0,
        print_width=None,
        print_height=None,
    )
    prod = {'front': {'width': 11.0, 'height': 12.0}, 'back': None}
    line = item_cost_breakdown(item, dtf_rate=0.05, production=prod)
    assert line['print_sq_in'] == 132.0
    assert line['dtf_cost'] == 6.60


def test_margin_bands():
    assert margin_band(41) == 'good'
    assert margin_band(20) == 'ok'
    assert margin_band(19.9) == 'low'
    assert margin_band(None) == 'unknown'


def test_apply_calculated_cogs():
    product = SimpleNamespace(wholesale_cost=10.0)
    item = SimpleNamespace(
        id=9,
        product=product,
        quantity=1,
        unit_price=40.0,
        subtotal=40.0,
        print_width=10.0,
        print_height=10.0,
    )
    order = SimpleNamespace(
        items=[item],
        total=45.0,
        cost_of_goods=None,
        profit=None,
    )
    breakdown = order_cost_breakdown(order)
    changed = apply_calculated_cogs(order, breakdown)
    assert changed is True
    # blank 10 + dtf 5 = 15 cogs; paid 45; profit 30
    assert order.cost_of_goods == 15.0
    assert order.profit == 30.0
