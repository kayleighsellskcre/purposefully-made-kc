"""Kansas sales tax, kept simple and honest.

* One rate, set in Site settings (not locked in code). Use the combined rate your CPA or the Kansas Department of
  Revenue gives you for the Shawnee pickup address.
* Kansas collects by where the customer takes the item. So:
    pickup or a hand-off (including "sent home with a child")  -> the rate
    shipped to an address in Kansas                             -> the rate
    shipped to another state                                    -> no Kansas tax
* If the ship-to state is missing or unclear, tax is charged. Someone who typed "Kansa" for the state, or whose ZIP
  code is a Kansas one, is still treated as Kansas, so a typo never turns tax off by accident.
* Shipping itself is not taxed (separately stated, true-cost delivery charges are not taxable in Kansas; confirm
  with your CPA).
Every order is labelled with where it was taxed, so the sales tax report can group by it.
"""
from __future__ import annotations

import re
import time

from flask import current_app

SETTING_KEY = 'ks_sales_tax_percent'
MIN_PERCENT, MAX_PERCENT = 0.0, 15.0
_TTL = 60
_CACHE = {'at': 0.0, 'percent': None}

LOCAL, KS_SHIPPED, OUT_OF_STATE, INVOICE = 'local', 'ks_shipped', 'out_of_state', 'invoice'
JURISDICTION_LABELS = {
    LOCAL: 'Pickup or hand-off in Kansas',
    KS_SHIPPED: 'Shipped within Kansas',
    OUT_OF_STATE: 'Shipped out of state (no Kansas tax)',
    INVOICE: 'Hand-made invoices',
}


def default_percent():
    return float(current_app.config.get('KS_SALES_TAX_PERCENT', 9.5))


def rate_percent():
    """The tax rate in percent (9.5 means 9.5%), from Site settings, cached for a minute."""
    now = time.time()
    if _CACHE['percent'] is not None and now - _CACHE['at'] < _TTL:
        return _CACHE['percent']
    percent = default_percent()
    try:
        from utils.site_settings import get_setting
        raw = (get_setting(SETTING_KEY, '') or '').strip()
        if raw:
            value = float(raw)
            if MIN_PERCENT <= value <= MAX_PERCENT:
                percent = value
    except Exception:
        percent = default_percent()
    _CACHE.update(at=now, percent=percent)
    return percent


def rate_fraction():
    return rate_percent() / 100.0


def save_rate_percent(value):
    """Store a new rate (0 to 15). Raises ValueError for anything else."""
    percent = round(float(value), 4)
    if not (MIN_PERCENT < percent <= MAX_PERCENT):
        raise ValueError(f'Enter a rate between {MIN_PERCENT:g} and {MAX_PERCENT:g} percent, like 9.6.')
    from utils.site_settings import set_setting
    set_setting(SETTING_KEY, f'{percent:g}', 'Kansas sales tax rate (percent)')
    _CACHE['at'] = 0.0
    return percent


def clear_cache():
    _CACHE.update(at=0.0, percent=None)


# ---- where was it taxed ------------------------------------------------------------------------

def is_kansas(state, zip_code=None):
    """True when the address is in Kansas. A Kansas-looking state OR a Kansas ZIP (66xxx or 67xxx) counts."""
    letters = re.sub(r'[^a-z]', '', (state or '').lower())
    if letters in ('ks', 'kansas') or letters.startswith('kans'):
        return True
    digits = re.sub(r'\D', '', zip_code or '')[:5]
    return len(digits) >= 3 and digits[:2] in ('66', '67')


def charges_tax(method, state=None, zip_code=None):
    """Should Kansas sales tax be charged on this sale?"""
    if (method or 'pickup') != 'shipping':
        return True
    if not (state or '').strip():
        return True                                            # not known yet: charge, and the form asks again
    return is_kansas(state, zip_code)


def jurisdiction_key(method, state=None, zip_code=None):
    if (method or 'pickup') != 'shipping':
        return LOCAL
    return KS_SHIPPED if charges_tax(method, state, zip_code) else OUT_OF_STATE


def classify_order(order):
    """(label key, effective rate in percent) for a finished order, from what it actually charged."""
    key = jurisdiction_key(order.fulfillment_method, order.shipping_state, order.shipping_zip)
    subtotal = float(order.subtotal or 0)
    effective = round(100.0 * float(order.tax or 0) / subtotal, 3) if subtotal > 0 else 0.0
    return key, effective
