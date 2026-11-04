"""Discount codes and the free-shipping rule.

A code takes a percent or a dollar amount off the shirts (never shipping or tax), and can also make shipping free.
The discount lowers the amount tax is charged on, like any seller coupon. The customer always pays at least $1.
Free shipping can also come from an order total: set a minimum in Site Settings (blank turns it off).
"""
from __future__ import annotations

from datetime import datetime

from models import Coupon, db

FREE_SHIP_KEY = 'free_shipping_min'
SESSION_KEY = 'coupon_code'


def normalize(code):
    return ''.join(str(code or '').split()).upper()[:40]


def find(code):
    code = normalize(code)
    return Coupon.query.filter_by(code=code).first() if code else None


def problem(coupon, merchandise, now=None):
    """Why this code cannot be used on this much merchandise, in plain words, or None when it can."""
    now = now or datetime.utcnow()
    if coupon is None or not coupon.active:
        return 'That promo code is not valid.'
    if coupon.expires_at and coupon.expires_at < now:
        return 'That promo code has expired.'
    if coupon.max_uses is not None and (coupon.uses or 0) >= coupon.max_uses:
        return 'That promo code has already been used the most times it can be.'
    if coupon.min_subtotal and float(merchandise or 0) + 0.005 < float(coupon.min_subtotal):
        return f'That code needs an order of at least ${coupon.min_subtotal:,.2f}.'
    return None


def discount_for(coupon, merchandise):
    """Dollars off the shirts, never taking the order below $1."""
    merchandise = float(merchandise or 0)
    off = 0.0
    if coupon.percent_off:
        off = merchandise * float(coupon.percent_off) / 100.0
    if coupon.amount_off:
        off += float(coupon.amount_off)
    return round(max(0.0, min(off, merchandise - 1.0)), 2)


def free_shipping_min():
    from utils.site_settings import get_setting
    try:
        value = float((get_setting(FREE_SHIP_KEY, '') or '').strip())
    except ValueError:
        return None
    return value if value > 0 else None


def record_use(order):
    """Count this order against its code. Called once, when the order is created."""
    code = getattr(order, 'coupon_code', None)
    if code:
        Coupon.query.filter_by(code=code).update({Coupon.uses: db.func.coalesce(Coupon.uses, 0) + 1},
                                                 synchronize_session=False)


def describe(coupon):
    bits = []
    if coupon.percent_off:
        bits.append(f'{coupon.percent_off:g}% off')
    if coupon.amount_off:
        bits.append(f'${coupon.amount_off:,.2f} off')
    if coupon.free_shipping:
        bits.append('free shipping')
    return ' + '.join(bits) or 'no discount'
