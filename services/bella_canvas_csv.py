"""
Parser for the BellaCanvas SDL (Static Data Library) CSV export from SanMar.

CSV columns (from BellaCanvasData_164838.csv):
  UNIQUE_KEY, PRODUCT_TITLE, PRODUCT_DESCRIPTION, STYLE#, AVAILABLE_SIZES,
  BRAND_LOGO_IMAGE, THUMBNAIL_IMAGE, COLOR_SWATCH_IMAGE, PRODUCT_IMAGE,
  SPEC_SHEET, PRICE_TEXT, SUGGESTED_PRICE, CATEGORY_NAME, SUBCATEGORY_NAME,
  COLOR_NAME, COLOR_SQUARE_IMAGE, COLOR_PRODUCT_IMAGE,
  COLOR_PRODUCT_IMAGE_THUMBNAIL, SIZE, PIECE_WEIGHT, PIECE_PRICE,
  DOZENS_PRICE, CASE_PRICE, PRICE_GROUP, CASE_SIZE, INVENTORY_KEY,
  SIZE_INDEX, SANMAR_MAINFRAME_COLOR, MILL, PRODUCT_STATUS,
  COMPANION_STYLE, MSRP, MAP_PRICING, FRONT_MODEL_IMAGE_URL,
  PRODUCT_MEASUREMENTS

Each row = one style + color + size combination.
We group by STYLE# → colors → sizes.
"""

import csv
import json
import io
from collections import defaultdict


def _safe_float(value, default=0.0) -> float:
    try:
        return float(str(value).strip()) if value else default
    except (ValueError, TypeError):
        return default


def _extract_fabric(description: str) -> str:
    """Pull the fabric/weight line out of the product description."""
    for line in description.replace('. ', '\n').split('\n'):
        line = line.strip()
        low = line.lower()
        if any(w in low for w in ('ounce', 'cotton', 'polyester', 'spun', 'airlume', 'fabric', 'blend')):
            return line
    return ''


def _cdn_img_base(row: dict) -> str:
    """
    Extract the correct CDN base path from FRONT_MODEL_IMAGE_URL.
    e.g. https://cdnm.sanmar.com/imglib/mresjpg/2026/f2/BC3483_black_model_front.jpg
      → https://cdnm.sanmar.com/imglib/mresjpg/2026/f2/
    The year/folder changes annually, so we always derive it from the CSV.
    """
    url = row.get('FRONT_MODEL_IMAGE_URL', '').strip()
    if url and '/' in url:
        return url[:url.rfind('/') + 1]
    return 'https://cdnm.sanmar.com/imglib/mresjpg/2026/f2/'


def _front_image_url(row: dict) -> str:
    """
    Return the best available flat/no-model front image URL.

    Priority:
    1. COLOR_PRODUCT_IMAGE with '_flat_front' in name → real CDN flat image (no person)
    2. Local static file uploaded by user: /static/sanmar/front/{PRODUCT_IMAGE}
       (user copies images from the SanMar SDL ZIP into static/sanmar/front/)
    3. Empty string — admin must set manually
    """
    color_img = row.get('COLOR_PRODUCT_IMAGE', '').strip()
    if color_img and '_flat_front' in color_img.lower():
        return _cdn_img_base(row) + color_img

    # Fallback to locally hosted image from SDL ZIP
    product_img = row.get('PRODUCT_IMAGE', '').strip()
    if product_img:
        return '/static/sanmar/front/' + product_img

    return ''


def _back_image_url(row: dict) -> str:
    """
    Return the best available flat/no-model back image URL.

    Priority:
    1. Replace '_flat_front' with '_flat_back' in COLOR_PRODUCT_IMAGE → CDN back flat image
    2. Local static file: /static/sanmar/back/{PRODUCT_IMAGE}
    """
    color_img = row.get('COLOR_PRODUCT_IMAGE', '').strip()
    if color_img and '_flat_front' in color_img.lower():
        back_img = color_img.lower().replace('_flat_front', '_flat_back')
        return _cdn_img_base(row) + back_img

    # Fallback to locally hosted back image from SDL ZIP
    product_img = row.get('PRODUCT_IMAGE', '').strip()
    if product_img:
        name_no_ext = product_img.rsplit('.', 1)[0]
        return '/static/sanmar/back/' + name_no_ext + 'B.jpg'

    return ''


def _swatch_url(row: dict) -> str:
    """Return the color square swatch URL — derived from the same CDN base as product images."""
    swatch = row.get('COLOR_SQUARE_IMAGE', '').strip()
    if swatch:
        return _cdn_img_base(row) + swatch
    return ''


def _spec_sheet_url(row: dict) -> str:
    """Return the spec sheet PDF URL. Uses the SPEC_SHEET column from the SDL CSV."""
    spec = (row.get('SPEC_SHEET', '') or row.get('PRODUCT_MEASUREMENTS', '')).strip()
    if spec and spec.lower().endswith('.pdf'):
        return 'https://cdnm.sanmar.com/imglib/mresjpg/specsheet/pdf/specsheet/' + spec
    return ''


def parse_csv(source) -> list[dict]:
    """
    Parse a BellaCanvas SDL CSV.

    source: file path (str) OR a file-like object (e.g. Flask request.files['file'])

    Returns a list of product dicts ready to be upserted into the database.
    Each dict shape:
      style_number, name, brand, description, fabric_details,
      base_price, wholesale_cost, available_sizes (JSON str),
      available_colors (JSON str), category, is_active,
      front_mockup_template, color_variants (list of dicts)
    """
    if hasattr(source, 'read'):
        raw = source.read()
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
    else:
        with open(source, 'r', encoding='utf-8-sig', errors='replace', newline='') as fh:
            rows = list(csv.DictReader(fh))

    # --- Group rows by style number ---
    # styles[style] = { 'meta': first_row, 'sizes': {size: size_index}, 'colors': {color: [rows]} }
    styles: dict = {}

    for row in rows:
        style = row.get('STYLE#', '').strip()
        if not style:
            continue
        color = row.get('COLOR_NAME', '').strip()
        size  = row.get('SIZE', '').strip()

        if style not in styles:
            styles[style] = {'meta': row, 'sizes': {}, 'colors': defaultdict(list)}

        sd = styles[style]
        if size and size not in sd['sizes']:
            try:
                sd['sizes'][size] = int(row.get('SIZE_INDEX', 999))
            except (ValueError, TypeError):
                sd['sizes'][size] = 999

        if color:
            sd['colors'][color].append(row)

    # --- Build product dicts ---
    products = []

    for style, sd in styles.items():
        meta    = sd['meta']
        colors  = sd['colors']

        # Sizes sorted by SIZE_INDEX
        all_sizes = sorted(sd['sizes'].keys(), key=lambda s: sd['sizes'][s])

        piece_price     = _safe_float(meta.get('PIECE_PRICE'))
        suggested_price = _safe_float(meta.get('SUGGESTED_PRICE') or meta.get('MSRP'))

        # For blank tees from a print shop, markup ~3.5× wholesale is a reasonable start.
        # Admin can adjust after import. Never write 0.
        if suggested_price > 0:
            retail_start = round(suggested_price * 2.0, 2)  # SDL price × 2 = print shop retail
        elif piece_price > 0:
            retail_start = round(piece_price * 3.5, 2)
        else:
            retail_start = 0.0

        description = meta.get('PRODUCT_DESCRIPTION', '').strip()
        status      = meta.get('PRODUCT_STATUS', '').strip().lower()
        category    = (meta.get('CATEGORY_NAME', '') or 'T-Shirts').strip()

        # Build color variant list
        color_variant_list = []
        all_color_names    = []

        for color_name, color_rows in colors.items():
            if not color_name:
                continue
            first = color_rows[0]
            front_url = _front_image_url(first)
            back_url = _back_image_url(first)
            swatch_url = _swatch_url(first)

            all_color_names.append(color_name)
            color_variant_list.append({
                'color_name':      color_name,
                'front_image_url': front_url,
                'back_image_url':  back_url,
                'side_image_url':  '',
                'color_swatch_url': swatch_url,
                'color_hex':       '',
                'size_inventory':  {},
            })

        if not color_variant_list:
            continue

        products.append({
            'style_number':          style,
            'name':                  meta.get('PRODUCT_TITLE', '').strip(),
            'brand':                 'Bella+Canvas',
            'description':           description,
            'fabric_details':        _extract_fabric(description),
            'base_price':            retail_start,
            'wholesale_cost':        piece_price,
            'available_sizes':       json.dumps(all_sizes),
            'available_colors':      json.dumps(all_color_names),
            'category':              category,
            'is_active':             status not in ('discontinued', 'closeout'),
            'front_mockup_template': color_variant_list[0]['front_image_url'],
            'back_mockup_template':  color_variant_list[0]['back_image_url'],
            'spec_sheet_url':        _spec_sheet_url(meta),
            'color_variants':        color_variant_list,
        })

    return products
