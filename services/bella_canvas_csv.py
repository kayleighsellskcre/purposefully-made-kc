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


# SanMar CDN base URL for images not already full URLs
_CDN_BASE = 'https://cdnm.sanmar.com/catalog/images'


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


def _front_image_url(row: dict) -> str:
    """
    Return a flat/ghost product image URL — no model photos.
    Priority:
      1. COLOR_PRODUCT_IMAGE filename → cdnm.sanmar.com/catalog/images/{file}
         (color-specific flat shirt image from the SDL ZIP)
      2. PRODUCT_IMAGE filename → same base (generic flat, not color-specific)
    Falls back to FRONT_MODEL_IMAGE_URL only if nothing else is available.
    """
    # Color-specific flat image (best option)
    color_img = row.get('COLOR_PRODUCT_IMAGE', '').strip()
    if color_img:
        return f'{_CDN_BASE}/{color_img}'

    # Generic flat product image (same for all colors of a style)
    product_img = row.get('PRODUCT_IMAGE', '').strip()
    if product_img:
        return f'{_CDN_BASE}/{product_img}'

    # Last resort: model image
    url = row.get('FRONT_MODEL_IMAGE_URL', '').strip()
    if url and url.startswith('http'):
        return url

    return ''


def _back_image_url(row: dict) -> str:
    """
    Derive the back image URL from the front image filename.
    SanMar CDN naming: BC3483_black_model_front.jpg → BC3483_black_model_back.jpg
    """
    color_img = row.get('COLOR_PRODUCT_IMAGE', '').strip()
    if color_img and '_front' in color_img.lower():
        back_img = color_img.lower().replace('_front', '_back')
        return f'{_CDN_BASE}/{back_img}'
    return ''


def _swatch_url(row: dict) -> str:
    """Return the color swatch image URL."""
    swatch = row.get('COLOR_SQUARE_IMAGE', '').strip()
    if swatch:
        return f'{_CDN_BASE}/{swatch}'
    return ''


def _spec_sheet_url(row: dict) -> str:
    """Return the spec sheet PDF URL from SanMar's CDN."""
    spec = row.get('PRODUCT_MEASUREMENTS', '').strip()
    if spec and spec.lower().endswith('.pdf'):
        return f'https://cdnm.sanmar.com/imglib/mresjpg/specsheet/pdf/specsheet/{spec}'
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
                'color_hex':       swatch_url,   # stored in color_hex field as swatch URL
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
