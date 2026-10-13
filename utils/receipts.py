"""One printable document (receipt or invoice) for site orders AND hand-made invoices.

Both are turned into the same plain dict, so the printed page looks identical:
the order receipt for a customer who ordered online, and the invoice Kayleigh
writes for someone who ordered directly (any brand, any price).
"""
import json
import re


def money(value):
    return round(float(value or 0), 2)


def _date_label(dt):
    from utils.local_time import format_central
    return format_central(dt, '%B %d, %Y').replace(' 0', ' ') if dt else ''


def _pick_kind(requested, balance):
    requested = (requested or '').strip().lower()
    if requested in ('receipt', 'invoice'):
        return requested
    return 'receipt' if balance <= 0 else 'invoice'


def doc_from_order(order, args):
    """Document for an order placed on the site. ``args`` is request.args (company, attn, po, note, kind)."""
    from utils.business_info import CARD_LABELS
    from utils.group_orders import order_group_label, order_has_regular_items, order_store_ids
    from models import Collection, db

    items = list(order.items)
    paid = money(order.amount_paid)
    if (order.payment_status or '') == 'paid' and not paid:
        paid = money(order.total)
    total = money(order.total)
    balance = round(max(total - paid, 0), 2)

    names = {}
    ids = order_store_ids(order)
    if len(ids) > 1 or order_has_regular_items(order):
        names = {c.id: c.name for c in Collection.query.filter(Collection.id.in_(ids)).all()}
    lines = []
    for item in items:
        detail = ' · '.join(x for x in (item.color, item.size and f'Size {item.size}') if x)
        if item.design and (item.design.title or item.design_file_name):
            detail += ' · Custom print'
        store = None
        if names or order_has_regular_items(order):
            cid = item.collection_id if item.collection_id is not None else order.collection_id
            store = 'Regular shop' if cid == 0 else names.get(cid)
        lines.append({'name': item.product_name or 'Item', 'detail': detail, 'qty': item.quantity,
                      'unit': money(item.unit_price), 'total': money(item.subtotal), 'for': store})
    discount = round(sum(l['total'] for l in lines) - money(order.subtotal), 2)

    ship_to = ''
    if order.fulfillment_method == 'shipping' and order.shipping_street:
        parts = [order.shipping_recipient or order.full_name, order.shipping_street, order.shipping_street_2,
                 f'{order.shipping_city}, {order.shipping_state} {order.shipping_zip}']
        ship_to = ', '.join(p for p in parts if p)

    return {
        'kind': _pick_kind(args.get('kind'), balance),
        'number': order.order_number,
        'date': _date_label(order.paid_at or order.created_at),
        'name': order.full_name, 'email': order.email or '', 'phone': order.phone or '',
        'company': (args.get('company') or '').strip()[:120], 'attn': (args.get('attn') or '').strip()[:120],
        'po': (args.get('po') or '').strip()[:60], 'address': '', 'ship_to': ship_to,
        'group': order_group_label(order), 'note': (args.get('note') or '').strip()[:400],
        'lines': lines,
        'subtotal': money(order.subtotal), 'discount': discount if discount > 0.005 else 0,
        'shipping': money(order.shipping_cost), 'tax': money(order.tax), 'tax_label': 'Tax', 'total': total,
        'paid': paid, 'balance': balance,
        'method': CARD_LABELS.get(order.payment_method or '', (order.payment_method or '').title()),
    }


def parse_items(raw):
    """Invoice lines from the form (or stored JSON): [{'description', 'qty', 'unit'}], blanks dropped."""
    try:
        rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        rows = []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        desc = str(row.get('description') or '').strip()[:300]
        try:
            qty = max(float(row.get('qty') or 0), 0)
            unit = max(float(row.get('unit') or 0), 0)
        except (TypeError, ValueError):
            continue
        if desc and qty:
            out.append({'description': desc, 'qty': int(qty) if qty == int(qty) else qty, 'unit': round(unit, 2)})
    return out


def invoice_totals(items, tax_rate, shipping, discount):
    subtotal = round(sum(round(i['qty'] * i['unit'], 2) for i in items), 2)
    discount = min(max(money(discount), 0), subtotal)
    taxable = round(subtotal - discount, 2)
    from decimal import Decimal, ROUND_HALF_UP
    tax = float((Decimal(str(taxable)) * Decimal(str(max(float(tax_rate or 0), 0))) / 100)
                .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    shipping = max(money(shipping), 0)
    return {'subtotal': subtotal, 'discount': discount, 'tax': tax, 'shipping': shipping,
            'total': round(taxable + tax + shipping, 2)}


def doc_from_invoice(inv, args=None):
    """Document for a hand-made invoice."""
    items = parse_items(inv.items_json)
    t = invoice_totals(items, inv.tax_rate, inv.shipping, inv.discount)
    paid = min(money(inv.amount_paid), t['total'])
    balance = round(max(t['total'] - paid, 0), 2)
    lines = [{'name': i['description'], 'detail': '', 'qty': i['qty'], 'unit': i['unit'],
              'total': round(i['qty'] * i['unit'], 2), 'for': None} for i in items]
    rate = float(inv.tax_rate or 0)
    return {
        'kind': _pick_kind(inv.kind, balance),
        'number': inv.number, 'date': _date_label(inv.issued_at or inv.created_at),
        'name': inv.customer_name or '', 'email': inv.email or '', 'phone': inv.phone or '',
        'company': inv.company or '', 'attn': inv.attn or '', 'po': inv.po or '',
        'address': inv.address or '', 'ship_to': '', 'group': '', 'note': inv.note or '',
        'lines': lines,
        'subtotal': t['subtotal'], 'discount': t['discount'], 'shipping': t['shipping'], 'tax': t['tax'],
        'tax_label': f'Tax ({rate:g}%)' if rate else 'Tax', 'total': t['total'],
        'paid': paid, 'balance': balance, 'method': (inv.payment_method or '').strip(),
    }


def next_invoice_number(session, model, year):
    """INV-2026-0001, then 0002, and so on (counted per year)."""
    prefix = f'INV-{year}-'
    last = (session.query(model.number).filter(model.number.like(prefix + '%'))
            .order_by(model.number.desc()).first())
    seq = 1
    if last:
        m = re.search(r'(\d+)$', last[0])
        seq = int(m.group(1)) + 1 if m else 1
    return f'{prefix}{seq:04d}'
