"""A checkup of every active style: what a customer would expect to see on the shop, but this style does not have.

The customizer page itself is the same for every style. What can differ is the information behind it, so a style with no
size chart, no fabric note or no back picture for a color looks thinner than the others. This lists those gaps.
"""
from __future__ import annotations

import json

CHECKS = [
    ('size_chart', 'Size chart'),
    ('description', 'Description'),
    ('fabric', 'Fabric'),
    ('fit_guide', 'Fit guide'),
    ('softness', 'Softness rating'),
    ('cost', 'Your cost'),
    ('colors', 'Colors'),
    ('front_pics', 'Front pictures'),
    ('back_pics', 'Back pictures'),
]


def _json_list(raw):
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def checkup():
    """(rows, totals). Each row: the product and the labels of what it is missing. Only styles with a gap are listed."""
    from models import Product, ProductColorVariant

    products = Product.query.filter(Product.is_active.is_(True)).order_by(Product.brand, Product.style_number).all()
    by_product = {}
    for v in ProductColorVariant.query.filter(ProductColorVariant.product_id.in_([p.id for p in products] or [0])).all():
        by_product.setdefault(v.product_id, []).append(v)

    rows, totals = [], {key: 0 for key, _ in CHECKS}
    labels = dict(CHECKS)
    for p in products:
        variants = by_product.get(p.id, [])
        missing = []
        if not (p.size_chart or '').strip():
            missing.append('size_chart')
        if len((p.description or '').strip()) < 20:
            missing.append('description')
        if not ((p.fabric_details or '').strip() or (p.fabric_summary or '').strip()):
            missing.append('fabric')
        if not (p.fit_guide or '').strip():
            missing.append('fit_guide')
        if not p.softness_rating:
            missing.append('softness')
        if not p.wholesale_cost:
            missing.append('cost')
        if not variants and not _json_list(p.available_colors):
            missing.append('colors')
        no_front = [v.color_name for v in variants if not (v.front_image_url or '').strip()]
        no_back = [v.color_name for v in variants if not (v.back_image_url or '').strip()]
        if no_front:
            missing.append('front_pics')
        if no_back:
            missing.append('back_pics')
        if not missing:
            continue
        for key in missing:
            totals[key] += 1
        notes = []
        if no_front:
            notes.append(f"{len(no_front)} of {len(variants)} colors have no front picture")
        if no_back:
            notes.append(f"{len(no_back)} of {len(variants)} colors have no back picture")
        rows.append({'product': p, 'missing': [labels[k] for k in missing], 'notes': notes})
    return rows, [(labels[k], totals[k]) for k, _ in CHECKS], len(products)
