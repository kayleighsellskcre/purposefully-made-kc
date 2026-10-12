"""Cotton and CVC (cotton/poly blend) versions of the same shirt, shown as one.

Bella+Canvas 3001 (100% cotton) and 3001CVC (heather blends) are the same shirt
in different fabrics. Shoppers should see ONE shirt with every color, and the
color they pick decides which vendor style they are really buying. Behind the
scenes the two styles stay separate products, so prices, stock, blanks lists
and old orders all stay exact.

A pair is: same brand, same number, same age letter (Y/T/B), one without "CVC"
and one with it. Brand letters in front of the number (BC3001 vs 3001) are
ignored.
"""
import re

_STYLE = re.compile(r'^([A-Z]*?)(\d+)([A-Z]*)$')


def _brand_key(product):
    brand = getattr(product, 'brand', None)
    if not (brand or '').strip():
        try:
            from utils.product_filters import infer_brand
            brand = infer_brand(product)
        except Exception:
            brand = ''
    return re.sub(r'[^a-z0-9]', '', (brand or '').lower())


def style_parts(style_number):
    """(number, rest-without-CVC, is_blend) for a style number, or None."""
    style = re.sub(r'[^A-Z0-9]', '', (style_number or '').upper())
    match = _STYLE.match(style)
    if not match:
        return None
    _prefix, digits, tail = match.groups()
    is_blend = tail.endswith('CVC')
    return digits, (tail[:-3] if is_blend else tail), is_blend


def pair_key(product):
    """Key two products share when they are the cotton and CVC version of one shirt."""
    parts = style_parts(getattr(product, 'style_number', None))
    if not parts:
        return None
    digits, tail, _is_blend = parts
    return (_brand_key(product), digits, tail)


def is_blend(product):
    parts = style_parts(getattr(product, 'style_number', None))
    return bool(parts and parts[2])


def blend_pairs(products):
    """[(cotton_product, blend_product)] for every pair present in ``products``."""
    slots = {}
    for product in products or []:
        key = pair_key(product)
        if key is None:
            continue
        slot = 'blend' if is_blend(product) else 'base'
        slots.setdefault(key, {}).setdefault(slot, product)
    return [(row['base'], row['blend']) for row in slots.values() if 'base' in row and 'blend' in row]


def find_partner(product):
    """The other fabric of this shirt in the active catalog, or None."""
    from models import Product
    parts = style_parts(getattr(product, 'style_number', None))
    if not parts:
        return None
    digits = parts[0]
    candidates = Product.query.filter(
        Product.is_active == True,  # noqa: E712
        Product.style_number.ilike(f'%{digits}%'),
        Product.id != product.id,
    ).all()
    key = pair_key(product)
    want_blend = not is_blend(product)
    for other in candidates:
        if pair_key(other) == key and is_blend(other) == want_blend:
            return other
    return None


def fabric_label(product):
    """Short fabric note for a color: 'Cotton/poly blend' for CVC, else the product's own summary."""
    if is_blend(product):
        return 'Cotton/poly blend'
    return (getattr(product, 'fabric_summary', None) or '').strip()


def partner_map():
    """{cotton product id: blend product id} for every pair in the active catalog."""
    from models import Product
    return {cotton.id: blend.id
            for cotton, blend in blend_pairs(Product.query.filter_by(is_active=True).all())}


def expand_with_blends(product_ids):
    """Picking the cotton shirt in a group-order form also picks its CVC twin.

    The forms show one shirt with every color; behind it the store holds both
    vendor styles. A store that only ever chose the CVC style is left alone.
    """
    ids = []
    for value in product_ids or []:
        try:
            pid = int(value)
        except (TypeError, ValueError):
            continue
        if pid not in ids:
            ids.append(pid)
    twins = partner_map()
    out = []
    for pid in ids:
        out.append(pid)
        twin = twins.get(pid)
        if twin and twin not in ids and twin not in out:
            out.append(twin)
    return out


def replicate_blend_color_picks(allowed_colors_json):
    """Colors picked for a cotton shirt apply to its CVC twin too (one picker, two styles)."""
    import json
    from utils.group_orders import PRODUCT_COLOR_PREFIX
    try:
        parsed = json.loads(allowed_colors_json) if allowed_colors_json else None
    except (TypeError, ValueError):
        return allowed_colors_json
    if not isinstance(parsed, dict):
        return allowed_colors_json
    twins = partner_map()
    changed = False
    for key in list(parsed):
        if not str(key).startswith(PRODUCT_COLOR_PREFIX):
            continue
        try:
            pid = int(str(key)[len(PRODUCT_COLOR_PREFIX):])
        except ValueError:
            continue
        twin_key = f'{PRODUCT_COLOR_PREFIX}{twins[pid]}' if pid in twins else None
        if twin_key and twin_key not in parsed:
            parsed[twin_key] = list(parsed[key])
            changed = True
    return json.dumps(parsed, separators=(',', ':')) if changed else allowed_colors_json
