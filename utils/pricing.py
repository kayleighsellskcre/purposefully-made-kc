"""The one place item prices are decided.

Every rule here used to be duplicated between the customizer JavaScript in
templates/shop/customize.html and routes/cart.py, and the browser's number was
the one that got charged. Now the browser's figure is only ever used to detect
a mismatch and warn; this module produces the number of record.

Keep the constants and the JS in customize.html in sync. tests/test_pricing.py
asserts the values below, so a change here without a matching change there
will fail the suite rather than silently mischarge someone.
"""
from utils.print_sizes import classify_age

# A left- or right-chest print is small, so it costs less to produce.
SMALL_LOGO_PLACEMENTS = ('left_chest', 'right_chest')
SMALL_LOGO_DISCOUNT = 2.00

# Adult extended sizes cost more blank. Youth sizing never gets a surcharge.
EXTENDED_SIZE_SURCHARGES = {
    '2XL': 2.00, '2X': 2.00, 'XXL': 2.00,
    '3XL': 3.00, '3X': 3.00, 'XXXL': 3.00,
    '4XL': 4.00, '4X': 4.00,
}

# A second print location on the back.
BACK_DESIGN_FEE = 6.00

# A garment with no artwork at all skips the transfer entirely.
BLANK_ITEM_DISCOUNT = 12.00


def size_surcharge(product, size):
    """Extra cost for an extended adult size. Youth garments always return 0."""
    if not size:
        return 0.0
    if classify_age(product) != 'adult':
        return 0.0
    return EXTENDED_SIZE_SURCHARGES.get(str(size).strip().upper(), 0.0)


def calculate_unit_price(
    product,
    size=None,
    placement=None,
    has_back_design=False,
    is_blank=False,
    design_fee=0.0,
):
    """Price for one garment, before quantity.

    `design_fee` is the "Have Us Recreate" charge stored on the Design row
    ($0 exact copy, $4 with changes, $20 from scratch). It is passed in rather
    than looked up so this function stays free of database access and is
    trivially testable.
    """
    price = float(product.base_price or 0)

    if placement in SMALL_LOGO_PLACEMENTS:
        price -= SMALL_LOGO_DISCOUNT

    price += size_surcharge(product, size)

    if has_back_design:
        price += BACK_DESIGN_FEE

    if is_blank:
        # A blank cannot also carry a back design, but clamp anyway so a bad
        # combination can never produce a negative line item.
        price = max(0.0, price - BLANK_ITEM_DISCOUNT)

    price += float(design_fee or 0)

    return round(max(0.0, price), 2)


def price_cart_item(item, product, design=None):
    """Recompute a stored cart item's unit price from the database.

    Used at checkout so a session that was tampered with, or one that predates
    a price change, is corrected before payment.
    """
    meta = item.get('back_design_meta') or {}
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            meta = {}
    if not isinstance(meta, dict):
        meta = {}

    has_back_design = bool(
        item.get('back_design_url') or meta.get('name') or meta.get('number')
    )
    has_front_design = bool(item.get('design_url') or item.get('design_id'))
    is_blank = not (has_front_design or has_back_design)

    design_fee = 0.0
    if design is not None:
        design_fee = float(getattr(design, 'design_fee', 0) or 0)

    return calculate_unit_price(
        product,
        size=item.get('size'),
        placement=item.get('placement'),
        has_back_design=has_back_design,
        is_blank=is_blank,
        design_fee=design_fee,
    )
