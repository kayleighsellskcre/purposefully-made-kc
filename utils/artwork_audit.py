"""Daily check that every recent order still has its print file, so a lost one is caught while the customer can still resend it."""
from __future__ import annotations

from datetime import datetime, timedelta

DAYS = 21


def _present(app, url):
    """True when the file at ``url`` can still be loaded. Unknown hosts count as present (never blocks on our guess)."""
    if not url or url.startswith('data:'):
        return True
    if url.startswith(('http://', 'https://')):
        from utils.asset_urls import is_fetchable_url
        if not is_fetchable_url(url, app):
            return True
        import urllib.request
        try:
            req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'PMKC-artwork-check'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                return 200 <= resp.status < 400
        except Exception as exc:
            return getattr(exc, 'code', None) not in (404, 410)         # a timeout is not proof the file is gone
    from utils.order_artwork import local_file_for_url
    return local_file_for_url(app, url if url.startswith('/') else '/static/' + url.lstrip('/')) is not None


def find_missing(app, days=DAYS, now=None):
    """[(order_number, item_id, side, url)] for recent, not-cancelled orders whose print file cannot be loaded."""
    from models import Order, OrderItem
    from utils.order_artwork import back_print_url, front_print_url
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    rows = (OrderItem.query.join(Order, Order.id == OrderItem.order_id)
            .filter(Order.created_at >= cutoff, Order.status != 'cancelled').all())
    out = []
    for item in rows:
        checks = []
        if getattr(item, 'design_id', None) or getattr(item, 'design_file_name', None):
            checks.append(('front', front_print_url(item)))
        meta = getattr(item, 'back_design_details', None) or {}
        if getattr(item, 'back_design_file_name', None) and not (meta.get('name') or meta.get('number')):
            checks.append(('back', back_print_url(item)))
        for side, url in checks:
            if url and not _present(app, url):
                out.append((item.order.order_number, item.id, side, url))
    return out


def alert_if_missing(app):
    """Email the owner the list when anything is missing. Returns how many files are missing. Never raises."""
    try:
        missing = find_missing(app)
        if not missing:
            return 0
        from flask_mail import Message

        from utils import mailer
        lines = [f'  Order {num}: the {side} print file is missing ({url})' for num, _i, side, url in missing[:40]]
        body = ('These recent orders have a print file that can no longer be loaded:\n\n' + '\n'.join(lines) +
                '\n\nAsk each customer to send the artwork again. On the order page in the admin, open "Replace this print file" '
                'and upload it; it is then saved permanently.\n')
        mailer.send(app, Message(subject=f'{len(missing)} order print file(s) missing',
                                 recipients=[mailer.admin_recipient(app)], body=body), 'missing artwork alert')
        return len(missing)
    except Exception:
        app.logger.exception('artwork audit failed')
        return 0
