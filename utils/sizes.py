"""Apparel size ordering — baby → toddler → youth → adult, then XS…6XL."""

import re

_LETTER_RANK = {
    'PREMIE': -5, 'PREEMIE': -5, 'NB': -4, 'N': -4, 'NEWBORN': -4,
    'XXS': 0, '2XS': 0,
    'XS': 1, 'XSM': 1, 'XSMALL': 1,
    'S': 2, 'SM': 2, 'SMALL': 2,
    'M': 3, 'MD': 3, 'MED': 3, 'MEDIUM': 3,
    'L': 4, 'LG': 4, 'LARGE': 4,
    'XL': 5, 'XLG': 5, 'XLARGE': 5,
    'XXL': 6, '2XL': 6, '2X': 6, 'XXLARGE': 6,
    'XXXL': 7, '3XL': 7, '3X': 7, 'XXXLARGE': 7,
    '4XL': 8, '4X': 8,
    '5XL': 9, '5X': 9,
    '6XL': 10, '6X': 10,
    '7XL': 11, '7X': 11,
    'OS': 80, 'ONESIZE': 80,
}

# Age group so mixed catalogs still sort: baby, toddler, youth, adult.
_AGE_BABY, _AGE_TODDLER, _AGE_YOUTH, _AGE_ADULT = 0, 1, 2, 3

_YOUTH_TOKEN = {
    'YXS': 'XS', 'YS': 'S', 'YM': 'M', 'YL': 'L',
    'YXL': 'XL', 'YXXL': 'XXL', 'Y2XL': '2XL', 'Y3XL': '3XL',
}


def _norm(size) -> str:
    s = str(size or '').strip().upper()
    s = s.replace('X-LARGE', 'XL').replace('X LARGE', 'XL')
    s = s.replace('XX-LARGE', 'XXL').replace('XX LARGE', 'XXL')
    s = s.replace('ONE SIZE', 'ONESIZE').replace('ONE-SIZE', 'ONESIZE')
    s = re.sub(r'(\d+)\s*[-/]\s*(\d+)\s*M', r'\1TO\2M', s)
    s = s.replace('SMALL', 'S').replace('MEDIUM', 'M').replace('LARGE', 'L')
    s = re.sub(r'[\s_\-]+', '', s)
    s = s.replace('YOUTH', 'Y')
    s = s.replace('TODDLER', '')
    s = s.replace('ADULT', '')
    s = s.replace('BABY', '')
    s = s.replace('INFANT', '')
    s = s.replace('ONESIE', '')
    return s


def size_sort_key(size):
    """Sort key: (age_group, rank, original). Unknown sizes go last, A–Z."""
    raw = str(size or '').strip()
    s = _norm(raw)
    if not s:
        return (99, 999, raw)

    age = _AGE_ADULT

    if s in ('NB', 'N', 'NEWBORN', 'PREMIE', 'PREEMIE'):
        return (_AGE_BABY, _LETTER_RANK.get(s, -4), raw)

    if s in _YOUTH_TOKEN:
        age = _AGE_YOUTH
        s = _YOUTH_TOKEN[s]
    elif s.startswith('Y') and len(s) > 1 and s[1:] in _LETTER_RANK:
        age = _AGE_YOUTH
        s = s[1:]

    # Newborn / months: 0-3M, 3M, 6-9M, 12M, 18M, 24M
    m = re.match(r'^(\d+)(?:TO|/)?(\d+)?M(?:ONTHS?)?$', s)
    if m:
        start = int(m.group(1))
        return (_AGE_BABY, start, raw)

    # Toddler: 2T, 3T, 4T…
    m = re.match(r'^(\d+)T$', s)
    if m:
        return (_AGE_TODDLER, int(m.group(1)), raw)

    # Numeric youth (2, 4, 5/6, 8, 10, 12, 14, 16)
    m = re.match(r'^(\d+)(?:/(\d+))?$', s)
    if m:
        return (_AGE_YOUTH, int(m.group(1)), raw)

    # 2XL, 3X, 6XL
    m = re.match(r'^(\d+)X[LS]?$', s)
    if m:
        n = int(m.group(1))
        return (age, 4 + n, raw)  # 2XL → 6, same as _LETTER_RANK

    if s in _LETTER_RANK:
        return (age, _LETTER_RANK[s], raw)

    return (99, 999, raw)


DEFAULT_ADULT_SIZES = ['S', 'M', 'L', 'XL', '2XL', '3XL']
DEFAULT_YOUTH_SIZES = ['YS', 'YM', 'YL', 'YXL']
_YOUTH_AGE_GROUPS = frozenset(('youth', 'toddler', 'baby', 'kids', 'kid', 'infant'))


def _inventory_size_labels(inventory):
    if isinstance(inventory, dict):
        data = inventory
    else:
        from utils.json_fields import parse_json_object
        data = parse_json_object(inventory)
    return [str(key).strip() for key in (data or {}) if str(key).strip()]


def shop_sizes_for_product(product, variants=None):
    """Sizes the customizer should offer, even when available_sizes was never saved.

    A style can have 30 colour mockups and still ship with an empty size list.
    The size grid then rendered nothing, so the customer could pick a colour
    and never a size. Prefer the listed sizes, then inventory keys, then a
    default adult/youth run so the page is always orderable.
    """
    from utils.json_fields import parse_json_list

    listed = parse_json_list(getattr(product, 'available_sizes', None))
    if listed:
        return sort_sizes(listed)

    if variants is None:
        variants = list(getattr(product, 'color_variants', None) or [])

    labels = []
    for variant in variants:
        if isinstance(variant, dict):
            inventory = variant.get('inventory') or variant.get('size_inventory')
        else:
            inventory = getattr(variant, 'size_inventory', None)
        labels.extend(_inventory_size_labels(inventory))
    if labels:
        return sort_sizes(labels)

    age = (getattr(product, 'age_group', None) or '').strip().lower()
    if age in _YOUTH_AGE_GROUPS:
        return list(DEFAULT_YOUTH_SIZES)
    return list(DEFAULT_ADULT_SIZES)


def sort_sizes(sizes):
    """Return a new list in true ascending size order. Drops empties, keeps uniqueness."""
    if not sizes:
        return []
    seen = set()
    unique = []
    for s in sizes:
        label = str(s).strip() if s is not None else ''
        if not label:
            continue
        key = label.upper()
        if key in seen:
            continue
        seen.add(key)
        unique.append(label)
    return sorted(unique, key=size_sort_key)
