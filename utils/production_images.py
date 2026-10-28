"""Every print picture on the Production Master page, ready to save in one go.

Each file is named so it sorts and reads at a glance:  YM_8.5x7.1in_Student-Council_x1_PMKC-1234.png
(size code, print width x height in inches, what it is, how many, which order).
"""
import re
import zipfile
from io import BytesIO
from urllib.request import Request, urlopen

from flask import current_app

from utils.order_artwork import back_print_url, front_print_url, local_file_for_url, remote_url_allowed
from utils.size_codes import size_code


def _slug(value, fallback='design'):
    text = re.sub(r'[^A-Za-z0-9]+', '-', str(value or '')).strip('-')
    return text[:40] or fallback


def _dim(value):
    try:
        return f'{float(value):.1f}'.rstrip('0').rstrip('.') if value is not None else '?'
    except (TypeError, ValueError):
        return '?'


def file_name(code, width, height, label, qty, order_number):
    return f'{code or "NA"}_{_dim(width)}x{_dim(height)}in_{_slug(label)}_x{int(qty or 1)}_{_slug(order_number, "order")}.png'


def fetch_bytes(url, host_url=None):
    """The picture's bytes from our uploads or our image storage; None if it cannot be read."""
    if not url:
        return None
    local = local_file_for_url(current_app, url)
    if local:
        return local.read_bytes()
    fetch = url
    if url.startswith('/') and host_url:
        fetch = host_url.rstrip('/') + url
    if fetch.startswith(('http://', 'https://')) and (remote_url_allowed(current_app, fetch, host_url) or url.startswith('/')):
        try:
            with urlopen(Request(fetch, headers={'User-Agent': 'PMKC-Admin/1.0'}), timeout=20) as resp:
                return resp.read()
        except Exception:
            current_app.logger.warning('production image fetch failed: %s', fetch)
    return None


def bytes_for(order, item, side, host_url=None):
    """PNG bytes for one print file (front picture, back picture, or the name/number back), or None."""
    if side == 'back':
        meta = item.back_design_details or {}
        if meta.get('name') or meta.get('number'):
            from utils.name_number_art import generate_personalized_png
            try:
                data, _snap = generate_personalized_png(current_app, item, 'back', customer_name=order.full_name)
                return data
            except Exception:
                current_app.logger.exception('production zip: back build failed item=%s', item.id)
                return None
        return fetch_bytes(back_print_url(item), host_url)
    return fetch_bytes(front_print_url(item), host_url)


def zip_bytes(entries, host_url=None):
    """entries: [(order, item, side, filename)] -> (zip bytes, how many files, names that could not be read)."""
    out = BytesIO()
    added, missing, used = 0, [], set()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        for order, item, side, name in entries:
            data = bytes_for(order, item, side, host_url)
            if not data:
                missing.append(name)
                continue
            from utils.order_artwork import labeled_png
            data = labeled_png(data, name)                          # the size label is part of every saved picture
            base, n = name, 2
            while name in used:
                name, n = base.replace('.png', f'-{n}.png'), n + 1
            used.add(name)
            zf.writestr(name, data)
            added += 1
    return out.getvalue(), added, missing


def code_for(item):
    return size_code(item.size, getattr(item, 'product', None))
