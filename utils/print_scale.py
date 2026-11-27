"""How big the main print is: Medium, Standard or Oversized.

Standard is the print the shop has always made (the width chart in utils/print_sizes.py). Medium sits between a chest
logo and a standard print. Oversized is the large full-front or full-back look. Chest logos (left and right chest) keep
their own placements, so a scale only applies to the center front and the center back.

Each scale has a width factor (of the standard chart width) and a price change, which the owner edits in Site Settings.
The price change is stored as a setting; the factors are fixed here so the transfer sheet and the preview always agree.
"""
from __future__ import annotations

SCALES = [('medium', 'Medium'), ('standard', 'Standard'), ('oversized', 'Oversized')]
SCALE_KEYS = tuple(k for k, _ in SCALES)
DEFAULT_SCALE = 'standard'

# Fraction of the standard chart width. Medium is a bit bigger than a chest logo (which is 0.4).
WIDTH_FACTOR = {'medium': 0.6, 'standard': 1.0, 'oversized': 1.3}

# The Oversized Full Back is a little bigger than the Oversized front: 1.45 of the chart width is about 14.5 in on an adult
# medium. Much past this a normal portrait picture runs taller than the 19 in safe height and gets held back anyway.
BACK_OVERSIZED_FACTOR = 1.45
BACK_PLACEMENTS = ('center_back', 'full_back')

# Taller than the standard 15.5 in limit, so a big print is not flagged as too tall.
OVERSIZED_SAFE_HEIGHT_ADULT = 19.0

SCALE_PLACEMENTS = ('center_chest', 'center_back', 'full_front', 'full_back')

DEFAULT_ADJUSTMENTS = {'medium': -1.00, 'standard': 0.00, 'oversized': 6.00}
# What the Oversized Full Back costs in all, in place of the regular back print charge ($6 + the $6 Oversized change).
DEFAULT_BACK_OVERSIZED_PRICE = 12.00
_BACK_PRICE_KEY = 'print_scale_price_back_oversized'
_SETTING_KEY = 'print_scale_price_{}'

HINTS = {
    'medium': 'A bit bigger than a chest logo',
    'standard': 'Our regular full-size print',
    'oversized': 'Large, the full-chest or full-back look',
}


def normalize(value) -> str:
    value = str(value or '').strip().lower()
    return value if value in SCALE_KEYS else DEFAULT_SCALE


def applies_to(placement) -> bool:
    """Chest logos are their own size, so only the center placements can be scaled."""
    return (placement or 'center_chest') in SCALE_PLACEMENTS


def oversized_allowed(product=None, size=None, placement=None) -> bool:
    """Oversized needs room: adult garments only, no tanks, and not on the front of a hoodie (the pocket is in the way)."""
    from utils.print_sizes import classify_category, is_hoodie, is_tank
    if classify_category(product, size) != 'adult' or is_tank(product):
        return False
    if is_hoodie(product) and (placement or 'center_chest') in ('center_chest', 'full_front'):
        return False
    return True


def allowed_scales(product=None, size=None, placement=None):
    if not applies_to(placement):
        return [DEFAULT_SCALE]
    keys = ['medium', 'standard']
    if oversized_allowed(product, size, placement):
        keys.append('oversized')
    return keys


def width_factor(scale, placement=None) -> float:
    """How wide a print is, as a share of the chart width. The Oversized Full Back is a bit larger than the Oversized front."""
    scale = normalize(scale)
    if scale == 'oversized' and (placement or '') in BACK_PLACEMENTS:
        return BACK_OVERSIZED_FACTOR
    return WIDTH_FACTOR[scale]


def effective(scale, product=None, size=None, placement=None) -> str:
    """The scale that will really be used: a scale that does not fit this garment or placement falls back to Standard."""
    scale = normalize(scale)
    return scale if scale in allowed_scales(product, size, placement) else DEFAULT_SCALE


def adjustments() -> dict:
    """Price change for each scale, in dollars. The owner's saved numbers, or the defaults."""
    out = dict(DEFAULT_ADJUSTMENTS)
    try:
        from utils.site_settings import get_setting
        for key in ('medium', 'oversized'):
            raw = get_setting(_SETTING_KEY.format(key), '')
            if str(raw).strip() != '':
                out[key] = round(float(str(raw).replace('$', '').replace(',', '')), 2)
    except Exception:
        return dict(DEFAULT_ADJUSTMENTS)
    return out


def back_oversized_price() -> float:
    """The whole charge for an Oversized Full Back (it replaces the regular back print charge). The owner's number or the default."""
    try:
        from utils.site_settings import get_setting
        raw = get_setting(_BACK_PRICE_KEY, '')
        if str(raw).strip() != '':
            return round(float(str(raw).replace('$', '').replace(',', '')), 2)
    except Exception:
        pass
    return DEFAULT_BACK_OVERSIZED_PRICE


def save_back_oversized_price(value):
    from utils.site_settings import set_setting
    amount = round(float(str(value).replace('$', '').replace(',', '').strip() or 0), 2)
    if amount < 0 or amount > 200:
        raise ValueError('That amount looks wrong.')
    set_setting(_BACK_PRICE_KEY, f'{amount:.2f}', 'Oversized Full Back print price (replaces the regular back print charge)')


def save_adjustments(medium, oversized):
    from utils.site_settings import set_setting
    for key, value in (('medium', medium), ('oversized', oversized)):
        amount = round(float(str(value).replace('$', '').replace(',', '').strip() or 0), 2)
        if abs(amount) > 200:
            raise ValueError('That amount looks too large.')
        set_setting(_SETTING_KEY.format(key), f'{amount:.2f}', f'Print size price change: {key}')


def price_adjustment(scale, placement=None, product=None, size=None) -> float:
    """Dollars added to (or taken off) the garment price for this print size."""
    if not applies_to(placement):
        return 0.0
    return float(adjustments().get(effective(scale, product, size, placement), 0.0))


def choices(product=None, size=None, placement=None):
    """What the customizer offers: key, label, hint and price change, in order."""
    adj = adjustments()
    return [{'key': k, 'label': dict(SCALES)[k], 'hint': HINTS[k], 'adjust': adj[k]}
            for k in allowed_scales(product, size, placement)]
