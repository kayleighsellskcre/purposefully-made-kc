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
    'bodysuit': 'Onesie',
    'bodysuits': 'Onesie',
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


_BRAND_PREFIXES = (
    ('STTU', 'Stanley/Stella'),
    ('STTW', 'Stanley/Stella'),
    ('STTK', 'Stanley/Stella'),
    ('LST', 'Sport-Tek'),
    ('G185', 'Gildan'),
    ('G180', 'Gildan'),
    ('G5', 'Gildan'),
    ('LPC', 'Port & Company'),
    ('RS', 'Rabbit Skins'),
    ('CC', 'Comfort Colors'),
    ('DT', 'District'),
    ('DM', 'District'),
    ('PC', 'Port & Company'),
    ('ST', 'Sport-Tek'),
    ('BC', 'Bella+Canvas'),
)

_AGE_ORDER = {'adult': 0, 'youth': 1, 'toddler': 2, 'baby': 3}


def infer_brand(item):
    stored = str(_val(item, 'brand')).strip()
    if stored:
        return stored
    style = re.sub(r'[^A-Z0-9]', '', str(_val(item, 'style_number')).upper())
    for prefix, brand in _BRAND_PREFIXES:
        if style.startswith(prefix):
            return brand
    return 'Bella+Canvas' if style else ''


def prepare_catalog(products):
    """Attach display labels and sort so similar items sit together."""
    items = list(products or [])
    for product in items:
        product.display_brand = infer_brand(product) or ''
        product.display_age = infer_age(product) or ''
        product.display_category = infer_category(product) or ''
        product.display_fit = infer_fit(product) or ''
        if getattr(product, 'base_price', None) is None:
            product.base_price = 0
        preview = (getattr(product, 'front_mockup_template', None) or '').strip()
        if preview and not preview.startswith(('http://', 'https://', '/', 'data:')):
            preview = '/static/' + preview
        product.preview_image_url = preview
    items.sort(key=lambda p: (
        _AGE_ORDER.get(getattr(p, 'display_age', None), 9),
        getattr(p, 'display_category', None) or '',
        (getattr(p, 'display_brand', None) or '').lower(),
        p.name or '',
    ))
    return items


def catalog_filter_options(products):
    """Unique Who / Type / Brand values present in this list."""
    try:
        items = list(products or [])
    except Exception:
        return {'ages': [], 'categories': [], 'brands': []}
    present_ages = {infer_age(p) for p in items}
    ages = [
        {'key': key, 'label': label}
        for key, label in (('adult', 'Adult'), ('youth', 'Youth'), ('toddler', 'Toddler'), ('baby', 'Baby'))
        if key in present_ages
    ]
    categories, brands = [], []
    seen_cat, seen_brand = set(), set()
    for product in items:
        cat = infer_category(product)
        if cat and cat not in seen_cat:
            seen_cat.add(cat)
            categories.append(cat)
        brand = infer_brand(product)
        if brand and brand not in seen_brand:
            seen_brand.add(brand)
            brands.append(brand)
    return {'ages': ages, 'categories': sorted(categories), 'brands': sorted(brands)}


def load_group_order_form_catalog():
    """Products, colors, and designs for create/edit group-order forms.

    Uses one distinct color query instead of loading every variant per product.
    That N+1 pattern was crashing the logged-in Create Group Order page
    (Cloudflare ERR_HTTP2_PROTOCOL_ERROR / origin reset).
    """
    from models import Design, Product, ProductColorVariant, db

    products = prepare_catalog(Product.query.filter_by(is_active=True).all())
    ids = [p.id for p in products]
    all_colors = []
    gallery_designs = []
    try:
        if ids:
            rows = (
                db.session.query(ProductColorVariant.color_name)
                .filter(
                    ProductColorVariant.product_id.in_(ids),
                    ProductColorVariant.color_name.isnot(None),
                    ProductColorVariant.color_name != '',
                )
                .distinct()
                .order_by(ProductColorVariant.color_name)
                .all()
            )
            all_colors = [name for (name,) in rows if name]
    except Exception:
        all_colors = []
    try:
        gallery_designs = (
            Design.query.filter_by(is_gallery=True)
            .order_by(Design.uploaded_at.desc())
            .limit(80)
            .all()
        )
    except Exception:
        gallery_designs = []
    return {
        'products': products,
        'all_colors': all_colors,
        'gallery_designs': gallery_designs,
        'catalog_filter_opts': catalog_filter_options(products),
        'catalog_filter_picker': True,
    }


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
