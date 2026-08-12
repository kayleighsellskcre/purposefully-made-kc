"""
SanMar SOAP Web Service API integration for Bella+Canvas products.

Credentials are read from environment variables:
  SANMAR_CUSTOMER_NUMBER
  SANMAR_USERNAME
  SANMAR_PASSWORD

SOAP endpoint: https://ws.sanmar.com:8080/SanMarWebService/SanMarServicePort
"""

import os
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.error import URLError

# ---------------------------------------------------------------------------
# Bella+Canvas style numbers to sync
# ---------------------------------------------------------------------------

BELLA_CANVAS_STYLES = [
    # Unisex Tees
    '3001C', '3001CVC', '3001U', '3005', '3010',
    '3015', '3021', '3024', '3025', '3051CVC',
    '3055C', '3100', '3413', '3413CVC', '3413S',
    '3415', '3415C', '3480', '3480C', '3485',
    # Women's Tees
    '6004', '6004CVC', '6035', '6400', '6400CVC',
    '6405', '6413', '6413S', '6415', '6435',
    # Youth Tees
    '3001Y', '3001YCVC', '3413Y', '3413YCVC', '3001B',
    # Hoodies & Sweatshirts
    '3739', '3901', '3719', '3729', '3945',
    '7719', '7720', '7729', '7739', '3501CVC',
    # Women's Hoodies
    '7519', '7520', '7529', '7539',
    # Youth Hoodies
    '3719Y', '3729Y', '3739Y',
    # Tank Tops
    '3480', '8803',
    # Long Sleeve
    '3501', '3501CVC', '3501T',
    # Crop Tops
    '6682', '6013',
    # Joggers / Pants
    '3727', '3728', '8822',
    # V-Necks
    '3005', '3415', '6405',
    # Onesies / Baby
    '100B', '100CVC',
]

# De-duplicate while preserving order
_seen = set()
BELLA_CANVAS_STYLES = [s for s in BELLA_CANVAS_STYLES if not (_seen.add(s) or s in _seen)]


# ---------------------------------------------------------------------------
# SOAP helper
# ---------------------------------------------------------------------------

_SOAP_ENDPOINT = 'https://ws.sanmar.com:8080/SanMarWebService/SanMarServicePort'

_SOAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ws="http://www.sanmar.com/webservice">
  <soapenv:Header/>
  <soapenv:Body>
    <ws:getProductInfoAndInventoryByStyleColorAndSize>
      <ws:arg0>
        <ws:style>{style}</ws:style>
        <ws:color>{color}</ws:color>
        <ws:size></ws:size>
        <ws:sanMarCustomerNumber>{customer_number}</ws:sanMarCustomerNumber>
        <ws:sanMarUserName>{username}</ws:sanMarUserName>
        <ws:sanMarUserPassword>{password}</ws:sanMarUserPassword>
      </ws:arg0>
    </ws:getProductInfoAndInventoryByStyleColorAndSize>
  </soapenv:Body>
</soapenv:Envelope>"""


def _soap_request(style: str, color: str = '') -> ET.Element | None:
    """Send a SOAP request for a style+color and return the root XML element, or None on error."""
    customer_number = os.getenv('SANMAR_CUSTOMER_NUMBER', '')
    username = os.getenv('SANMAR_USERNAME', '')
    password = os.getenv('SANMAR_PASSWORD', '')

    body = _SOAP_TEMPLATE.format(
        style=style,
        color=color,
        customer_number=customer_number,
        username=username,
        password=password,
    ).encode('utf-8')

    req = Request(
        _SOAP_ENDPOINT,
        data=body,
        headers={
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': '',
        },
        method='POST',
    )
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return ET.fromstring(raw)
    except (URLError, ET.ParseError) as exc:
        print(f'[SanMarAPI] SOAP error for style={style}: {exc}')
        return None


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

def _ns_find(element: ET.Element, tag: str) -> str:
    """Find a tag anywhere in the subtree, ignoring namespaces. Returns text or ''."""
    for child in element.iter():
        local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if local == tag:
            return (child.text or '').strip()
    return ''


def _parse_product_entry(entry: ET.Element) -> dict:
    """Parse a single productInfo/listResponse element into a flat dict."""
    return {
        'style':        _ns_find(entry, 'style'),
        'color_name':   _ns_find(entry, 'colorName') or _ns_find(entry, 'color'),
        'size':         _ns_find(entry, 'size'),
        'price':        _ns_find(entry, 'piecePrice') or _ns_find(entry, 'price'),
        'title':        _ns_find(entry, 'productTitle') or _ns_find(entry, 'title'),
        'description':  _ns_find(entry, 'productDescription') or _ns_find(entry, 'description'),
        'material':     _ns_find(entry, 'material') or _ns_find(entry, 'fabric'),
        'inventory':    _ns_find(entry, 'qty') or _ns_find(entry, 'inventory'),
        'front_image':  _ns_find(entry, 'frontModel') or _ns_find(entry, 'frontImage'),
        'back_image':   _ns_find(entry, 'backModel')  or _ns_find(entry, 'backImage'),
        'color_hex':    _ns_find(entry, 'colorHex')  or '',
    }


# ---------------------------------------------------------------------------
# Main API class
# ---------------------------------------------------------------------------

class SanMarAPI:
    """Minimal SanMar SOAP client for Bella+Canvas catalog sync."""

    def fetch_style_data(self, style_number: str) -> dict:
        """Fetch all color/size variants for a style and return a structured dict.

        Returns:
            {
              'style': '3001C',
              'title': 'Unisex Jersey Short Sleeve Tee',
              'description': '...',
              'material': '100% combed and ring-spun cotton',
              'color_variants': {
                  'White': {
                      'sizes': ['XS','S','M','L','XL','2XL'],
                      'price': 6.98,
                      'front_image': 'https://...',
                      'back_image':  'https://...',
                      'inventory': {'S': 500, ...},
                  },
                  ...
              }
            }
        """
        root = _soap_request(style_number, color='')
        if root is None:
            return {}

        result: dict = {
            'style': style_number,
            'title': '',
            'description': '',
            'material': '',
            'color_variants': {},
        }

        # Collect all product entries in the response
        entries = []
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local in ('listResponse', 'productInfo', 'return', 'item'):
                parsed = _parse_product_entry(elem)
                if parsed['style'] or parsed['color_name']:
                    entries.append(parsed)

        for entry in entries:
            # Fill top-level fields from first complete entry
            if not result['title'] and entry['title']:
                result['title'] = entry['title']
            if not result['description'] and entry['description']:
                result['description'] = entry['description']
            if not result['material'] and entry['material']:
                result['material'] = entry['material']

            color = entry['color_name']
            if not color:
                continue

            if color not in result['color_variants']:
                result['color_variants'][color] = {
                    'sizes': [],
                    'price': 0.0,
                    'front_image': entry['front_image'],
                    'back_image':  entry['back_image'],
                    'color_hex':   entry['color_hex'],
                    'inventory':   {},
                }

            cv = result['color_variants'][color]
            size = entry['size']
            if size and size not in cv['sizes']:
                cv['sizes'].append(size)

            try:
                price = float(entry['price'])
                if price > 0 and cv['price'] == 0.0:
                    cv['price'] = price
            except (ValueError, TypeError):
                pass

            if size and entry['inventory']:
                try:
                    cv['inventory'][size] = int(entry['inventory'])
                except (ValueError, TypeError):
                    pass

        return result

    def parse_style_to_product(self, style_data: dict) -> dict | None:
        """Convert raw style_data dict into the Product model format used by the app."""
        if not style_data or not style_data.get('style'):
            return None

        style = style_data['style']
        color_variants = style_data.get('color_variants', {})

        # Collect sizes and colors
        all_sizes: list[str] = []
        all_colors: list[str] = list(color_variants.keys())
        base_price = 0.0

        for cv_data in color_variants.values():
            for sz in cv_data.get('sizes', []):
                if sz not in all_sizes:
                    all_sizes.append(sz)
            if not base_price and cv_data.get('price'):
                base_price = cv_data['price']

        if not base_price:
            base_price = 0.0

        # Build color_variants in the app's expected format
        color_variants_list = []
        for color_name, cv_data in color_variants.items():
            color_variants_list.append({
                'color_name':   color_name,
                'front_image':  cv_data.get('front_image', ''),
                'back_image':   cv_data.get('back_image', ''),
                'side_image':   '',
                'color_hex':    cv_data.get('color_hex', ''),
                'size_inventory': cv_data.get('inventory', {}),
                'color_id':     None,
            })

        return {
            'style_number':     style,
            'name':             style_data.get('title') or f'Bella+Canvas {style}',
            'brand':            'Bella+Canvas',
            'description':      style_data.get('description', ''),
            'fabric_details':   style_data.get('material', ''),
            'base_price':       base_price,
            'wholesale_cost':   round(base_price * 0.6, 2) if base_price else 0.0,
            'available_sizes':  ', '.join(all_sizes),
            'available_colors': ', '.join(all_colors),
            'category':         'T-Shirts',  # default; admin can update
            'is_active':        True,
            'front_mockup_template': next(
                (cv['front_image'] for cv in color_variants.values() if cv.get('front_image')), ''
            ),
            'back_mockup_template': next(
                (cv['back_image'] for cv in color_variants.values() if cv.get('back_image')), ''
            ),
            'color_variants':   color_variants_list,
            'api_data':         None,
        }

    def sync_bella_canvas_catalog(self) -> list[dict]:
        """Sync all BELLA_CANVAS_STYLES from SanMar. Returns list of product dicts."""
        products = []
        for style in BELLA_CANVAS_STYLES:
            print(f'[SanMarAPI] Fetching style {style}…')
            try:
                style_data = self.fetch_style_data(style)
                product = self.parse_style_to_product(style_data)
                if product:
                    products.append(product)
            except Exception as exc:
                print(f'[SanMarAPI] Skipping {style}: {exc}')
                continue
        print(f'[SanMarAPI] Sync complete — {len(products)} products fetched.')
        return products
