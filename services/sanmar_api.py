"""
SanMar SOAP Web Service integration.

Credentials from environment variables:
  SANMAR_CUSTOMER_NUMBER
  SANMAR_USERNAME
  SANMAR_PASSWORD

Confirmed working method: getProductInfoByBrand
Also tries getProductInfoByStyle for curated bestsellers.
"""

import json
import math
import os
import re
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
# Size code normalisation
# ---------------------------------------------------------------------------

_SIZE_LABEL_MAP: dict[str, str] = {
    # Infant / toddler numeric codes from SanMar
    '0003': 'NB',
    '0306': '0-3M',
    '0612': '6-12M',
    '1218': '12-18M',
    '1824': '18-24M',
    # Youth codes (rarely numeric, but just in case)
    '0002': '2T',
    '0004': '4T',
    '0006': '6T',
}


def normalize_size(raw: str) -> str:
    """Convert a raw SanMar size code to a human-readable label."""
    cleaned = (raw or '').strip()
    return _SIZE_LABEL_MAP.get(cleaned, cleaned)


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

_SOAP_STYLE_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
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
        # Only treat as auth failure if it's clearly about credentials, not just "invalid" anything
        auth_kw = ('authentication failed', 'unauthorized', 'invalid credentials',
                   'invalid password', 'invalid username', 'invalid user',
                   'access denied', 'not authorized', 'login failed')
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
            # Connected but no product rows — surface the message field value
            sanmar_msg = _ns_find(root, 'message')
            last_error = (
                f'Brand "{brand}" accepted, 0 rows. '
                f'SanMar message: "{sanmar_msg}". '
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

    # None of the Bella+Canvas brand name variants worked.
    # Try a known SanMar brand to check if the API account itself is provisioned.
    try:
        customer_number, username, password = get_credentials()
        body = _SOAP_BRAND_TEMPLATE.format(
            brand='Port Authority',
            customer_number=customer_number,
            username=username,
            password=password,
        ).encode('utf-8')
        root = _do_soap_request(body, timeout=20)
        pa_rows = sum(
            1 for e in root.iter()
            if (e.tag.split('}')[-1] if '}' in e.tag else e.tag) == 'listResponse'
        )
        if pa_rows > 0:
            return {
                'ok': False,
                'message': (
                    f'API account works (Port Authority returned {pa_rows} rows) '
                    'but BELLA+CANVAS is not available under any brand name tried.'
                ),
                'details': (
                    'SanMar acquired BELLA+CANVAS in June 2026. '
                    'The brand may not yet be in the Web Services API, '
                    'or may require a separate enablement. '
                    'Call SanMar at 800-426-6399 and ask how to query BELLA+CANVAS '
                    'via the Product Info Web Services API (getProductInfoByBrand).'
                ),
            }
    except Exception:
        pass  # Port Authority check failed too — account not provisioned

    return {
        'ok': False,
        'message': f'SanMar API returned no product data. Details: {last_error}',
        'details': (
            'Your credentials connect but SanMar is not returning Bella+Canvas products. '
            'This usually means your SanMar account (#306292) needs Web Services API access enabled. '
            'Call SanMar at 800-426-6399, give them customer # 306292, and ask them to: '
            '(1) Enable "Product Info Web Services" on your account, and '
            '(2) Confirm the exact brandName string to use for BELLA+CANVAS in getProductInfoByBrand.'
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
        'front_image': (_ns_find(row, 'colorProductImage')
                        or _ns_find(row, 'frontModel')),
        'back_image':  (_ns_find(row, 'colorProductImageBack')
                        or _ns_find(row, 'backModel')),
        'color_swatch':_ns_find(row, 'colorSquareImage') or _ns_find(row, 'colorSwatchImage'),
        'color_hex':   _ns_find(row, 'colorHex') or '',
    }


def normalize_style_key(style: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', (style or '').upper())


def style_is_allowed(style: str, allowed: list[str]) -> bool:
    key = normalize_style_key(style)
    if not key:
        return False
    allowed_keys = {normalize_style_key(item) for item in allowed}
    if key in allowed_keys:
        return True
    if key.startswith('BC') and key[2:] in allowed_keys:
        return True
    if f'BC{key}' in allowed_keys:
        return True
    if key.startswith('RS') and key[2:] in allowed_keys:
        return True
    if f'RS{key}' in allowed_keys:
        return True
    if key.startswith('C') and key[1:] in allowed_keys:
        return True
    return False


def _group_list_responses(root: ET.Element) -> dict:
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
            price = float(row['price'])
            if price > 0 and cv['price'] == 0.0:
                cv['price'] = price
        except (ValueError, TypeError):
            pass
    return styles


def _soap_call(template: str, timeout: int, **fields) -> ET.Element:
    customer_number, username, password = get_credentials()
    body = template.format(
        customer_number=customer_number,
        username=username,
        password=password,
        **fields,
    ).encode('utf-8')
    return _do_soap_request(body, timeout=timeout)


# ---------------------------------------------------------------------------
# Main API class
# ---------------------------------------------------------------------------

class SanMarAPI:
    """SanMar SOAP client for curated brand catalog sync."""

    def fetch_brand_catalog(self, api_names: list[str], timeout: int = 120) -> dict:
        """Return grouped styles for the first brand name SanMar accepts."""
        last_error = ''
        for brand in api_names:
            try:
                root = _soap_call(_SOAP_BRAND_TEMPLATE, timeout, brand=brand)
                grouped = _group_list_responses(root)
                print(
                    f'[SanMarAPI] Brand "{brand}" returned {len(grouped)} styles.',
                    file=sys.stderr, flush=True,
                )
                return grouped
            except SanMarAuthError:
                raise
            except SanMarSOAPError as exc:
                last_error = str(exc)
                print(f'[SanMarAPI] Brand "{brand}" failed: {exc}', file=sys.stderr, flush=True)
        raise SanMarSOAPError(f'No valid brand name found. Last error: {last_error}')

    def fetch_style(self, style: str, timeout: int = 45) -> dict:
        root = _soap_call(_SOAP_STYLE_TEMPLATE, timeout, style=style)
        return _group_list_responses(root)

    def fetch_full_catalog(self) -> list[dict]:
        """Legacy Bella-only fetch. Prefer sync_curated_catalog()."""
        grouped = self.fetch_brand_catalog(['BELLA+CANVAS', 'Bella+Canvas', 'Bella + Canvas'])
        products = []
        for style_data in grouped.values():
            product = self._to_product(style_data, brand_name='Bella+Canvas')
            if product:
                products.append(product)
        return products

    def bestsellers_for_brand(self, brand: dict) -> list[dict]:
        """Return curated products for one brand, or [] if SanMar has no access."""
        display = brand['name']
        allowed = brand['styles']
        grouped: dict = {}
        try:
            grouped = self.fetch_brand_catalog(brand['api_names'], timeout=40)
        except SanMarSOAPError as exc:
            print(f'[SanMarAPI] {display} brand fetch failed: {exc}', file=sys.stderr, flush=True)

        matched = {
            style: data for style, data in grouped.items()
            if style_is_allowed(style, allowed)
        }

        if not matched:
            tried = set()
            for style in allowed:
                key = normalize_style_key(style)
                if key in tried:
                    continue
                tried.add(key)
                try:
                    extra = self.fetch_style(style, timeout=20)
                    for extra_style, data in extra.items():
                        if style_is_allowed(extra_style, allowed):
                            matched[extra_style] = data
                except Exception as exc:
                    print(
                        f'[SanMarAPI] Style {style} ({display}) skipped: {exc}',
                        file=sys.stderr, flush=True,
                    )

        products = []
        for style_data in matched.values():
            product = self._to_product(style_data, brand_name=display)
            if product:
                products.append(product)
        return products

    def sync_curated_catalog(self) -> tuple[list[dict], list[str]]:
        """Pull only the bestseller styles for each shop brand.

        Returns (products, notes) so admin can see brands that SanMar skipped.
        """
        from services.sanmar_catalog import CURATED_BRANDS

        cred_check = check_credentials()
        if not cred_check['ok']:
            missing = ', '.join(cred_check['missing'])
            raise SanMarSOAPError(f'Missing credentials: {missing}')

        products: list[dict] = []
        notes: list[str] = []

        for brand in CURATED_BRANDS:
            display = brand['name']
            brand_products = self.bestsellers_for_brand(brand)
            products.extend(brand_products)
            if brand_products:
                notes.append(f'{display}: {len(brand_products)} styles')
            else:
                notes.append(f'{display}: none returned (account may not include this line)')

        print(
            f'[SanMarAPI] Curated sync parsed {len(products)} products.',
            file=sys.stderr, flush=True,
        )
        return products, notes

    def _to_product(self, style_data: dict, brand_name: str = 'Bella+Canvas') -> dict | None:
        """Convert grouped style data into the Product model format."""
        from utils.product_filters import infer_age, infer_category, infer_fit
        from utils.sizes import sort_sizes

        style = style_data.get('style', '')
        color_variants = style_data.get('color_variants', {})
        if not style or not color_variants:
            return None

        all_sizes: list[str] = []
        all_colors: list[str] = list(color_variants.keys())
        wholesale = 0.0

        for cv_data in color_variants.values():
            for sz in cv_data.get('sizes', []):
                label = normalize_size(sz)
                if label and label not in all_sizes:
                    all_sizes.append(label)
            if not wholesale and cv_data.get('price'):
                wholesale = float(cv_data['price'])

        color_variants_list = [
            {
                'color_name':      color,
                'front_image':     cv.get('front_image', ''),
                'back_image':      cv.get('back_image', ''),
                'side_image':      '',
                'color_hex':       cv.get('color_hex', ''),
                'color_swatch':    cv.get('color_swatch', ''),
                'size_inventory':  json.dumps(cv.get('inventory') or {}),
                'color_id':        None,
            }
            for color, cv in color_variants.items()
        ]

        raw_name = (style_data.get('title') or f'{brand_name} {style}').strip()
        if style and raw_name.upper().endswith(style.upper()):
            raw_name = raw_name[:-len(style)].strip()
        if brand_name.lower() not in raw_name.lower():
            raw_name = f'{brand_name} {raw_name}'.strip()

        attrs = {
            'name': raw_name,
            'category': style_data.get('title') or '',
            'style_number': style,
        }
        category = infer_category(attrs)
        age_group = infer_age(attrs)
        fit_type = infer_fit(attrs)

        retail = (math.ceil(wholesale) + 19) if wholesale else 0.0

        return {
            'style_number':          style,
            'name':                  raw_name,
            'brand':                 brand_name,
            'description':           style_data.get('description', ''),
            'fabric_details':        style_data.get('material', ''),
            'base_price':            retail,
            'wholesale_cost':        round(wholesale, 2) if wholesale else 0.0,
            'available_sizes':       json.dumps(sort_sizes(all_sizes)),
            'available_colors':      json.dumps(all_colors),
            'category':              category,
            'age_group':             age_group,
            'fit_type':              fit_type,
            'is_active':             True,
            'is_customer_favorite':  True,
            'front_mockup_template': next(
                (cv['front_image'] for cv in color_variants.values() if cv.get('front_image')), ''
            ),
            'back_mockup_template':  next(
                (cv['back_image'] for cv in color_variants.values() if cv.get('back_image')), ''
            ),
            'color_variants':        color_variants_list,
        }

    def sync_bella_canvas_catalog(self) -> list[dict]:
        """Public entry used by admin and scheduler. Syncs all curated brands."""
        products, _notes = self.sync_curated_catalog()
        return products

    # ------------------------------------------------------------------
    # Inventory sync
    # ------------------------------------------------------------------

    _INVENTORY_ENDPOINT = (
        'https://ws.sanmar.com:8080/SanMarWebService/SanMarInventoryServicePort'
    )

    _INV_SOAP_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ns2="http://impl.webservice.integration.sanmar.com/">
  <soapenv:Header/>
  <soapenv:Body>
    <ns2:getInventoryQty>
      <arg0>
        <style>{style}</style>
      </arg0>
      <arg1>
        <sanMarCustomerNumber>{customer_number}</sanMarCustomerNumber>
        <sanMarUserName>{username}</sanMarUserName>
        <sanMarUserPassword>{password}</sanMarUserPassword>
      </arg1>
    </ns2:getInventoryQty>
  </soapenv:Body>
</soapenv:Envelope>"""

    def fetch_inventory_for_style(self, style: str, timeout: int = 30) -> dict:
        """
        Returns {color: {size: qty}} for a single style.
        qty is an integer (0 if out of stock). Multiple warehouse rows are summed.
        """
        customer_number, username, password = get_credentials()
        body = self._INV_SOAP_TEMPLATE.format(
            style=style,
            customer_number=customer_number,
            username=username,
            password=password,
        ).encode('utf-8')

        req = Request(
            self._INVENTORY_ENDPOINT,
            data=body,
            headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': ''},
            method='POST',
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except Exception as exc:
            print(f'[SanMarAPI] Inventory fetch failed for {style}: {exc}', file=sys.stderr)
            return {}

        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return {}

        inventory: dict[str, dict[str, int]] = {}
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local != 'listResponse':
                continue
            color = _ns_find(elem, 'catalogColor') or _ns_find(elem, 'color') or ''
            size  = normalize_size(_ns_find(elem, 'size') or '')
            qty_s = _ns_find(elem, 'qty') or _ns_find(elem, 'quantity') or '0'
            try:
                qty = int(float(qty_s))
            except (ValueError, TypeError):
                qty = 0
            if color and size:
                inventory.setdefault(color, {})
                inventory[color][size] = inventory[color].get(size, 0) + max(0, qty)

        return inventory

    def sync_inventory_for_all_styles(self, style_list: list[str]) -> dict:
        """
        Fetches live inventory for every style in style_list.
        Returns {style: {color: {size: qty}}}.
        Skips styles that error — logs and continues.
        """
        results: dict[str, dict] = {}
        for style in style_list:
            try:
                inv = self.fetch_inventory_for_style(style)
                results[style] = inv
                print(
                    f'[SanMarAPI] Inventory for {style}: '
                    f'{sum(len(v) for v in inv.values())} size/color combos',
                    file=sys.stderr, flush=True,
                )
            except Exception as exc:
                print(f'[SanMarAPI] Skipping inventory for {style}: {exc}', file=sys.stderr)
        return results
