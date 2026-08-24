"""
Resolve product mockup image URLs from DB (color variants) or from uploads/mockups folder.
All mockups under uploads/mockups/{style_number}/ are used so each product shows its uploaded mockups.
"""
import os
import time
from pathlib import Path


def _mockup_dirs(app):
    """Return list of directories to search for mockup files (most preferred first)."""
    # App uploads: static/uploads/mockups (UPLOAD_FOLDER is typically static/uploads)
    basedir = app.config.get('UPLOAD_FOLDER')
    if not basedir:
        basedir = os.path.join(app.root_path, 'static', 'uploads')
    if not os.path.isabs(basedir):
        basedir = os.path.join(app.root_path, basedir)
    app_mockups = os.path.join(basedir, 'mockups')
    # Project root uploads/mockups (where bulk-uploaded mockups live)
    root_mockups = os.path.join(app.root_path, 'uploads', 'mockups')
    # static/images/products — SanMar-sourced product images
    static_images = os.path.join(app.root_path, 'static', 'images', 'products')
    return [app_mockups, root_mockups, static_images]


MOCKUP_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')

# Resolving one colour's mockup used to cost up to 12 stat() calls plus up to
# 12 directory globs. /shop/ renders every colour of every product — about 1350
# colour/view pairs on the live catalogue — so a single page load made tens of
# thousands of filesystem calls. That is why /shop/ took 2.7 seconds while every
# other page answered in under 30ms.
#
# Each style folder is now listed once and turned into two lookup tables, so the
# same resolution is a dictionary hit.
#
# (mockup search roots, style_number) -> _StyleIndex
_STYLE_INDEX = {}

# How long a cached index is trusted before its folders are stat()ed again.
# Mockups only change when an admin uploads them, so a second of staleness costs
# nothing, and it keeps a catalogue render from re-stat()ing the same folder
# once per colour.
_INDEX_TTL_SECONDS = 1.0


class _StyleIndex:
    """Everything /shop/ needs to know about one style's mockup folders.

    `filenames` is the union of every filename across the folders, used for the
    exact-match naming scheme. `by_color_view` resolves the descriptive naming
    scheme, holding the first match in the original search order (folder
    preference, then extension, then name). `listings` keeps the per-folder
    names in order for colour discovery, which wants the *last* match rather
    than the first.
    """

    __slots__ = ('fingerprint', 'checked_at', 'listings', 'filenames', 'by_color_view')

    def __init__(self, fingerprint, checked_at, listings, filenames, by_color_view):
        self.fingerprint = fingerprint
        self.checked_at = checked_at
        self.listings = listings
        self.filenames = filenames
        self.by_color_view = by_color_view


def _style_dirs(app, style_number):
    """Existing folders holding this style's mockups, most preferred first."""
    dirs = []
    for mockup_dir in _mockup_dirs(app):
        if not mockup_dir:
            continue
        style_dir = os.path.join(mockup_dir, str(style_number))
        if os.path.isdir(style_dir):
            dirs.append(style_dir)
    return dirs


def _fingerprint(style_dirs):
    """Modification times of the folders, so a new upload invalidates the cache.

    Adding a file changes its containing directory's mtime, so an admin who
    uploads a mockup sees it without waiting for a restart.
    """
    marks = []
    for path in style_dirs:
        try:
            marks.append((path, os.stat(path).st_mtime_ns))
        except OSError:
            marks.append((path, None))
    return tuple(marks)


def _color_key(color_name):
    return (color_name or '').strip().lower().replace(' ', '_')


def _build_style_index(app, style_number, now):
    style_dirs = _style_dirs(app, style_number)
    fingerprint = _fingerprint(style_dirs)

    listings = []
    for style_dir in style_dirs:
        try:
            listings.append(sorted(os.listdir(style_dir)))
        except OSError:
            listings.append([])

    filenames = set()
    for names in listings:
        filenames.update(names)

    # First match wins, in the same folder-then-extension-then-name order the
    # old per-colour scan used.
    by_color_view = {}
    for names in listings:
        for ext in MOCKUP_EXTENSIONS:
            for name in names:
                if not name.lower().endswith(ext):
                    continue
                parsed_color, parsed_view = _parse_mockup_filename(
                    style_number, name[: -len(ext)])
                if not parsed_color or not parsed_view:
                    continue
                by_color_view.setdefault((_color_key(parsed_color), parsed_view), name)

    return _StyleIndex(fingerprint, now, listings, filenames, by_color_view)


def _style_index(app, style_number):
    # Keyed by the search roots as well as the style. app.py builds an app at
    # module scope and the test suite builds another, so two apps can share this
    # process with different root_path or UPLOAD_FOLDER values. Keying on the
    # style alone let the TTL shortcut below hand one app the other's index,
    # because that path deliberately skips the fingerprint check.
    key = (tuple(_mockup_dirs(app)), str(style_number))

    now = time.monotonic()
    cached = _STYLE_INDEX.get(key)
    if cached is not None:
        if now - cached.checked_at < _INDEX_TTL_SECONDS:
            return cached
        if _fingerprint(_style_dirs(app, style_number)) == cached.fingerprint:
            cached.checked_at = now
            return cached

    index = _build_style_index(app, style_number, now)
    _STYLE_INDEX[key] = index
    return index


def clear_mockup_cache():
    """Forget every remembered folder listing. For tests and after bulk uploads."""
    _STYLE_INDEX.clear()


def _find_mockup_file(app, style_number, color_name, view):
    """
    Look for a mockup file in uploads/mockups for the given style, color, and view.
    Tries format A (3001_Aqua_front.jpg) first, then scans for format B (BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg).
    Returns the relative path for URL (e.g. 3001/3001_Aqua_front.jpg) if found, else None.
    """
    safe_color = (color_name or '').replace(' ', '_').strip()
    if not safe_color:
        return None

    index = _style_index(app, style_number)
    if not index.filenames:
        return None

    # Format A: 3001_Aqua_front.jpg
    base_name = f"{style_number}_{safe_color}_{view}"
    for ext in MOCKUP_EXTENSIONS:
        filename = base_name + ext
        if filename in index.filenames:
            return f"{style_number}/{filename}"

    # Format B: BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg
    name = index.by_color_view.get((_color_key(color_name), view.lower()))
    if name:
        return f"{style_number}/{name}"
    return None


def _mockup_url(app, rel):
    """Return URL for mockup - uses static path directly."""
    # Return path like /static/uploads/mockups/3001/3001_Aqua_front.jpg
    return f"/static/uploads/mockups/{rel}"


def get_mockup_url_for_variant(product, variant, view, app):
    """
    Return the best available mockup URL for a product color variant and view (front/back).
    Prefers local uploads/mockups so customer-uploaded images always show for design preview.
    """
    rel = _find_mockup_file(app, product.style_number, getattr(variant, 'color_name', None), view)
    if rel:
        return _mockup_url(app, rel)
    if view == 'front' and getattr(variant, 'front_image_url', None):
        return variant.front_image_url
    if view == 'back' and getattr(variant, 'back_image_url', None):
        return variant.back_image_url
    return None


def _parse_mockup_filename(style_number, stem):
    """
    Parse mockup filename to extract color and view.
    Supports:
      - 3001_Aqua_front -> color "Aqua", view "front"
      - BELLA_+_CANVAS_3001Y_Ash_Front_High -> color "Ash", view "front" (when style is 3001Y)
    Returns (color_name, view) or (None, None).
    """
    parts = stem.split('_')
    if len(parts) < 3:
        return None, None
    style_str = str(style_number)
    # Format A: 3001_Aqua_front
    if parts[0] == style_str:
        view = parts[-1].lower()
        if view not in ('front', 'back', 'side'):
            return None, None
        color_parts = parts[1:-1]
        color_name = ' '.join(color_parts).title()
        return color_name if color_name else None, view
    # Format B: BELLA_+_CANVAS_3001Y_Ash_Front_High - style number somewhere in middle
    if style_str in parts:
        idx = parts.index(style_str)
        # View is last part or last two (Front_High -> front)
        last = parts[-1].lower()
        if last in ('front', 'back', 'side'):
            view = last
        elif last == 'high' and len(parts) >= 2 and parts[-2].lower() == 'front':
            view = 'front'
        elif last == 'high' and len(parts) >= 2 and parts[-2].lower() == 'back':
            view = 'back'
        else:
            return None, None
        color_parts = parts[idx + 1:-1] if last != 'high' else parts[idx + 1:-2]
        color_name = ' '.join(color_parts).title()
        return color_name if color_name else None, view
    return None, None


def discover_colors_from_mockup_folder(app, style_number):
    """
    Scan uploads/mockups/{style_number}/ for image files and return unique colors with their mockup URLs.
    Supports formats: 3001_Aqua_front.jpg and BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg
    Returns list of dicts:
    [{'color_name': 'Aqua', 'front_image': url or None, 'back_image': url or None, 'inventory': {}}, ...]
    """
    colors_seen = {}
    for names in _style_index(app, style_number).listings:
        for ext in MOCKUP_EXTENSIONS:
            for name in names:
                if not name.lower().endswith(ext):
                    continue
                color_name, view = _parse_mockup_filename(style_number, name[: -len(ext)])
                if not color_name or not view:
                    continue
                rel = f"{style_number}/{name}"
                url = _mockup_url(app, rel)
                if color_name not in colors_seen:
                    colors_seen[color_name] = {'color_name': color_name, 'color_hex': None, 'front_image': None, 'back_image': None, 'front_image_url': None, 'back_image_url': None, 'inventory': {}}
                if view == 'front':
                    colors_seen[color_name]['front_image'] = url
                    colors_seen[color_name]['front_image_url'] = url
                elif view == 'back':
                    colors_seen[color_name]['back_image'] = url
                    colors_seen[color_name]['back_image_url'] = url
    return list(colors_seen.values())


SHOP_PLACEHOLDER_IMAGE = '/static/img/placeholder-product.svg'


def _shop_inventory_for_variant(raw_inventory, shop_sizes, listed_sizes):
    from utils.stock import inventory_for_display, _qty_int
    inventory = inventory_for_display(raw_inventory, shop_sizes)
    if not listed_sizes and inventory and all(_qty_int(qty) <= 0 for qty in inventory.values()):
        return {}
    return inventory


def get_color_variants_data_for_product(product, app):
    """
    Build color_variants_data for product detail/customize pages.
    Merges DB variants with mockup folder, no duplicates.
    Returns list of dicts: color_name, color_hex, front_image, back_image, inventory.
    """
    from utils.json_fields import parse_json_list
    from utils.sizes import shop_sizes_for_product
    listed_sizes = parse_json_list(getattr(product, 'available_sizes', None))
    raw_variants = list(getattr(product, 'color_variants', []) or [])
    shop_sizes = shop_sizes_for_product(product, raw_variants)
    color_variants_data = []
    seen_colors = set()
    for variant in raw_variants:
        inventory = _shop_inventory_for_variant(variant.size_inventory, shop_sizes, listed_sizes)
        front_image = get_mockup_url_for_variant(product, variant, 'front', app) or variant.front_image_url
        back_image = get_mockup_url_for_variant(product, variant, 'back', app) or variant.back_image_url
        color_variants_data.append({
            'color_name': variant.color_name,
            'color_hex': variant.color_hex,
            'front_image': front_image,
            'back_image': back_image,
            'inventory': inventory
        })
        seen_colors.add(variant.color_name)
    for extra in discover_colors_from_mockup_folder(app, product.style_number):
        if extra['color_name'] in seen_colors or not (extra.get('front_image') or extra.get('back_image')):
            continue
        seen_colors.add(extra['color_name'])
        color_variants_data.append({
            'color_name': extra['color_name'],
            'color_hex': extra.get('color_hex'),
            'front_image': extra.get('front_image_url') or extra.get('front_image'),
            'back_image': extra.get('back_image_url') or extra.get('back_image'),
            'inventory': _shop_inventory_for_variant(extra.get('inventory', {}), shop_sizes, listed_sizes)
        })
    for color_name in parse_json_list(getattr(product, 'available_colors', None)):
        if color_name in seen_colors:
            continue
        seen_colors.add(color_name)
        color_variants_data.append({
            'color_name': color_name,
            'color_hex': None,
            'front_image': None,
            'back_image': None,
            'inventory': {}
        })
    return color_variants_data


def ensure_variant_mockup_urls(app):
    """
    Fill missing front_image_url/back_image_url on ProductColorVariant from mockup folder.
    Also CREATE variants for colors that exist in mockup folder but not in DB.
    Call after sync so customers see mockup images when selecting colors.
    """
    from models import Product, ProductColorVariant, db
    import json

    for product in Product.query.filter_by(is_active=True).all():
        existing_colors = {v.color_name for v in ProductColorVariant.query.filter_by(product_id=product.id).all()}
        # 1. Fill missing URLs on existing variants
        for v in ProductColorVariant.query.filter_by(product_id=product.id).all():
            if not v.front_image_url:
                rel = _find_mockup_file(app, product.style_number, v.color_name, 'front')
                if rel:
                    v.front_image_url = _mockup_url(app, rel)
            if not v.back_image_url:
                rel = _find_mockup_file(app, product.style_number, v.color_name, 'back')
                if rel:
                    v.back_image_url = _mockup_url(app, rel)

        # 2. Create variants for mockup folder colors not yet in DB
        for c in discover_colors_from_mockup_folder(app, product.style_number):
            if c['color_name'] in existing_colors or not (c.get('front_image') or c.get('back_image')):
                continue
            existing_colors.add(c['color_name'])
            sizes = []
            try:
                sizes = json.loads(product.available_sizes) if product.available_sizes else ['S', 'M', 'L', 'XL']
            except (TypeError, ValueError):
                sizes = ['S', 'M', 'L', 'XL']
            inv = json.dumps({s: 0 for s in sizes})
            db.session.add(ProductColorVariant(
                product_id=product.id,
                color_name=c['color_name'],
                front_image_url=c.get('front_image_url') or c.get('front_image'),
                back_image_url=c.get('back_image_url') or c.get('back_image'),
                size_inventory=inv
            ))


def get_carousel_colors_for_product(product, app, allowed_colors=None, variants=None):
    """
    Build carousel color list for a product, merging DB variants with mockup folder.
    Returns list of dicts with color_name and front_image_url for shop carousel.
    Ensures ALL colors from uploads/mockups show in carousel with correct images.
    allowed_colors: optional set to filter (e.g. for collection restrictions)
    variants: optional pre-fetched colour variants for this product.

    `Product.color_variants` is a dynamic relationship, so iterating it runs a
    SELECT. On a page rendering the whole catalogue that is one query per
    product. A caller with many products can fetch every variant in one query
    and pass this product's share in. It cannot be solved with eager loading:
    SQLAlchemy rejects selectinload on a dynamic relationship outright.
    """
    from utils.json_fields import parse_json_list

    result = []
    seen = set()
    pending_names = []

    if variants is None:
        variants = getattr(product, 'color_variants', []) or []

    # 1. DB variants - prefer mockup folder URL over DB URL (DB may have old S&S CDN links)
    for v in variants:
        if v.color_name in seen:
            continue
        if allowed_colors and v.color_name not in allowed_colors:
            continue
        # Try mockup folder FIRST
        rel = _find_mockup_file(app, product.style_number, v.color_name, 'front')
        if rel:
            url = _mockup_url(app, rel)
        else:
            raw = v.front_image_url or ''
            # Fix bare relative paths stored without /static/ prefix
            if raw and not raw.startswith('http') and not raw.startswith('/'):
                raw = '/static/' + raw
            url = raw or None
        if url:
            seen.add(v.color_name)
            result.append({'color_name': v.color_name, 'front_image_url': url})
        else:
            pending_names.append(v.color_name)

    # 2. Colors from mockup folder not yet in result
    for c in discover_colors_from_mockup_folder(app, product.style_number):
        if c['color_name'] in seen:
            continue
        if allowed_colors and c['color_name'] not in allowed_colors:
            continue
        if not c.get('front_image') and not c.get('front_image_url'):
            continue
        seen.add(c['color_name'])
        url = c.get('front_image_url') or c.get('front_image')
        result.append({'color_name': c['color_name'], 'front_image_url': url})

    # 3. Colours that exist in the catalog but have no photo yet still count,
    # so the shop card does not read "0 colors" while the customizer shows 35.
    for name in pending_names + parse_json_list(getattr(product, 'available_colors', None)):
        if not name or name in seen:
            continue
        if allowed_colors and name not in allowed_colors:
            continue
        seen.add(name)
        result.append({'color_name': name, 'front_image_url': SHOP_PLACEHOLDER_IMAGE})

    return result


def _hex_luminance(hex_color):
    """0–255 perceived brightness, or None if the hex is unusable."""
    h = str(hex_color or '').strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(ch * 2 for ch in h)
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


_LIGHT_NAME_SCORES = (
    ('white', 252),
    ('ivory', 246),
    ('snow', 248),
    ('cream', 242),
    ('natural', 238),
    ('bone', 232),
    ('oatmeal', 224),
    ('sand', 210),
    ('ice', 220),
    ('ash', 198),
    ('silver', 190),
    ('light', 186),
    ('heather', 168),
    ('grey', 150),
    ('gray', 150),
)


def _name_lightness(color_name):
    key = str(color_name or '').lower()
    score = 80
    for token, value in _LIGHT_NAME_SCORES:
        if token in key:
            score = max(score, value)
    return score


def lightest_front_mockup_url(variants):
    """Front mockup URL for the lightest color that actually has a photo."""
    best_url = None
    best_score = -1
    for variant in variants or []:
        url = (getattr(variant, 'front_image_url', None) or '').strip()
        if not url:
            continue
        lum = _hex_luminance(getattr(variant, 'color_hex', None))
        if lum is None:
            lum = _name_lightness(getattr(variant, 'color_name', ''))
        if lum > best_score:
            best_score = lum
            best_url = url
    return best_url


def sorted_front_mockup_urls(variants):
    """
    Return all variant front_image_urls sorted lightest-first (deduped).
    Use as a JS fallback list so if the first image 404s the next is tried.
    """
    scored = []
    seen = set()
    for variant in variants or []:
        url = (getattr(variant, 'front_image_url', None) or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        lum = _hex_luminance(getattr(variant, 'color_hex', None))
        if lum is None:
            lum = _name_lightness(getattr(variant, 'color_name', ''))
        scored.append((lum, url))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [url for _, url in scored]


def get_first_shop_image_url(product, app, carousel=None):
    """
    Get a single image URL for shop display when carousel is empty.
    Returns first available front mockup from folder or DB, else None.

    Pass `carousel` when the caller has already built the colour list. /shop/
    called this straight after get_carousel_colors_for_product() for every
    product, so the whole list was being built twice per row.
    """
    colors = carousel if carousel is not None else get_carousel_colors_for_product(product, app)
    for color in colors or []:
        url = (color.get('front_image_url') or '').strip()
        if url and SHOP_PLACEHOLDER_IMAGE not in url:
            return url
    if colors:
        return colors[0].get('front_image_url')
    # Fallback: scan folder for any front image
    discovered = discover_colors_from_mockup_folder(app, product.style_number)
    for c in discovered:
        url = c.get('front_image_url') or c.get('front_image')
        if url:
            return url
    # Last resort: check static/images/products/ with brand-prefix stripped
    # e.g. BC3001 → 3001, STTU755 → 755
    import re as _re
    style = (getattr(product, 'style_number', None) or '').strip()
    if style:
        style_bare = _re.sub(r'^[A-Za-z+& ]+', '', style)
        for candidate in dict.fromkeys([style_bare, style]):
            if not candidate:
                continue
            folder_path = os.path.join(app.root_path, 'static', 'images', 'products', candidate)
            if os.path.isdir(folder_path):
                fronts = [f for f in os.listdir(folder_path) if '_front.' in f.lower()]
                if fronts:
                    return f'/static/images/products/{candidate}/{fronts[0]}'
    return None


def create_products_from_mockup_folders(app):
    """
    Create Product + ProductColorVariant for each style folder in uploads/mockups
    that doesn't have a product yet. Returns count of products created.
    """
    from pathlib import Path
    from models import db, Product, ProductColorVariant
    import json
    import os

    mockup_styles = set()
    for mockup_dir in _mockup_dirs(app):
        if not mockup_dir or not os.path.isdir(mockup_dir):
            continue
        for p in Path(mockup_dir).iterdir():
            if p.is_dir() and not p.name.startswith('.'):
                mockup_styles.add(p.name)

    created = 0
    for style_num in sorted(mockup_styles):
        if Product.query.filter_by(style_number=style_num).first():
            continue
        colors_data = discover_colors_from_mockup_folder(app, style_num)
        if not colors_data:
            continue
        color_names = [c['color_name'] for c in colors_data]
        product = Product(
            style_number=style_num,
            name=f"Bella+Canvas Style {style_num}",
            category="Tee",
            description="",
            base_price=25.00,
            wholesale_cost=10.00,
            is_active=True,
            available_sizes=json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL"]),
            available_colors=json.dumps(color_names),
            brand="Bella+Canvas"
        )
        db.session.add(product)
        db.session.flush()
        for c in colors_data:
            inv = json.dumps({s: 0 for s in ["XS", "S", "M", "L", "XL", "2XL", "3XL"]})
            db.session.add(ProductColorVariant(
                product_id=product.id,
                color_name=c['color_name'],
                front_image_url=c.get('front_image_url') or c.get('front_image'),
                back_image_url=c.get('back_image_url') or c.get('back_image'),
                size_inventory=inv
            ))
        created += 1
    return created
