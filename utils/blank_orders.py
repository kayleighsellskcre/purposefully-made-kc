"""Weekly blank-apparel shopping list from open production orders.

Nothing is purchased here. This is the list Kayleigh takes to S&S / SanMar
once a week for free shipping.
"""
from collections import defaultdict

from models import Product
from utils.product_filters import infer_brand
from utils.sizes import sort_sizes

VENDOR_SS = 'S&S Activewear'
VENDOR_SANMAR = 'SanMar'

VENDOR_SHOP = {
    VENDOR_SS: 'https://www.ssactivewear.com/',
    VENDOR_SANMAR: 'https://www.sanmar.com/',
}

_SANMAR_BRANDS = (
    'port & company', 'port and company', 'port & co',
    'district',
    'sport-tek', 'sport tek',
    'stanley/stella', 'stanley stella',
)


def blank_vendor(brand, style_number):
    blob = f'{brand or ""} {style_number or ""}'.lower()
    if any(token in blob for token in _SANMAR_BRANDS):
        return VENDOR_SANMAR
    style = (style_number or '').upper().replace(' ', '')
    if style.startswith(('PC', 'LPC', 'DM', 'DT', 'STTU', 'STTW', 'STTK', 'LST', 'G645', 'G644')):
        return VENDOR_SANMAR
    return VENDOR_SS


def _copy_block(style_number, color, sizes):
    lines = [f'{style_number} — {color}']
    for row in sizes:
        lines.append(f"  {row['size']} × {row['qty']}")
    return '\n'.join(lines)


def build_blank_shopping_list(orders):
    """Aggregate order lines into vendor → style → color → sizes."""
    product_ids = {
        item.product_id
        for order in orders
        for item in order.items
        if item.product_id
    }
    products = {p.id: p for p in Product.query.filter(Product.id.in_(product_ids)).all()} if product_ids else {}

    # (vendor, brand, style, name, color) -> {size: qty}
    buckets = defaultdict(lambda: defaultdict(int))
    wholesale = {}
    for order in orders:
        for item in order.items:
            product = products.get(item.product_id)
            brand = infer_brand(product or item) or ''
            style = item.style_number or (getattr(product, 'style_number', None) if product else '') or ''
            name = item.product_name or (getattr(product, 'name', None) if product else '') or ''
            color = item.color or '—'
            size = item.size or '—'
            vendor = blank_vendor(brand, style)
            key = (vendor, brand, style, name, color)
            buckets[key][size] += int(item.quantity or 0)
            if product and getattr(product, 'wholesale_cost', None) and key not in wholesale:
                wholesale[key] = float(product.wholesale_cost)

    vendors = {}
    csv_rows = []
    for (vendor, brand, style, name, color), size_map in buckets.items():
        sizes = [{'size': s, 'qty': size_map[s]} for s in sort_sizes(size_map.keys())]
        qty = sum(row['qty'] for row in sizes)
        cost = wholesale.get((vendor, brand, style, name, color))
        csv_rows.append({
            'vendor': vendor,
            'brand': brand,
            'style_number': style,
            'product_name': name,
            'color': color,
            'sizes': sizes,
            'quantity': qty,
            'cost_each': cost or 0,
        })
        shop = vendors.setdefault(vendor, {
            'name': vendor,
            'shop_url': VENDOR_SHOP.get(vendor, ''),
            'styles': {},
            'quantity': 0,
        })
        style_key = (style, name, brand)
        style_row = shop['styles'].setdefault(style_key, {
            'style_number': style,
            'product_name': name,
            'brand': brand,
            'colors': [],
            'quantity': 0,
        })
        style_row['colors'].append({
            'color': color,
            'sizes': sizes,
            'quantity': qty,
            'copy_text': _copy_block(style, color, sizes),
        })
        style_row['quantity'] += qty
        shop['quantity'] += qty

    vendor_list = []
    for vendor_name in (VENDOR_SS, VENDOR_SANMAR):
        shop = vendors.get(vendor_name)
        if not shop:
            continue
        styles = []
        for style_row in sorted(shop['styles'].values(), key=lambda r: (r['style_number'] or '', r['product_name'] or '')):
            style_row['colors'].sort(key=lambda c: (c['color'] or '').lower())
            style_row['copy_text'] = '\n\n'.join(c['copy_text'] for c in style_row['colors'])
            styles.append(style_row)
        shop['styles'] = styles
        shop['copy_text'] = '\n\n'.join(s['copy_text'] for s in styles)
        vendor_list.append(shop)

    all_copy = '\n\n'.join(
        f"{v['name']}\n{v['copy_text']}" for v in vendor_list
    )
    total_quantity = sum(v['quantity'] for v in vendor_list)
    total_cost = sum(row['cost_each'] * row['quantity'] for row in csv_rows)

    flat = []
    for row in csv_rows:
        for size_row in row['sizes']:
            flat.append({
                'vendor': row['vendor'],
                'brand': row['brand'],
                'style_number': row['style_number'],
                'product_name': row['product_name'],
                'color': row['color'],
                'size': size_row['size'],
                'quantity': size_row['qty'],
            })
    flat.sort(key=lambda r: (r['vendor'], r['style_number'], r['color'], r['size']))

    return {
        'vendors': vendor_list,
        'flat': flat,
        'all_copy': all_copy,
        'total_quantity': total_quantity,
        'total_cost': total_cost,
        'style_count': sum(len(v['styles']) for v in vendor_list),
    }
