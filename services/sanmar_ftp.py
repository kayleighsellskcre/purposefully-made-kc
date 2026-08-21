"""
services/sanmar_ftp.py

SanMar SFTP sync pipeline — downloads sanmar_dip.txt (Daily Inventory & Pricing),
parses it, and upserts Product + ProductColorVariant rows into the Railway DB.

Required environment variables:
  SANMAR_FTP_HOST        = ftp.sanmar.com
  SANMAR_FTP_PORT        = 2200
  SANMAR_FTP_USER        = <from SanMar>
  SANMAR_FTP_PASSWORD    = <from SanMar>
  DATABASE_URL           = <Railway postgres URL>

Optional:
  SANMAR_DIP_REMOTE_PATH = /sanmar_dip.txt        (default)
  SANMAR_DIP_LOCAL_PATH  = /tmp/sanmar_dip.txt    (default)
"""

import csv
import json
import math
import os
import sys
from datetime import date, datetime

import paramiko

# ---------------------------------------------------------------------------
# Restricted brands — per SanMar decorator agreement, these cannot appear
# on third-party / decorator storefronts.
# ---------------------------------------------------------------------------

_RESTRICTED_BRAND_KEYWORDS = frozenset({
    'nike', 'north face', 'tnf', 'carhartt', 'ogio',
    'travismathew', 'callaway', 'eddie bauer', 'red house', 'redhouse',
})

# Style-number prefixes for the restricted brands
_RESTRICTED_STYLE_PREFIXES = ('NK', 'NKDH', 'NF0', 'CT', 'OG')


def _is_restricted(style: str, brand_name: str) -> bool:
    s = style.upper().strip()
    for prefix in _RESTRICTED_STYLE_PREFIXES:
        if s.startswith(prefix):
            return True
    bn = (brand_name or '').lower()
    return any(kw in bn for kw in _RESTRICTED_BRAND_KEYWORDS)


# ---------------------------------------------------------------------------
# Curated style key set
# ---------------------------------------------------------------------------

def _get_curated_style_keys() -> set[str]:
    """Normalized style keys for all brands in sanmar_catalog.CURATED_BRANDS."""
    try:
        from services.sanmar_catalog import CURATED_BRANDS
        from services.sanmar_api import normalize_style_key
        keys: set[str] = set()
        for brand in CURATED_BRANDS:
            for s in brand.get('styles', []):
                keys.add(normalize_style_key(s))
        return keys
    except Exception as exc:
        print(f'[SanMarFTP] Could not load CURATED_BRANDS: {exc}', file=sys.stderr)
        return set()


# ---------------------------------------------------------------------------
# SFTP download
# ---------------------------------------------------------------------------

def download_dip_file(local_path: str | None = None) -> str:
    """
    Download sanmar_dip.txt from SanMar's SFTP server.
    Returns the local file path.  Raises on failure.
    """
    host     = os.getenv('SANMAR_FTP_HOST', 'ftp.sanmar.com')
    port     = int(os.getenv('SANMAR_FTP_PORT', '2200'))
    user     = os.getenv('SANMAR_FTP_USER', '')
    password = os.getenv('SANMAR_FTP_PASSWORD', '')
    remote   = os.getenv('SANMAR_DIP_REMOTE_PATH', '/sanmar_dip.txt')

    if not user or not password:
        raise OSError(
            'SANMAR_FTP_USER and SANMAR_FTP_PASSWORD must be set in environment variables.'
        )

    if local_path is None:
        local_path = os.getenv('SANMAR_DIP_LOCAL_PATH', '/tmp/sanmar_dip.txt')

    print(f'[SanMarFTP] Connecting {host}:{port} …', file=sys.stderr, flush=True)
    transport = paramiko.Transport((host, port))
    try:
        transport.connect(username=user, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            try:
                attrs = sftp.stat(remote)
                mb = attrs.st_size / (1024 * 1024)
                print(f'[SanMarFTP] Remote file: {mb:.1f} MB — downloading …',
                      file=sys.stderr, flush=True)
            except Exception:
                pass
            sftp.get(remote, local_path)
        finally:
            sftp.close()
    finally:
        transport.close()

    print(f'[SanMarFTP] Saved to {local_path}', file=sys.stderr, flush=True)
    return local_path


# ---------------------------------------------------------------------------
# dip.txt parser
# ---------------------------------------------------------------------------

# Maps raw column header variants → canonical name used in code below
_COL_ALIASES: dict[str, str] = {
    # Style
    'STYLE#': 'STYLE', 'STYLE_NUMBER': 'STYLE', 'STYLE': 'STYLE',
    # Color
    'CATALOG_COLOR': 'CATALOG_COLOR', 'CATALOG COLOR': 'CATALOG_COLOR',
    'COLOR_NAME':    'COLOR_NAME',    'COLOR NAME':    'COLOR_NAME',
    'COLOR HEX':     'COLOR_HEX',     'COLOR_HEX':     'COLOR_HEX',
    # Size / qty
    'SIZE': 'SIZE',
    'QTY': 'QTY', 'QUANTITY': 'QTY', 'INVENTORY_QTY': 'QTY', 'INVENTORY QTY': 'QTY',
    # Pricing
    'PIECE_PRICE':      'PIECE_PRICE',      'PIECE PRICE':      'PIECE_PRICE',
    'CASE_PRICE':       'CASE_PRICE',       'CASE PRICE':       'CASE_PRICE',
    'PIECE_SALE_PRICE': 'PIECE_SALE_PRICE', 'PIECE SALE PRICE': 'PIECE_SALE_PRICE',
    'CASE_SALE_PRICE':  'CASE_SALE_PRICE',  'CASE SALE PRICE':  'CASE_SALE_PRICE',
    'SALE_START_DATE':  'SALE_START_DATE',  'SALE START DATE':  'SALE_START_DATE',
    'SALE_END_DATE':    'SALE_END_DATE',    'SALE END DATE':    'SALE_END_DATE',
    # Images
    'FRONT_MODEL':         'FRONT_MODEL',         'FRONT MODEL':         'FRONT_MODEL',
    'BACK_MODEL':          'BACK_MODEL',           'BACK MODEL':          'BACK_MODEL',
    'FRONT_FLAT':          'FRONT_FLAT',           'FRONT FLAT':          'FRONT_FLAT',
    'BACK_FLAT':           'BACK_FLAT',            'BACK FLAT':           'BACK_FLAT',
    'COLOR_PRODUCT_IMAGE': 'COLOR_PRODUCT_IMAGE',  'COLOR PRODUCT IMAGE': 'COLOR_PRODUCT_IMAGE',
    'COLOR_SQUARE_IMAGE':  'COLOR_SQUARE_IMAGE',   'COLOR SQUARE IMAGE':  'COLOR_SQUARE_IMAGE',
    # Misc
    'UNIQUE_KEY':       'UNIQUE_KEY',  'UNIQUE KEY':   'UNIQUE_KEY',
    'BRAND_NAME':       'BRAND_NAME',  'BRAND NAME':   'BRAND_NAME',
    'PRODUCT_TITLE':    'PRODUCT_TITLE', 'PRODUCT TITLE': 'PRODUCT_TITLE',
    'DISCONTINUED_CODE':'DISCONTINUED_CODE', 'DISCONTINUED CODE': 'DISCONTINUED_CODE',
    'INVENTORY_KEY':    'INVENTORY_KEY',
    'SIZE_INDEX':       'SIZE_INDEX',
}


def _sniff_delimiter(line: str) -> str:
    """Pick the delimiter that appears most on the header line."""
    return max(('|', '\t', ','), key=lambda d: line.count(d))


def parse_dip_file(
    local_path: str,
    curated_styles: set[str] | None = None,
) -> list[dict]:
    """
    Parse sanmar_dip.txt and return a list of style/color group dicts.

    Each dict:
      style, style_key, catalog_color, color_name, brand_name, product_title,
      piece_price, sale_price, sale_active,
      front_image, back_image, color_swatch, color_product_image, color_hex,
      sizes: {size_label: qty}

    curated_styles: if provided, only rows whose normalize_style_key() is in the
                    set are included.  Pass None to parse the whole catalog.
    Skips discontinued rows (discontinued_code == 'S', qty == 0).
    Skips restricted brand styles.
    """
    from services.sanmar_api import normalize_style_key, normalize_size

    today = date.today()
    groups: dict[str, dict] = {}

    with open(local_path, encoding='utf-8', errors='replace', newline='') as fh:
        first_line = fh.readline()
        delimiter  = _sniff_delimiter(first_line)
        fh.seek(0)

        reader = csv.DictReader(fh, delimiter=delimiter)
        raw_fields = reader.fieldnames or []

        # Build raw_header → canonical lookup (strip + upper)
        col_map: dict[str, str] = {}
        for f in raw_fields:
            canon = _COL_ALIASES.get(f.strip().upper(), f.strip().upper())
            col_map[f] = canon

        def g(row: dict, canon: str, default: str = '') -> str:
            for raw, c in col_map.items():
                if c == canon:
                    return (row.get(raw) or '').strip()
            return default

        row_count = 0
        for row in reader:
            row_count += 1

            style = g(row, 'STYLE')
            if not style:
                continue

            style_key = normalize_style_key(style)

            # Curated filter
            if curated_styles is not None and style_key not in curated_styles:
                continue

            brand_name = g(row, 'BRAND_NAME')

            # Brand restriction check
            if _is_restricted(style, brand_name):
                continue

            # Skip discontinued + out of stock
            disc = g(row, 'DISCONTINUED_CODE').upper()
            try:
                qty = int(float(g(row, 'QTY') or '0'))
            except (ValueError, TypeError):
                qty = 0
            if disc == 'S' and qty == 0:
                continue

            catalog_color = g(row, 'CATALOG_COLOR') or g(row, 'COLOR_NAME')
            color_name    = g(row, 'COLOR_NAME') or catalog_color
            size          = normalize_size(g(row, 'SIZE'))

            group_key = f'{style}||{catalog_color}'

            # Pricing
            try:
                piece_price = float(g(row, 'PIECE_PRICE') or '0')
            except ValueError:
                piece_price = 0.0

            sale_price  = 0.0
            sale_active = False
            try:
                sp = float(g(row, 'PIECE_SALE_PRICE') or '0')
                if sp > 0:
                    start_s = g(row, 'SALE_START_DATE')
                    end_s   = g(row, 'SALE_END_DATE')
                    fmt     = '%m/%d/%Y'
                    start_d = datetime.strptime(start_s, fmt).date() if start_s else None
                    end_d   = datetime.strptime(end_s,   fmt).date() if end_s   else None
                    if (start_d is None or start_d <= today) and \
                       (end_d   is None or end_d   >= today):
                        sale_price  = sp
                        sale_active = True
            except (ValueError, TypeError):
                pass

            if group_key not in groups:
                groups[group_key] = {
                    'style':               style,
                    'style_key':           style_key,
                    'catalog_color':       catalog_color,
                    'color_name':          color_name,
                    'brand_name':          brand_name,
                    'product_title':       g(row, 'PRODUCT_TITLE'),
                    'piece_price':         piece_price,
                    'sale_price':          sale_price,
                    'sale_active':         sale_active,
                    'front_image':         g(row, 'FRONT_MODEL') or g(row, 'FRONT_FLAT'),
                    'back_image':          g(row, 'BACK_MODEL')  or g(row, 'BACK_FLAT'),
                    'color_swatch':        g(row, 'COLOR_SQUARE_IMAGE'),
                    'color_product_image': g(row, 'COLOR_PRODUCT_IMAGE'),
                    'color_hex':           g(row, 'COLOR_HEX'),
                    'sizes':               {},
                }

            grp = groups[group_key]

            # Update price/sale if not yet set
            if piece_price and not grp['piece_price']:
                grp['piece_price'] = piece_price
            if sale_active and not grp['sale_active']:
                grp['sale_price']  = sale_price
                grp['sale_active'] = True

            # Accumulate size inventory
            if size:
                grp['sizes'][size] = max(grp['sizes'].get(size, 0), qty)

    all_entries = list(groups.values())
    print(
        f'[SanMarFTP] Parsed {row_count:,} rows → {len(all_entries):,} style/color groups.',
        file=sys.stderr, flush=True,
    )
    return all_entries


# ---------------------------------------------------------------------------
# Helpers for upsert
# ---------------------------------------------------------------------------

def _effective_wholesale(entry: dict) -> float:
    """Use sale price when it's active and actually cheaper."""
    if entry['sale_active'] and 0 < entry['sale_price'] < entry['piece_price']:
        return entry['sale_price']
    return entry['piece_price']


def _brand_display_name(style_key: str, dip_brand: str) -> str:
    """Map style key back to our curated brand display name; fall back to dip_brand."""
    try:
        from services.sanmar_catalog import CURATED_BRANDS
        from services.sanmar_api import normalize_style_key
        for brand in CURATED_BRANDS:
            for s in brand.get('styles', []):
                if normalize_style_key(s) == style_key:
                    return brand['name']
    except Exception:
        pass
    return dip_brand or 'SanMar'


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def upsert_from_dip(entries: list[dict], app=None) -> tuple[int, int, int]:
    """
    Upsert Product + ProductColorVariant rows from parsed dip entries.

    Returns (created, updated, skipped) counts.
    app: Flask app instance (for app context).  Imported from app.py if None.
    """
    # Group entries by style number
    style_groups: dict[str, list[dict]] = {}
    for entry in entries:
        style_groups.setdefault(entry['style'], []).append(entry)

    if app is None:
        from app import app as flask_app
        app = flask_app

    created = updated = skipped = 0

    with app.app_context():
        from models import db, Product, ProductColorVariant
        from utils.product_filters import infer_age, infer_category, infer_fit
        from utils.sizes import sort_sizes

        for style, color_entries in style_groups.items():
            try:
                # Aggregate product-level data
                all_sizes:  list[str] = []
                all_colors: list[str] = []
                wholesale    = 0.0
                title        = ''
                brand_display = ''

                for e in color_entries:
                    if not title and e['product_title']:
                        title = e['product_title']
                    if not brand_display:
                        brand_display = _brand_display_name(e['style_key'], e['brand_name'])
                    w = _effective_wholesale(e)
                    if w and not wholesale:
                        wholesale = w
                    color = e['catalog_color'] or e['color_name']
                    if color and color not in all_colors:
                        all_colors.append(color)
                    for sz in e['sizes']:
                        if sz and sz not in all_sizes:
                            all_sizes.append(sz)

                retail = (math.ceil(wholesale) + 19) if wholesale else 0.0

                product_name = title or f'{brand_display} {style}'
                if brand_display and brand_display.lower() not in product_name.lower():
                    product_name = f'{brand_display} {product_name}'.strip()

                attrs     = {'name': product_name, 'category': title, 'style_number': style}
                category  = infer_category(attrs)
                age_group = infer_age(attrs)
                fit_type  = infer_fit(attrs)

                product = Product.query.filter_by(style_number=style).first()

                if product is None:
                    product = Product(
                        style_number      = style,
                        name              = product_name,
                        brand             = brand_display,
                        base_price        = retail,
                        wholesale_cost    = round(wholesale, 2),
                        available_sizes   = json.dumps(sort_sizes(all_sizes)),
                        available_colors  = json.dumps(all_colors),
                        category          = category,
                        age_group         = age_group,
                        fit_type          = fit_type,
                        is_active         = True,
                    )
                    db.session.add(product)
                    db.session.flush()   # get product.id before inserting variants
                    created += 1
                else:
                    # Update pricing + sizes; preserve manual name/description edits
                    if retail > 0:
                        product.wholesale_cost = round(wholesale, 2)
                        product.base_price     = retail
                    product.available_sizes  = json.dumps(sort_sizes(all_sizes))
                    product.available_colors = json.dumps(all_colors)
                    product.updated_at       = datetime.utcnow()
                    updated += 1

                # Upsert color variants
                for e in color_entries:
                    color = e['catalog_color'] or e['color_name']
                    if not color:
                        continue

                    variant = ProductColorVariant.query.filter_by(
                        product_id=product.id,
                        color_name=color,
                    ).first()

                    inv_json = json.dumps(e['sizes']) if e['sizes'] else '{}'
                    front  = e['front_image'] or e['color_product_image']
                    back   = e['back_image']
                    swatch = e['color_swatch']
                    hex_   = e['color_hex']

                    if variant is None:
                        variant = ProductColorVariant(
                            product_id      = product.id,
                            color_name      = color,
                            color_hex       = hex_,
                            color_swatch_url= swatch,
                            front_image_url = front,
                            back_image_url  = back,
                            size_inventory  = inv_json,
                            last_synced     = datetime.utcnow(),
                        )
                        db.session.add(variant)
                    else:
                        if front:  variant.front_image_url  = front
                        if back:   variant.back_image_url   = back
                        if swatch: variant.color_swatch_url = swatch
                        if hex_:   variant.color_hex        = hex_
                        variant.size_inventory = inv_json
                        variant.last_synced    = datetime.utcnow()

                db.session.commit()

            except Exception as exc:
                db.session.rollback()
                print(f'[SanMarFTP] Error upserting style {style}: {exc}', file=sys.stderr)
                skipped += 1

    return created, updated, skipped


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def run_dip_sync(
    styles_only: bool = True,
    local_path:  str | None = None,
    keep_file:   bool = False,
    app=None,
) -> dict:
    """
    Full pipeline: download → parse → upsert.

    styles_only: True  → only sync styles listed in sanmar_catalog.CURATED_BRANDS
                 False → sync the entire SanMar catalog
    local_path:  skip download and use an already-downloaded file
    keep_file:   don't delete the local dip.txt after sync
    app:         Flask app for DB context (imported automatically if None)

    Returns a result dict: {ok, created, updated, skipped, groups, elapsed_seconds}
    """
    import time
    t0 = time.time()

    curated = _get_curated_style_keys() if styles_only else None

    # Download (unless caller supplied a local file)
    if local_path is None:
        path = download_dip_file()
    else:
        path = local_path
        print(f'[SanMarFTP] Using local file: {path}', file=sys.stderr, flush=True)

    # Parse
    entries = parse_dip_file(path, curated_styles=curated)

    # Upsert
    created, updated, skipped = upsert_from_dip(entries, app=app)

    elapsed = round(time.time() - t0, 1)

    # Clean up temp file
    if not keep_file and local_path is None:
        try:
            os.unlink(path)
        except OSError:
            pass

    result = {
        'ok':              True,
        'created':         created,
        'updated':         updated,
        'skipped':         skipped,
        'groups':          len(entries),
        'elapsed_seconds': elapsed,
    }
    print(f'[SanMarFTP] Sync complete: {result}', file=sys.stderr, flush=True)
    return result


# ---------------------------------------------------------------------------
# Background thread helper (mirrors inventory_sync pattern)
# ---------------------------------------------------------------------------

def start_dip_sync_thread(app, styles_only: bool = True):
    """
    Run run_dip_sync() in a daemon thread so the HTTP request can return immediately.
    styles_only=True  → only curated brands from sanmar_catalog.CURATED_BRANDS
    styles_only=False → full SanMar catalog
    """
    import threading

    def _run():
        with app.app_context():
            try:
                result = run_dip_sync(styles_only=styles_only, app=app)
                print(f'[SanMarFTP] Background DIP sync finished: {result}',
                      file=sys.stderr, flush=True)
            except Exception as exc:
                print(f'[SanMarFTP] Background DIP sync failed: {exc}',
                      file=sys.stderr, flush=True)

    thread = threading.Thread(target=_run, daemon=True, name='sanmar-dip-sync')
    thread.start()
    return thread
