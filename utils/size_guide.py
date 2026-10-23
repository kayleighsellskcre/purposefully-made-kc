"""Size charts for the size guide page, built from the charts saved on each product."""
import json

PREFERRED_BRANDS = ['Bella+Canvas', 'Comfort Colors', 'District', 'Independent Trading Co.', 'MV Sport']

# One honest line per brand. A brand with no note here gets the general note on the page.
FIT_NOTES = {
    'Bella+Canvas': 'A modern unisex cut with a soft, slightly fitted feel. Most people order their usual size.',
    'Comfort Colors': 'A relaxed, roomy cut. Order your usual size for a lived-in look, or one size down for a closer fit.',
}

GENERAL_NOTE = ('Measurements are taken with the garment lying flat. If you are between sizes, or buying for '
                'someone else, send us a message and we will help you choose.')


def _chart(product):
    raw = getattr(product, 'size_chart', None)
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and data else None


def brand_charts():
    """[{brand, style, age, rows: [(size, chest, length)], note}], preferred brands first."""
    from models import Product
    from utils.product_filters import infer_brand
    from utils.sizes import sort_sizes

    found = {}
    for product in Product.query.filter(Product.is_active.is_(True)).order_by(Product.id).all():
        chart = _chart(product)
        brand = (infer_brand(product) or '').strip()
        if not chart or not brand:
            continue
        age = 'Youth' if (product.age_group or '').lower() in ('youth', 'toddler', 'baby') else 'Adult'
        found.setdefault((brand, age), (product, chart))

    cards = []
    for (brand, age), (product, chart) in found.items():
        rows = []
        for size in sort_sizes(list(chart.keys())):
            row = chart[size] or {}
            rows.append((size, row.get('chest', ''), row.get('length', '')))
        cards.append({'brand': brand, 'style': product.style_number, 'age': age, 'rows': rows,
                      'note': FIT_NOTES.get(brand, '')})

    def order(card):
        try:
            rank = PREFERRED_BRANDS.index(card['brand'])
        except ValueError:
            rank = len(PREFERRED_BRANDS)
        return (rank, card['brand'].lower(), 0 if card['age'] == 'Adult' else 1)

    return sorted(cards, key=order)
