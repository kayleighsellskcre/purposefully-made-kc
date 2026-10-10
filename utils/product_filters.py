"""Normalize messy catalog labels so shop filters match real products.

S&S / CSV imports store values like ``T-Shirts ;Women's`` or
``Sweatshirts/Fleece;Youth`` instead of the dropdown values (Tee, Hoodie, youth).
"""
import re

from utils.product_names import display_product_name

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

# Canonical display casing, keyed by lowercase. Supplier feeds (S&S,
# SanMar) send brand names in inconsistent casing (e.g. "BELLA+CANVAS"),
# which showed up as-is on product cards while the filter dropdown, built
# from the same style-prefix fallback list, showed "Bella+Canvas".
_BRAND_DISPLAY_NAMES = {
    'bella+canvas': 'Bella+Canvas',
    'bella + canvas': 'Bella+Canvas',
    'gildan': 'Gildan',
    'comfort colors': 'Comfort Colors',
    'sport-tek': 'Sport-Tek',
    'port & company': 'Port & Company',
    'district': 'District',
    'rabbit skins': 'Rabbit Skins',
    'stanley/stella': 'Stanley/Stella',
}

_AGE_ORDER = {'adult': 0, 'youth': 1, 'toddler': 2, 'baby': 3}
_AGE_LABELS = (
    ('adult', 'Adult'),
    ('youth', 'Youth'),
    ('toddler', 'Toddler'),
    ('baby', 'Baby'),
)
KIDS_AGES = frozenset({'baby', 'toddler', 'youth'})
_CATEGORY_ORDER = {key: i for i, (key, _label) in enumerate(SHOP_CATEGORIES)}


def infer_brand(item):
    stored = str(_val(item, 'brand')).strip()
    if stored:
        return _BRAND_DISPLAY_NAMES.get(stored.lower(), stored)
    style = re.sub(r'[^A-Z0-9]', '', str(_val(item, 'style_number')).upper())
    for prefix, brand in _BRAND_PREFIXES:
        if style.startswith(prefix):
            return brand
    return 'Bella+Canvas' if style else ''


def catalog_sort_key(product):
    """Adult → Youth → Toddler → Baby, then garment type, brand, name."""
    age = getattr(product, 'display_age', None) or infer_age(product) or ''
    category = getattr(product, 'display_category', None) or infer_category(product) or ''
    brand = (getattr(product, 'display_brand', None) or infer_brand(product) or '').lower()
    return (
        _AGE_ORDER.get(age, 9),
        _CATEGORY_ORDER.get(category, 99),
        brand,
        (getattr(product, 'name', None) or ''),
    )


def sort_catalog(products):
    items = list(products or [])
    items.sort(key=catalog_sort_key)
    return items


_AGE_ORDER_LIST = ['adult', 'youth', 'toddler', 'baby']


def infer_family_key(item):
    """Auto-detect a family key from style number, grouping age variants together.

    If the product has a non-empty ``family_key`` attribute set by an admin,
    that value is used directly (allows manually linking toddler/baby styles
    that don't share a style-number prefix with their adult counterpart).

    Auto-detection rule: strip the brand letter prefix AND the leading
    age-indicator character (Y / T / B) from the tail.  The key is therefore
    just the numeric core + any fabric/cut suffix.

    Examples — all produce the same key so they group together:
        BC3001, BC3001Y, BC3001T, BC3001B, 3001, 3001T, 3001B  →  '3001'
        BC3001CVC, BC3001YCVC, 3001CVC                          →  '3001CVC'
        PC54, PC54Y, 54, 54Y                                    →  '54'

    Dropping the brand prefix is intentional: it makes grouping robust when
    the same style is entered with and without the brand letters (e.g. the
    toddler is stored as "3001T" while the adult is "BC3001").
    """
    # Prefer the admin-set manual override when present.
    # Guard with try/except: if family_key column isn't in DB yet (migration pending)
    # accessing a deferred SQLAlchemy attribute triggers a lazy-load that raises
    # OperationalError.  Fall through silently to style-number detection in that case.
    try:
        manual = str(_val(item, 'family_key') or '').strip()
    except Exception:
        manual = ''
    if manual:
        return manual

    style = re.sub(r'[^A-Z0-9]', '', (_val(item, 'style_number') or '').upper())
    m = re.match(r'^([A-Z]*?)(\d+)([A-Z]*)$', style)
    if not m:
        return style or str(getattr(item, 'id', id(item)))
    _brand_prefix, digits, tail = m.groups()
    # Strip leading Y / T / B (age indicator); keep fabric / cut suffix (e.g. CVC, LS)
    tail_clean = re.sub(r'^[YTB]', '', tail)
    # Key = numeric core + optional suffix (brand prefix intentionally dropped)
    return digits + tail_clean


def group_products_by_family(products):
    """Group a sorted product list into style families.

    Returns a list of dicts::

        {
            'key':       str,       # family key, e.g. 'BC3001'
            'primary':   Product,   # adult member (first if no adult present)
            'members':   [Product], # all members sorted adult→youth→toddler→baby
            'ages':      [str],     # age-group labels present in this family
            'is_family': bool,      # True when 2+ age groups are represented
        }

    Products without a matching sibling still appear — as single-member families
    — so the full catalog is always rendered.
    """
    from collections import OrderedDict

    buckets = OrderedDict()
    for product in (products or []):
        key = infer_family_key(product)
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(product)

    result = []
    for key, members in buckets.items():
        def _age_rank(p):
            age = getattr(p, 'display_age', None) or infer_age(p) or 'adult'
            try:
                return _AGE_ORDER_LIST.index(age)
            except ValueError:
                return 99

        members.sort(key=_age_rank)

        seen_ages = []
        for p in members:
            age = getattr(p, 'display_age', None) or infer_age(p) or 'adult'
            if age not in seen_ages:
                seen_ages.append(age)

        primary = next(
            (p for p in members
             if (getattr(p, 'display_age', None) or infer_age(p) or 'adult') == 'adult'),
            members[0],
        )

        result.append({
            'key': key,
            'primary': primary,
            'members': members,
            'ages': seen_ages,
            'is_family': len(seen_ages) > 1,
        })

    return result


def group_catalog_by_age(products):
    """Split a sorted catalog into Adult / Youth / Toddler / Baby sections."""
    buckets = {key: [] for key, _label in _AGE_LABELS}
    for product in products or []:
        age = getattr(product, 'display_age', None) or infer_age(product) or 'adult'
        if age not in buckets:
            age = 'adult'
        buckets[age].append(product)
    return [
        {'key': key, 'label': label, 'products': buckets[key]}
        for key, label in _AGE_LABELS
        if buckets[key]
    ]


def prepare_catalog(products, *, scan_folders=True):
    """Attach display labels and sort so similar items sit together."""
    items = list(products or [])
    for product in items:
        product.display_brand = infer_brand(product) or ''
        product.display_age = infer_age(product) or ''
        product.display_category = infer_category(product) or ''
        product.display_fit = infer_fit(product) or ''
        product.display_name = display_product_name(product)
        if getattr(product, 'base_price', None) is None:
            product.base_price = 0
        preview = (getattr(product, 'front_mockup_template', None) or '').strip()
        if preview and not preview.startswith(('http://', 'https://', '/', 'data:')):
            preview = '/static/' + preview
        # Shop pages can scan folders; group-order forms skip this — listdir
        # per product is what made Create Group Order feel stuck.
        if not preview and scan_folders:
            import os
            _proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            style = (getattr(product, 'style_number', None) or '').strip()
            if style:
                # DB style numbers like "BC3001" → folder "3001"; "BC3001CVC" → "3001CVC"
                import re as _re
                style_bare = _re.sub(r'^[A-Za-z+& ]+', '', style)
                for folder in dict.fromkeys([style_bare, style]):  # deduplicate, bare first
                    if not folder:
                        continue
                    folder_path = os.path.join(_proj_root, 'static', 'images', 'products', folder)
                    if os.path.isdir(folder_path):
                        fronts = [f for f in os.listdir(folder_path) if '_front.' in f.lower()]
                        if fronts:
                            preview = f'/static/images/products/{folder}/{fronts[0]}'
                            break
        product.preview_image_url = preview
    return sort_catalog(items)


def _usable_mockup_url(url):
    from utils.mockups import SHOP_PLACEHOLDER_IMAGE
    url = (url or '').strip()
    if not url or SHOP_PLACEHOLDER_IMAGE in url:
        return ''
    if url.startswith('//'):
        return 'https:' + url
    return url


def attach_group_order_preview_images(products):
    """Fill missing create-form thumbnails from color-variant photos.

    Group-order forms skip per-product folder scans (those stalled the page).
    Most live catalogue photos live on ProductColorVariant.front_image_url,
    so one extra query restores the grid without the N+1.
    """
    from types import SimpleNamespace
    from models import ProductColorVariant, db
    from utils.mockups import lightest_front_mockup_url

    items = list(products or [])
    ids = [p.id for p in items]
    if not ids:
        return items

    rows = (
        db.session.query(
            ProductColorVariant.product_id,
            ProductColorVariant.front_image_url,
            ProductColorVariant.back_image_url,
            ProductColorVariant.side_image_url,
            ProductColorVariant.color_name,
            ProductColorVariant.color_hex,
        )
        .filter(ProductColorVariant.product_id.in_(ids))
        .all()
    )
    grouped = {}
    for pid, front, back, side, name, hex_ in rows:
        url = _usable_mockup_url(front) or _usable_mockup_url(back) or _usable_mockup_url(side)
        if not url:
            continue
        grouped.setdefault(pid, []).append(
            SimpleNamespace(front_image_url=url, color_name=name, color_hex=hex_)
        )
    for product in items:
        variant_url = lightest_front_mockup_url(grouped.get(product.id) or [])
        if variant_url:
            product.preview_image_url = variant_url
    return items


def shop_filter_options(products):
    """Filter dropdowns for /shop/, built only from products that are actually listed."""
    base = catalog_filter_options(products)
    label_map = dict(SHOP_CATEGORIES)
    categories = [
        {'key': key, 'label': label_map.get(key, key)}
        for key in base['categories']
    ]
    categories.sort(key=lambda row: _CATEGORY_ORDER.get(row['key'], 99))
    fits = []
    seen_fit = set()
    for product in products or []:
        fit = infer_fit(product)
        if fit and fit not in seen_fit:
            seen_fit.add(fit)
            fits.append(fit)
    fits.sort(key=lambda value: (0 if value == 'Unisex' else 1, value))
    return {
        'ages': base['ages'],
        'categories': categories,
        'brands': base['brands'],
        'fits': fits,
    }


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
    if present_ages & KIDS_AGES:
        insert_at = 1 if ages and ages[0]['key'] == 'adult' else 0
        ages.insert(insert_at, {'key': 'kids', 'label': 'Baby & Kids'})
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


_AGE_LETTERS = {'youth': 'Y', 'toddler': 'T', 'baby': 'B'}


def _bare_style(style_number):
    raw = re.sub(r'[^A-Z0-9]', '', (style_number or '').upper())
    return re.sub(r'^BC', '', raw)


def same_style_other_age(kid_style, adult_style, kid_age):
    """True when a kids style is the adult style plus its age letter.

    3001Y / 3001, BC3001YCVC / BC3001CVC, PC54Y / PC54, YST350 / ST350.
    """
    kid = _bare_style(kid_style)
    adult = _bare_style(adult_style)
    letter = _AGE_LETTERS.get(kid_age)
    if not kid or not adult or not letter or len(kid) != len(adult) + 1:
        return False
    return any(
        ch == letter and kid[:i] + kid[i + 1:] == adult
        for i, ch in enumerate(kid)
    )


def matching_age_styles(products):
    """{product id: [[other id, 'Adult'|'Youth'|...], ...]} for one style in two ages."""
    labels = dict(_AGE_LABELS)
    items = []
    for product in products or []:
        age = getattr(product, 'display_age', None) or infer_age(product) or 'adult'
        brand = (getattr(product, 'display_brand', None) or infer_brand(product) or '').lower()
        items.append((product, age, brand))
    twins = {}
    for kid, kid_age, kid_brand in items:
        if kid_age == 'adult':
            continue
        for adult, adult_age, adult_brand in items:
            if adult_age != 'adult' or adult_brand != kid_brand:
                continue
            if same_style_other_age(kid.style_number, adult.style_number, kid_age):
                twins.setdefault(str(kid.id), []).append([str(adult.id), labels['adult']])
                twins.setdefault(str(adult.id), []).append([str(kid.id), labels.get(kid_age, kid_age.title())])
    return twins


def _age_of(product):
    return getattr(product, 'display_age', None) or infer_age(product) or 'adult'


def age_families(products):
    """[[adult, youth, toddler, ...], [solo], ...] for one style offered in several ages.

    Families keep the store order of their adult style. Kids styles without a
    matching adult style stay on their own.
    """
    products = list(products or [])
    twins = matching_age_styles(products)
    by_id = {str(p.id): p for p in products}
    parent = {}
    for product in products:
        if _age_of(product) == 'adult':
            continue
        for other_id, _label in twins.get(str(product.id), []):
            if other_id in by_id:
                parent[str(product.id)] = other_id
                break
    children = {}
    for kid_id, adult_id in parent.items():
        children.setdefault(adult_id, []).append(by_id[kid_id])
    families = []
    for product in products:
        pid = str(product.id)
        if pid in parent:
            continue
        members = [product] + children.get(pid, [])
        members.sort(key=lambda m: _AGE_ORDER.get(_age_of(m), 9))
        families.append(members)
    return families


def age_label(product):
    return dict(_AGE_LABELS).get(_age_of(product), _age_of(product).title())


def load_group_order_form_catalog():
    """Products and colors for create/edit group-order forms.

    Uses one distinct color query instead of loading every variant per product.
    That N+1 pattern was crashing the logged-in Create Group Order page
    (Cloudflare ERR_HTTP2_PROTOCOL_ERROR / origin reset).
    """
    from sqlalchemy.orm import load_only
    from models import Product, ProductColorVariant, db

    products = prepare_catalog(
        Product.query.filter_by(is_active=True).options(
            load_only(
                Product.id,
                Product.name,
                Product.style_number,
                Product.brand,
                Product.category,
                Product.age_group,
                Product.fit_type,
                Product.base_price,
                Product.front_mockup_template,
                Product.is_active,
                Product.family_key,   # needed by infer_family_key — must not be deferred
            )
        ).all(),
        scan_folders=False,
    )
    attach_group_order_preview_images(products)
    from utils.mockups import _usable_image_url
    products = [p for p in products if _usable_image_url(getattr(p, 'preview_image_url', None))]
    ids = [p.id for p in products]
    all_colors = []
    colors_by_brand = {}   # {brand: [sorted color names]}
    uniform_colors_by_product = {}  # {product_id: [sorted color names]}
    color_swatches = {}  # {"Brand||Display": hex, "Display": hex}
    fan_color_picker = {'palette': [], 'products': {}, 'twins': {}}
    try:
        if ids:
            rows = (
                db.session.query(
                    Product.id,
                    Product.brand,
                    ProductColorVariant.color_name,
                    ProductColorVariant.color_hex,
                    ProductColorVariant.color_swatch_url,
                )
                .join(ProductColorVariant, ProductColorVariant.product_id == Product.id)
                .filter(
                    Product.id.in_(ids),
                    ProductColorVariant.color_name.isnot(None),
                    ProductColorVariant.color_name != '',
                )
                .distinct()
                .order_by(Product.brand, ProductColorVariant.color_name)
                .all()
            )
            from utils.color_names import display_color_name, swatch_hex, unique_display_colors
            from utils.swatches import usable_swatch_url
            seen_colors: set[str] = set()
            product_hex = {}  # {product_id: {display label: hex}}
            product_swatch = {}  # {product_id: {display label: manufacturer swatch image}}
            for product_id, brand, color, color_hex, swatch_url in rows:
                if not color:
                    continue
                uniform_colors_by_product.setdefault(str(product_id), []).append(color)
                brand_key = brand or 'Other'
                colors_by_brand.setdefault(brand_key, []).append(color)
                seen_colors.add(color)
                label = display_color_name(color)
                hex_value = swatch_hex(color, color_hex) if label else None
                if hex_value:
                    color_swatches.setdefault(f'{brand_key}||{label}', hex_value)
                    color_swatches.setdefault(label, hex_value)
                    product_hex.setdefault(str(product_id), {}).setdefault(label, hex_value)
                swatch_img = usable_swatch_url(swatch_url) if label else None
                if swatch_img:
                    product_swatch.setdefault(str(product_id), {}).setdefault(label, swatch_img)
            all_colors = unique_display_colors(seen_colors)
            colors_by_brand = {
                brand: unique_display_colors(colors)
                for brand, colors in colors_by_brand.items()
            }
            colors_by_brand = {brand: colors for brand, colors in colors_by_brand.items() if colors}
            uniform_colors_by_product = {
                pid: unique_display_colors(colors)
                for pid, colors in uniform_colors_by_product.items()
            }
            # Shared [label, hex, swatch image] palette so the inline JSON
            # stays small even when dozens of shirts carry the same colors.
            palette_index = {}
            for pid, labels in uniform_colors_by_product.items():
                indexes = []
                for label in labels:
                    hex_value = product_hex.get(pid, {}).get(label) or ''
                    swatch_img = product_swatch.get(pid, {}).get(label) or ''
                    entry = (label, hex_value, swatch_img)
                    if entry not in palette_index:
                        palette_index[entry] = len(fan_color_picker['palette'])
                        fan_color_picker['palette'].append(list(entry))
                    indexes.append(palette_index[entry])
                if indexes:
                    fan_color_picker['products'][pid] = indexes
            fan_color_picker['twins'] = matching_age_styles(products)
    except Exception:
        all_colors = []
        colors_by_brand = {}
        uniform_colors_by_product = {}
        color_swatches = {}
        fan_color_picker = {'palette': [], 'products': {}, 'twins': {}}
    return {
        'products': products,
        'all_colors': all_colors,
        'colors_by_brand': colors_by_brand,
        'uniform_colors_by_product': uniform_colors_by_product,
        'color_swatches': color_swatches,
        'fan_color_picker': fan_color_picker,
        # Group-order organizers upload the artwork for that specific store.
        # The general design gallery is intentionally not offered here.
        'gallery_designs': [],
        'catalog_filter_opts': catalog_filter_options(products),
        'catalog_filter_picker': True,
    }


def requested_ages(age_group):
    """None means every age. 'kids' is baby, toddler, and youth together."""
    raw = str(age_group or '').strip().lower()
    if not raw:
        return None
    if raw in ('kids', 'kid', 'baby & kids', 'baby and kids'):
        return set(KIDS_AGES)
    return {raw}


def matches_filters(item, *, age_group=None, category=None, fit_type=None):
    wanted_ages = requested_ages(age_group)
    if wanted_ages and infer_age(item) not in wanted_ages:
        return False
    if category and infer_category(item) != category:
        return False
    if fit_type:
        want = 'Unisex' if fit_type in ("Men's", 'Unisex') else fit_type
        if infer_fit(item) != want:
            return False
    return True
