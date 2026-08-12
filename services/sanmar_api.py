"""
SanMar SOAP Web Service API integration for Bella+Canvas products.

Credentials are read from environment variables:
  SANMAR_CUSTOMER_NUMBER
  SANMAR_USERNAME
  SANMAR_PASSWORD

SOAP endpoint: https://ws.sanmar.com:8080/SanMarWebService/SanMarServicePort
"""

import os
import json
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

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
# Credential helpers
# ---------------------------------------------------------------------------

def get_credentials() -> tuple[str, str, str]:
    """Return (customer_number, username, password) from environment."""
    return (
        os.getenv('SANMAR_CUSTOMER_NUMBER', '').strip(),
        os.getenv('SANMAR_USERNAME', '').strip(),
        os.getenv('SANMAR_PASSWORD', '').strip(),
    )


def check_credentials() -> dict:
    """
    Validate that all three SanMar credentials are set.

    Returns:
        {'ok': True} if all credentials present, or
        {'ok': False, 'missing': ['SANMAR_CUSTOMER_NUMBER', ...]}
    """
    customer_number, username, password = get_credentials()
    missing = []
    if not customer_number:
        missing.append('SANMAR_CUSTOMER_NUMBER')
    if not username:
        missing.append('SANMAR_USERNAME')
    if not password:
        missing.append('SANMAR_PASSWORD')
    if missing:
        return {'ok': False, 'missing': missing}
    return {'ok': True, 'missing': []}


# ---------------------------------------------------------------------------
# SOAP helper
# ---------------------------------------------------------------------------

_SOAP_ENDPOINT = 'https://ws.sanmar.com:8080/SanMarWebService/SanMarProductInfoServicePort'

_SOAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ns2="http://impl.webservice.integration.sanmar.com/">
  <soapenv:Header/>
  <soapenv:Body>
    <ns2:getProductInfoByStyle>
      <arg0>
        <style>{style}</style>
      </arg0>
      <arg1>
        <sanMarCustomerNumber>{customer_number}</sanMarCustomerNumber>
        <sanMarUserName>{username}</sanMarUserName>
        <sanMarUserPassword>{password}</sanMarUserPassword>
      </arg1>
    </ns2:getProductInfoByStyle>
  </soapenv:Body>
</soapenv:Envelope>"""


class SanMarSOAPError(Exception):
    """Raised when SanMar returns a SOAP Fault."""
    pass


class SanMarAuthError(SanMarSOAPError):
    """Raised specifically for authentication failures."""
    pass


def _soap_request(style: str) -> ET.Element:
    """
    Send a SOAP request for a style number.

    Returns the root XML element on success.
    Raises SanMarAuthError for credential failures,
           SanMarSOAPError for other SOAP faults or non-XML responses,
           URLError / HTTPError for network problems.
    """
    import sys
    customer_number, username, password = get_credentials()

    body = _SOAP_TEMPLATE.format(
        style=style,
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

    raw = b''
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except HTTPError as exc:
        raw = exc.read() or b''
    # URLError / OSError propagate to caller

    if not raw:
        raise SanMarSOAPError('SanMar returned an empty response — check the endpoint URL and credentials.')

    # Log first 500 chars for Railway debugging
    preview = raw[:500].decode('utf-8', errors='replace')
    print(f'[SanMarAPI] Raw response preview: {preview}', file=sys.stderr, flush=True)

    # Detect non-XML (HTML error page, plain text, etc.)
    stripped = raw.lstrip()
    if stripped and stripped[0:1] != b'<':
        preview = raw[:300].decode('utf-8', errors='replace').strip()
        raise SanMarSOAPError(
            f'SanMar returned a non-XML response. '
            f'Raw start: {repr(preview)}'
        )

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        preview = raw[:300].decode('utf-8', errors='replace').strip()
        raise SanMarSOAPError(
            f'Could not parse SanMar response as XML ({exc}). '
            f'Raw response start: {repr(preview)}'
        )

    # Check for SOAP Fault
    fault = None
    for elem in root.iter():
        local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if local == 'Fault':
            fault = elem
            break

    if fault is not None:
        faultstring = ''
        for elem in fault.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local in ('faultstring', 'message', 'text'):
                faultstring = (elem.text or '').strip()
                break

        auth_keywords = ('invalid', 'authentication', 'unauthorized', 'credentials',
                         'password', 'username', 'login', 'access denied', 'not authorized')
        if any(kw in faultstring.lower() for kw in auth_keywords):
            raise SanMarAuthError(faultstring or 'Authentication failed')
        raise SanMarSOAPError(faultstring or 'SOAP Fault returned')

    return root


def test_connection() -> dict:
    """
    Test the SanMar connection with a single style (3001C).

    Returns a dict with keys:
      ok (bool), message (str), details (str | None)
    """
    cred_check = check_credentials()
    if not cred_check['ok']:
        missing = ', '.join(cred_check['missing'])
        return {
            'ok': False,
            'message': f'Missing credentials: {missing}',
            'details': (
                f'Add {missing} to your Railway environment variables. '
                'Go to Railway → your project → Variables.'
            ),
        }

    try:
        root = _soap_request('3001C')
        # Count product entries found
        entries = 0
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local in ('listResponse', 'productInfo', 'return', 'item'):
                entries += 1
        if entries > 0:
            return {
                'ok': True,
                'message': f'Connected! SanMar returned {entries} entries for style 3001C.',
                'details': None,
            }
        else:
            # Connected but empty — possibly wrong customer number or style not available
            return {
                'ok': False,
                'message': 'Connected to SanMar but received no product data for style 3001C.',
                'details': (
                    'Your credentials were accepted but the response was empty. '
                    'Check that your SANMAR_CUSTOMER_NUMBER is correct and that '
                    'your account has access to Bella+Canvas products.'
                ),
            }
    except SanMarAuthError as exc:
        return {
            'ok': False,
            'message': f'Authentication failed: {exc}',
            'details': (
                'SanMar rejected your credentials. Double-check SANMAR_USERNAME '
                'and SANMAR_PASSWORD in Railway.'
            ),
        }
    except SanMarSOAPError as exc:
        return {
            'ok': False,
            'message': f'SanMar error: {exc}',
            'details': 'Check Railway logs for the full response. The endpoint URL or SOAP namespace may need updating.',
        }
    except (URLError, OSError) as exc:
        return {
            'ok': False,
            'message': f'Network error: {exc}',
            'details': 'Could not reach ws.sanmar.com. Check that outbound HTTPS is allowed on port 8080 from Railway.',
        }
    except Exception as exc:
        return {
            'ok': False,
            'message': f'Unexpected error: {exc}',
            'details': 'Check Railway logs for more detail.',
        }


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

        Raises SanMarAuthError / SanMarSOAPError on API-level failures.
        Returns {} on empty/unparseable responses.
        """
        root = _soap_request(style_number)

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

        if not color_variants:
            return None

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
        """
        Sync all BELLA_CANVAS_STYLES from SanMar.

        Raises SanMarAuthError immediately if the first style fails authentication
        so the caller can surface a clear error rather than silently returning [].
        """
        import sys
        products = []
        auth_checked = False

        for style in BELLA_CANVAS_STYLES:
            print(f'[SanMarAPI] Fetching style {style}…', file=sys.stderr, flush=True)
            try:
                style_data = self.fetch_style_data(style)
                auth_checked = True
                product = self.parse_style_to_product(style_data)
                if product:
                    products.append(product)
                else:
                    print(f'[SanMarAPI] No data for {style} (style not available or empty response)',
                          file=sys.stderr, flush=True)
            except SanMarAuthError:
                # Re-raise immediately — no point continuing with bad credentials
                raise
            except (SanMarSOAPError, URLError, OSError) as exc:
                print(f'[SanMarAPI] Skipping {style}: {exc}', file=sys.stderr, flush=True)
                continue
            except Exception as exc:
                print(f'[SanMarAPI] Unexpected error for {style}: {exc}', file=sys.stderr, flush=True)
                continue

        print(f'[SanMarAPI] Sync complete — {len(products)} products fetched.', file=sys.stderr, flush=True)
        return products
