"""Family at-cost promo (AIRMATTRESS): wholesale + DTF + flat fee, cash only."""
from __future__ import annotations

import json

from flask import current_app, session

from utils.order_costs import get_dtf_costs, shirt_unit_cost, _safe_float, _print_area_sq_in


FAMILY_PROMO_FLAT_FEE = 5.00
SESSION_KEY = 'family_promo_code'


def configured_family_promo_code() -> str:
    code = (current_app.config.get('FAMILY_PROMO_CODE') or 'AIRMATTRESS').strip()
    return code.upper()


def normalize_promo_code(code) -> str:
    return (str(code or '')).strip().upper()


def is_family_promo_code(code) -> bool:
    entered = normalize_promo_code(code)
    if not entered:
        return False
    return entered == configured_family_promo_code()


def get_session_family_promo() -> str | None:
    code = normalize_promo_code(session.get(SESSION_KEY))
    if code and is_family_promo_code(code):
        return code
    return None


def set_session_family_promo(code: str | None) -> str | None:
    if code and is_family_promo_code(code):
        session[SESSION_KEY] = normalize_promo_code(code)
        session.modified = True
        return session[SESSION_KEY]
    session.pop(SESSION_KEY, None)
    session.modified = True
    return None


def clear_session_family_promo():
    set_session_family_promo(None)


def _cart_item_proxy(item: dict):
    """Minimal object so _print_area_sq_in can read cart dict fields."""
    transfer = item.get('transfer_production')
    if isinstance(transfer, str):
        try:
            transfer = json.loads(transfer)
        except (TypeError, ValueError, json.JSONDecodeError):
            transfer = None
    return type('CartPrintProxy', (), {
        'print_width': item.get('print_width'),
        'print_height': item.get('print_height'),
    })(), transfer if isinstance(transfer, dict) else None


def dtf_unit_cost_for_cart_item(item: dict, dtf_rate=None) -> float:
    """DTF transfer cost for one garment (not multiplied by qty)."""
    if dtf_rate is None:
        dtf_rate = get_dtf_costs().get('dtf_per_sq_in', 0.05)
    dtf_rate = _safe_float(dtf_rate, 0.05) or 0.0
    proxy, production = _cart_item_proxy(item)
    sq_in = _print_area_sq_in(proxy, production=production)
    if not sq_in:
        return 0.0
    return round(sq_in * dtf_rate, 4)


def at_cost_unit_price(item: dict, product) -> float:
    blank = shirt_unit_cost(product)
    blank = blank if blank is not None else 0.0
    dtf = dtf_unit_cost_for_cart_item(item)
    return round(blank + dtf, 2)


def apply_family_at_cost_prices(cart: list) -> list:
    """Overwrite each cart line's unit_price with wholesale + DTF (per unit)."""
    from models import Product

    dtf_rate = get_dtf_costs().get('dtf_per_sq_in', 0.05)
    for item in cart or []:
        if not isinstance(item, dict):
            continue
        product_id = item.get('product_id')
        try:
            product = Product.query.get(int(product_id)) if product_id is not None else None
        except (TypeError, ValueError):
            product = None
        if not product:
            continue
        blank = shirt_unit_cost(product) or 0.0
        dtf = dtf_unit_cost_for_cart_item(item, dtf_rate=dtf_rate)
        item['unit_price'] = round(blank + dtf, 2)
        item['_family_at_cost'] = True
    return cart


def family_promo_totals(cart: list) -> dict:
    """At-cost subtotal + flat fee; no shipping, no tax."""
    apply_family_at_cost_prices(cart)
    subtotal = 0.0
    for item in cart or []:
        if not isinstance(item, dict):
            continue
        try:
            qty = int(item.get('quantity') or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            unit = float(item.get('unit_price') or 0)
        except (TypeError, ValueError):
            unit = 0.0
        if qty > 0 and unit > 0:
            subtotal += qty * unit
    subtotal = round(subtotal, 2)
    fee = float(current_app.config.get('FAMILY_PROMO_FLAT_FEE', FAMILY_PROMO_FLAT_FEE) or FAMILY_PROMO_FLAT_FEE)
    fee = round(fee, 2)
    total = round(subtotal + fee, 2)
    return {
        'subtotal': subtotal,
        'shipping_cost': 0.0,
        'tax': 0.0,
        'flat_fee': fee,
        'total': total,
        'family_promo': True,
        'promo_code': configured_family_promo_code(),
    }
