"""Size charts for the size guide page, built from the charts saved on each product."""
import json

PREFERRED_BRANDS = ['Bella+Canvas', 'Comfort Colors', 'District', 'Independent Trading Co.', 'MV Sport']

# One honest line per brand. A brand with no note here gets the general note on the page.
FIT_NOTES = {
    'Bella+Canvas': 'A modern unisex cut with a soft, slightly fitted feel. Most people order their usual size.',
    'Comfort Colors': 'A relaxed, roomy cut. Order your usual size for a lived-in look, or one size down for a closer fit.',
    'District': 'The Very Important Tee runs slightly slimmer, with shorter sleeves. If you like a looser tee, go up one size.',
    'Independent Trading Co.': 'A generous, roomy fleece. Most people order their usual size, or one size down for a closer fit.',
    'MV Sport': 'A full athletic fit, roomy through the chest and body. Order your usual size, or one down for a closer look.',
}

# Published measurements (inches, flat) for each brand's best-known style, used only when none of our own
# products for that brand has a saved chart. Taken from the manufacturers' spec sheets; garments vary by about an inch.
REFERENCE_CHARTS = {
    'District': {
        'style': 'DT6000', 'name': 'Very Important Tee',
        'rows': [('XS', 17, 27), ('S', 19, 28), ('M', 20, 29), ('L', 21.5, 30), ('XL', 23, 31), ('2XL', 24.5, 32),
                 ('3XL', 26.5, 32.5), ('4XL', 28.5, 33), ('5XL', 30.5, 33.5), ('6XL', 32.5, 34)],
    },
    'Independent Trading Co.': {
        'style': 'SS4500', 'name': 'Midweight Hooded Sweatshirt',
        'rows': [('XS', 19, 27), ('S', 20, 28), ('M', 22, 29), ('L', 24, 30), ('XL', 26, 31), ('2XL', 27, 32),
                 ('3XL', 28, 33), ('4XL', 29.5, 34), ('5XL', 31, 34.5)],
    },
    'MV Sport': {
        'style': '496', 'name': 'Pro-Weave Crewneck Sweatshirt',
        'rows': [('XS', 20.5, 26), ('S', 22.5, 26.5), ('M', 24.5, 27), ('L', 26.5, 27.5), ('XL', 28.5, 28),
                 ('2XL', 30.5, 28.5), ('3XL', 32.5, 29)],
    },
}

GENERAL_NOTE = ('Measurements are taken with the garment lying flat. If you are between sizes, or buying for '
                'someone else, send us a message and we will help you choose.')


def _num(value):
    """17 -> '17', 21.5 -> '21 1/2' (how the spec sheets write it)."""
    whole = int(value)
    frac = value - whole
    return str(whole) if not frac else f'{whole} 1/2' if abs(frac - 0.5) < 0.01 else str(value)


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

    have = {card['brand'] for card in cards if card['age'] == 'Adult'}
    for brand, ref in REFERENCE_CHARTS.items():
        if brand not in have:
            cards.append({'brand': brand, 'style': ref['style'], 'age': 'Adult', 'reference': True, 'title': ref['name'],
                          'rows': [(size, _num(chest), _num(length)) for size, chest, length in ref['rows']],
                          'note': FIT_NOTES.get(brand, '')})

    def order(card):
        try:
            rank = PREFERRED_BRANDS.index(card['brand'])
        except ValueError:
            rank = len(PREFERRED_BRANDS)
        return (rank, card['brand'].lower(), 0 if card['age'] == 'Adult' else 1)

    return sorted(cards, key=order)
