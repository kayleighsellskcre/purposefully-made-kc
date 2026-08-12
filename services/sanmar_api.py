"""
SanMar SOAP Web Service integration for Bella+Canvas products.

Credentials from environment variables:
  SANMAR_CUSTOMER_NUMBER
  SANMAR_USERNAME
  SANMAR_PASSWORD

Confirmed working method: getProductInfoByBrand
Response structure per row:
  listResponse/productBasicInfo  — style, productTitle, catalogColor, size, …
  listResponse/productImageInfo  — frontModel, backModel, colorProductImage, …
  listResponse/productPriceInfo  — piecePrice, casePrice, …
"""

import os
import sys
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


# ---------------------------------------------------------------------------
# Style list (used for reference / future filtering)
# ---------------------------------------------------------------------------

BELLA_CANVAS_STYLES = [
    'BC3001C', 'BC3001CVC', 'BC3001U', 'BC3005', 'BC3010',
    'BC3015', 'BC3021', 'BC3024', 'BC3025', 'BC3051CVC',
    'BC3055C', 'BC3100', 'BC3413', 'BC3413CVC', 'BC3413S',
    'BC3415', 'BC3415C', 'BC3480', 'BC3480C', 'BC3485',
    'BC6004', 'BC6004CVC', 'BC6035', 'BC6400', 'BC6400CVC',
    'BC6405', 'BC6413', 'BC6413S', 'BC6415', 'BC6435',
    'BC3001Y', 'BC3001YCVC', 'BC3413Y', 'BC3413YCVC', 'BC3001B',
    'BC3739', 'BC3901', 'BC3719', 'BC3729', 'BC3945',
    'BC7719', 'BC7720', 'BC7729', 'BC7739', 'BC3501CVC',
    'BC7519', 'BC7520', 'BC7529', 'BC7539',
    'BC3719Y', 'BC3729Y', 'BC3739Y',
    'BC8803', 'BC3501', 'BC3501T',
    'BC6682', 'BC6013',
    'BC3727', 'BC3728', 'BC8822',
    'BC100B', 'BC100CVC',
    # Without BC prefix as fallback (pre-acquisition style numbers)
    '3001C', '3001CVC', '3413', '3413CVC', '3001Y', '3719', '3739',
]
_seen: set = set()
BELLA_CANVAS_STYLES = [s for s in BELLA_CANVAS_STYLES if not (_seen.add(s) or s in _seen)]


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def get_credentials() -> tuple[str, str, str]:
    return (
        os.getenv('SANMAR_CUSTOMER_NUMBER', '').strip(),
        os.getenv('SANMAR_USERNAME', '').strip(),
        os.getenv('SANMAR_PASSWORD', '').strip(),
    )


def check_credentials() -> dict:
    customer_number, username, password = get_credentials()
    missing = []
    if not customer_number:
        missing.append('SANMAR_CUSTOMER_NUMBER')
    if not username:
        missing.append('SANMAR_USERNAME')
    if not password:
        missing.append('SANMAR_PASSWORD')
    return {'ok': not missing, 'missing': missing}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SanMarSOAPError(Exception):
    """SOAP Fault or unreadable response from SanMar."""
    pass


class SanMarAuthError(SanMarSOAPError):
    """Authentication failure."""
    pass


# ---------------------------------------------------------------------------
# SOAP constants
# ---------------------------------------------------------------------------

_SOAP_ENDPOINT = (
    'https://ws.sanmar.com:8080/SanMarWebService/SanMarProductInfoServicePort'
)

# Single template — brand-level query (the only confirmed working call)
_SOAP_BRAND_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ns2="http://impl.webservice.integration.sanmar.com/">
  <soapenv:Header/>
  <soapenv:Body>
    <ns2:getProductInfoByBrand>
      <arg0>
        <brandName>{brand}</brandName>
      </arg0>
      <arg1>
        <sanMarCustomerNumber>{customer_number}</sanMarCustomerNumber>
        <sanMarUserName>{username}</sanMarUserName>
        <sanMarUserPassword>{password}</sanMarUserPassword>
      </arg1>
    </ns2:getProductInfoByBrand>
  </soapenv:Body>
</soapenv:Envelope>"""


# ---------------------------------------------------------------------------
# Low-level request
# ---------------------------------------------------------------------------

def _do_soap_request(body_bytes: bytes, timeout: int = 30) -> ET.Element:
    """
    POST SOAP body, parse XML, check for faults.
    Raises SanMarAuthError, SanMarSOAPError, URLError, or OSError.
    """
    req = Request(
        _SOAP_ENDPOINT,
        data=body_bytes,
        headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': ''},
        method='POST',
    )
    raw = b''
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as exc:
        raw = exc.read() or b''

    if not raw:
        raise SanMarSOAPError('SanMar returned an empty response.')

    preview = raw[:500].decode('utf-8', errors='replace')
    print(f'[SanMarAPI] Raw response preview: {preview}', file=sys.stderr, flush=True)

    stripped = raw.lstrip()
    if stripped and stripped[0:1] != b'<':
        raise SanMarSOAPError(
            f'Non-XML response: {repr(raw[:300].decode("utf-8", errors="replace"))}'
        )

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SanMarSOAPError(
            f'XML parse error ({exc}): {repr(raw[:300].decode("utf-8", errors="replace"))}'
        )

    # Check for SOAP Fault
    for elem in root.iter():
        local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if local == 'Fault':
            faultstring = ''
            for child in elem.iter():
                cl = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if cl in ('faultstring', 'message', 'text'):
                    faultstring = (child.text or '').strip()
                    break
            auth_kw = ('invalid', 'authentication', 'unauthorized', 'credentials',
                       'password', 'username', 'login', 'access denied', 'not authorized')
            if any(k in faultstring.lower() for k in auth_kw):
                raise SanMarAuthError(faultstring or 'Authentication failed')
            raise SanMarSOAPError(faultstring or 'SOAP Fault')

    # Check for SanMar application-level error (errorOccured/message pattern)
    error_occured = ''
    error_message = ''
    for elem in root.iter():
        local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if local == 'errorOccured':
            error_occured = (elem.text or '').strip().lower()
        elif local == 'message' and not error_message:
            error_message = (elem.text or '').strip()

    if error_occured == 'true':
        auth_kw = ('invalid', 'authentication', 'unauthorized', 'credentials',
                   'password', 'username', 'login', 'access denied', 'not authorized')
        if any(k in error_message.lower() for k in auth_kw):
            raise SanMarAuthError(error_message or 'Authentication failed')
        raise SanMarSOAPError(error_message or 'SanMar returned an error (errorOccured=true)')

    return root


_WORKING_BRAND_NAME: str = 'BELLA+CANVAS'  # updated by test_connection on success


def _brand_request(timeout: int = 120) -> ET.Element:
    """Fetch the full Bella+Canvas catalog from SanMar in one call."""
    customer_number, username, password = get_credentials()
    body = _SOAP_BRAND_TEMPLATE.format(
        brand='BELLA+CANVAS',
        customer_number=customer_number,
        username=username,
        password=password,
    ).encode('utf-8')
    return _do_soap_request(body, timeout=timeout)


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

def test_connection() -> dict:
    """Quick credential test. Returns {ok, message, details}."""
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

    # Try multiple brand name spellings — SanMar's API is case-sensitive
    brand_candidates = ['BELLA+CANVAS', 'Bella+Canvas', 'Bella + Canvas', 'BELLA + CANVAS']

    last_error = ''
    for brand in brand_candidates:
        try:
            customer_number, username, password = get_credentials()
            body = _SOAP_BRAND_TEMPLATE.format(
                brand=brand,
                customer_number=customer_number,
                username=username,
                password=password,
            ).encode('utf-8')
            root = _do_soap_request(body, timeout=30)

            all_tags = sorted({
                (e.tag.split('}')[-1] if '}' in e.tag else e.tag)
                for e in root.iter()
            })
            list_rows = [
                e for e in root.iter()
                if (e.tag.split('}')[-1] if '}' in e.tag else e.tag) == 'listResponse'
            ]
            count = len(list_rows)
            sample_style = _ns_find(list_rows[0], 'style') if list_rows else ''
            sample_color = (
                _ns_find(list_rows[0], 'catalogColor') or _ns_find(list_rows[0], 'color')
            ) if list_rows else ''

            if count > 0 and sample_style:
                return {
                    'ok': True,
                    'message': (
                        f'Connected! Brand name "{brand}" works. '
                        f'{count} rows received. '
                        f'First row: style={sample_style}, color={sample_color}.'
                    ),
                    'details': f'Tags in response: {", ".join(all_tags)}',
                }
            # Connected but no product rows — note the brand that worked (no error) but empty
            last_error = (
                f'Brand "{brand}" accepted but returned 0 product rows. '
                f'Tags: {", ".join(all_tags)}'
            )
        except SanMarAuthError as exc:
            return {
                'ok': False,
                'message': f'Authentication failed: {exc}',
                'details': 'Double-check SANMAR_USERNAME and SANMAR_PASSWORD in Railway.',
            }
        except SanMarSOAPError as exc:
            last_error = f'Brand "{brand}": {exc}'
            continue  # try next brand name
        except (URLError, OSError) as exc:
            return {
                'ok': False,
                'message': f'Network error: {exc}',
                'details': 'Could not reach ws.sanmar.com:8080.',
            }
        except Exception as exc:
            return {
                'ok': False,
                'message': f'Unexpected error: {exc}',
                'details': 'Check Railway logs for the traceback.',
            }

    # None of the brand names worked
    return {
        'ok': False,
        'message': f'Could not find valid brand name. Last error: {last_error}',
        'details': (
            'Tried: BELLA+CANVAS, Bella+Canvas, Bella + Canvas. '
            'Your SanMar account may need to be provisioned for Web Services API access — '
            'call SanMar support at 800-426-6399 and ask to enable '
            '"Product Info Web Services" on your account.'
        ),
    }


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

def _ns_find(element: ET.Element, tag: str) -> str:
    """Return text of first descendant matching tag (namespace-agnostic)."""
    for child in element.iter():
        local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if local == tag:
            return (child.text or '').strip()
    return ''


def _parse_list_response(row: ET.Element) -> dict:
    """
    Parse one <listResponse> element.

    Real structure (confirmed from SanMar docs):
      listResponse/productBasicInfo  → style, productTitle, catalogColor, color, size, …
      listResponse/productImageInfo  → frontModel, backModel, colorProductImage, colorSquareImage
      listResponse/productPriceInfo  → piecePrice, casePrice
    """
    return {
        'style':       _ns_find(row, 'style'),
        'color_name':  (_ns_find(row, 'catalogColor')
                        or _ns_find(row, 'color')
                        or _ns_find(row, 'colorName')),
        'size':        _ns_find(row, 'size'),
        'price':       _ns_find(row, 'piecePrice') or _ns_find(row, 'casePrice'),
        'title':       _ns_find(row, 'productTitle') or _ns_find(row, 'title'),
        'description': _ns_find(row, 'productDescription') or _ns_find(row, 'description'),
        'material':    _ns_find(row, 'material') or _ns_find(row, 'fabric'),
        'front_image': _ns_find(row, 'frontModel') or _ns_find(row, 'colorProductImage'),
        'back_image':  _ns_find(row, 'backModel'),
        'color_swatch':_ns_find(row, 'colorSquareImage') or _ns_find(row, 'colorSwatchImage'),
        'color_hex':   _ns_find(row, 'colorHex') or '',
    }


# ---------------------------------------------------------------------------
# Main API class
# ---------------------------------------------------------------------------

class SanMarAPI:
    """SanMar SOAP client for Bella+Canvas catalog sync."""

    def fetch_full_catalog(self) -> list[dict]:
        """
        Fetch the entire Bella+Canvas catalog in one SOAP call.
        Tries multiple brand name spellings until one succeeds.
        """
        brand_candidates = ['BELLA+CANVAS', 'Bella+Canvas', 'Bella + Canvas', 'BELLA + CANVAS']
        customer_number, username, password = get_credentials()
        root = None
        last_error = ''

        for brand in brand_candidates:
            try:
                body = _SOAP_BRAND_TEMPLATE.format(
                    brand=brand,
                    customer_number=customer_number,
                    username=username,
                    password=password,
                ).encode('utf-8')
                root = _do_soap_request(body, timeout=120)
                print(f'[SanMarAPI] Brand name "{brand}" accepted.', file=sys.stderr, flush=True)
                break
            except SanMarAuthError:
                raise
            except SanMarSOAPError as exc:
                last_error = str(exc)
                print(f'[SanMarAPI] Brand "{brand}" failed: {exc}', file=sys.stderr, flush=True)
                continue

        if root is None:
            raise SanMarSOAPError(f'No valid brand name found. Last error: {last_error}')

        # Group rows by style
        styles: dict[str, dict] = {}
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local != 'listResponse':
                continue

            row = _parse_list_response(elem)
            style = row['style'].strip()
            if not style:
                continue

            if style not in styles:
                styles[style] = {
                    'style': style,
                    'title': '',
                    'description': '',
                    'material': '',
                    'color_variants': {},
                }

            sd = styles[style]
            if not sd['title'] and row['title']:
                sd['title'] = row['title']
            if not sd['description'] and row['description']:
                sd['description'] = row['description']
            if not sd['material'] and row['material']:
                sd['material'] = row['material']

            color = row['color_name']
            if not color:
                continue

            if color not in sd['color_variants']:
                sd['color_variants'][color] = {
                    'sizes': [],
                    'price': 0.0,
                    'front_image': row['front_image'],
                    'back_image': row['back_image'],
                    'color_swatch': row['color_swatch'],
                    'color_hex': row['color_hex'],
                    'inventory': {},
                }

            cv = sd['color_variants'][color]
            size = row['size']
            if size and size not in cv['sizes']:
                cv['sizes'].append(size)
            try:
                p = float(row['price'])
                if p > 0 and cv['price'] == 0.0:
                    cv['price'] = p
            except (ValueError, TypeError):
                pass

        products = []
        for style_data in styles.values():
            product = self._to_product(style_data)
            if product:
                products.append(product)

        print(
            f'[SanMarAPI] Parsed {len(styles)} styles → {len(products)} products.',
            file=sys.stderr, flush=True,
        )
        return products

    def _to_product(self, style_data: dict) -> dict | None:
        """Convert grouped style data into the Product model format."""
        style = style_data.get('style', '')
        color_variants = style_data.get('color_variants', {})
        if not style or not color_variants:
            return None

        all_sizes: list[str] = []
        all_colors: list[str] = list(color_variants.keys())
        base_price = 0.0

        for cv_data in color_variants.values():
            for sz in cv_data.get('sizes', []):
                if sz not in all_sizes:
                    all_sizes.append(sz)
            if not base_price and cv_data.get('price'):
                base_price = cv_data['price']

        color_variants_list = [
            {
                'color_name':     color,
                'front_image':    cv.get('front_image', ''),
                'back_image':     cv.get('back_image', ''),
                'side_image':     '',
                'color_hex':      cv.get('color_hex', '') or cv.get('color_swatch', ''),
                'size_inventory': cv.get('inventory', {}),
                'color_id':       None,
            }
            for color, cv in color_variants.items()
        ]

        return {
            'style_number':          style,
            'name':                  style_data.get('title') or f'Bella+Canvas {style}',
            'brand':                 'Bella+Canvas',
            'description':           style_data.get('description', ''),
            'fabric_details':        style_data.get('material', ''),
            'base_price':            base_price,
            'wholesale_cost':        round(base_price * 0.6, 2) if base_price else 0.0,
            'available_sizes':       ', '.join(all_sizes),
            'available_colors':      ', '.join(all_colors),
            'category':              'T-Shirts',
            'is_active':             True,
            'front_mockup_template': next(
                (cv['front_image'] for cv in color_variants.values() if cv.get('front_image')), ''
            ),
            'back_mockup_template':  next(
                (cv['back_image'] for cv in color_variants.values() if cv.get('back_image')), ''
            ),
            'color_variants':        color_variants_list,
            'api_data':              None,
        }

    def sync_bella_canvas_catalog(self) -> list[dict]:
        """
        Public entry point called by admin route and scheduler.
        Fetches the full catalog and returns product dicts.
        Raises SanMarAuthError on auth failure.
        """
        cred_check = check_credentials()
        if not cred_check['ok']:
            missing = ', '.join(cred_check['missing'])
            raise SanMarSOAPError(f'Missing credentials: {missing}')

        return self.fetch_full_catalog()
