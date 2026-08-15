"""Normalize messy catalog labels so shop filters match real products.

S&S / CSV imports store values like ``T-Shirts ;Women's`` or
``Sweatshirts/Fleece;Youth`` instead of the dropdown values (Tee, Hoodie, youth).
"""
import re

SHOP_CATEGORIES = [
    ('Tee', 'T-Shirt'),
    ('Baseball Tee', 'Baseball Tee'),
    ('V-Neck', 'V-Neck T-Shirt'),
    ('Long Sleeve', 'Long Sleeve T-Shirt'),
    ('Tank', 'Tank Top'),
    ('Hoodie', 'Hoodie'),
    ('Sweatshirt', 'Sweatshirt'),
    ('Pants', 'Pants'),
    ('Shorts', 'Shorts'),
    ('Onesie', 'Onesie'),
    ('Polo', 'Polo'),
]

_CATEGORY_ALIASES = {
    't-shirt': 'Tee',
    't-shirts': 'Tee',
    'tshirt': 'Tee',
    'tee': 'Tee',
    'hoodies': 'Hoodie',
    'hoodie': 'Hoodie',
    'sweatshirts': 'Sweatshirt',
    'sweatshirt': 'Sweatshirt',
    'tank top': 'Tank',
    'tank tops': 'Tank',
    'tank': 'Tank',
    'v-neck t-shirt': 'V-Neck',
    'v-neck': 'V-Neck',
    'long sleeve t-shirt': 'Long Sleeve',
    'long sleeve': 'Long Sleeve',
    'onesies': 'Onesie',
    'onesie': 'Onesie',
    'baseball tee': 'Baseball Tee',
    'pants': 'Pants',
    'shorts': 'Shorts',
    'polo': 'Polo',
}


def canonical_category_param(value):
    if not value:
        return None
    return _CATEGORY_ALIASES.get(value.strip().lower(), value.strip())


def _val(item, key):
    if isinstance(item, dict):
        return item.get(key) or ''
    return getattr(item, key, None) or ''


def _text(item):
    return ' '.join([
        str(_val(item, 'name')),
        str(_val(item, 'category')),
        str(_val(item, 'style_number')),
    ]).lower()


def style_suffix(style_number):
    """Return the Bella suffix after the digits: B, T, Y, YCVC, CVC, GD, …"""
    raw = re.sub(r'[^A-Z0-9]', '', (style_number or '').upper())
    raw = re.sub(r'^BC', '', raw)
    match = re.search(r'\d+([A-Z]*)$', raw)
    return match.group(1) if match else ''


def infer_age(item):
    stored = str(_val(item, 'age_group')).strip().lower()
    name = str(_val(item, 'name')).lower()
    category = str(_val(item, 'category')).lower()
    suffix = style_suffix(_val(item, 'style_number'))

    # Bella style suffixes are the most reliable signal (3001Y, 3001T, 3001B).
    if suffix.startswith('Y'):
        return 'youth'
    if suffix.startswith('T'):
        return 'toddler'
    if suffix.startswith('B'):
        return 'baby'

    if 'toddler' in name:
        return 'toddler'
    if 'youth' in name:
        return 'youth'
    if any(token in name for token in ('infant', 'onesie', 'one piece')):
        return 'baby'

    if 'youth' in category:
        return 'youth'
    if 'toddler' in category:
        return 'toddler'
    if 'infant' in category:
        return 'baby'

    if stored in ('baby', 'toddler', 'youth', 'adult'):
        return stored
    return 'adult'


def infer_fit(item):
    stored = str(_val(item, 'fit_type')).strip()
    name = str(_val(item, 'name')).lower()
    category = str(_val(item, 'category')).lower()
    if "women" in name or 'ladies' in name or "women" in category:
        return "Women's"
    if stored.lower().startswith('women'):
        return "Women's"
    return 'Unisex'


def infer_category(item):
    name = str(_val(item, 'name')).lower()
    category = str(_val(item, 'category')).lower()
    blob = f'{name} {category}'

    if any(token in blob for token in ('onesie', 'one piece', 'bodysuit')):
        return 'Onesie'
    if 'sweatshort' in blob or re.search(r'\bshorts\b', blob):
        return 'Shorts'
    if any(token in blob for token in ('sweatpant', 'jogger')) or re.search(r'\bpants?\b', blob):
        return 'Pants'
    if 'hoodie' in blob or 'hooded' in blob:
        return 'Hoodie'
    if 'tank' in blob or 'spaghetti strap' in blob:
        return 'Tank'
    if 'baseball' in blob:
        return 'Baseball Tee'
    if 'v-neck' in blob or 'vneck' in blob:
        return 'V-Neck'
    if 'long sleeve' in blob or 'long-sleeve' in blob:
        return 'Long Sleeve'
    if any(token in blob for token in ('sweatshirt', 'fleece', 'crewneck')):
        return 'Sweatshirt'
    if 'polo' in blob:
        return 'Polo'
    if 'raglan' in blob and 'tee' in blob:
        return 'Tee'
    return 'Tee'


def matches_filters(item, *, age_group=None, category=None, fit_type=None):
    if age_group and infer_age(item) != age_group:
        return False
    if category and infer_category(item) != category:
        return False
    if fit_type:
        want = 'Unisex' if fit_type in ("Men's", 'Unisex') else fit_type
        if infer_fit(item) != want:
            return False
    return True
