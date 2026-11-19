"""Bulk order entry: type or paste a whole group's names, sizes and numbers in one table.

One entry makes two linked records, and each has one job:

* an Order, so the shirts show up in New Orders and the production workflow with every
  name, size and number attached (marked Awaiting Payment until the invoice is paid);
* a ManualInvoice, so the customer gets one invoice with a card pay link, and the books
  count the money once, the way they already count every hand-made invoice.

The order never counts as income itself (its payment_status is never 'paid'), so nothing is
counted twice. When the invoice is paid, `sync_order_from_invoice` releases the order.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import datetime

AWAITING = 'awaiting_payment'        # the invoice has not been paid yet
INVOICE_PAID = 'invoice_paid'        # the invoice is paid in full; the invoice is the money record
MAX_ROWS = 400


# ── Paste from Excel or Google Sheets ───────────────────────────────────────────────────────

_HEADER_WORDS = {
    'name': 'person', 'player': 'person', 'player name': 'person', 'who': 'person', 'full name': 'person',
    'size': 'size', 'sizes': 'size',
    'back': 'back_name', 'name on back': 'back_name', 'back name': 'back_name', 'jersey name': 'back_name',
    'last name': 'back_name', 'nickname': 'back_name',
    'number': 'number', 'no': 'number', 'no.': 'number', '#': 'number', 'jersey number': 'number', 'num': 'number',
    'qty': 'qty', 'quantity': 'qty', 'count': 'qty',
    'color': 'color', 'colour': 'color',
    'email': 'email', 'e-mail': 'email', 'email address': 'email',
}
_DEFAULT_ORDER = ['person', 'size', 'back_name', 'number', 'qty']


def _split_line(line: str):
    if '\t' in line:
        return [c.strip() for c in line.split('\t')]
    if line.count(',') >= 1:
        return [c.strip().strip('"') for c in line.split(',')]
    return [c.strip() for c in re.split(r'\s{2,}', line.strip())]


def parse_paste(text: str):
    """Rows from pasted spreadsheet text. A header row is used when there is one.

    Without a header the columns are read in this order: Name, Size, Name on back, Number, Qty.
    """
    rows = []
    columns = None
    for raw in (text or '').replace('\r', '').split('\n'):
        if not raw.strip():
            continue
        cells = _split_line(raw)
        if columns is None:
            lowered = [c.lower().strip() for c in cells]
            mapped = [_HEADER_WORDS.get(c) for c in lowered]
            if sum(1 for m in mapped if m) >= 2 and any(m in ('size', 'number', 'back_name') for m in mapped):
                columns = mapped
                continue
            columns = _DEFAULT_ORDER
        row = {'person': '', 'size': '', 'back_name': '', 'number': '', 'qty': 1, 'color': '', 'email': ''}
        for key, cell in zip(columns, cells):
            if not key:
                continue
            if key == 'qty':
                try:
                    row['qty'] = max(1, int(float(cell)))
                except (TypeError, ValueError):
                    row['qty'] = 1
            else:
                row[key] = cell[:120]
        if any(row[k] for k in ('person', 'size', 'back_name', 'number')):
            rows.append(row)
        if len(rows) >= MAX_ROWS:
            break
    return rows


# ── Building the order and its invoice ──────────────────────────────────────────────────────

class BulkOrderError(ValueError):
    pass


def _money(value) -> float:
    try:
        return max(round(float(str(value).replace('$', '').strip() or 0), 2), 0.0)
    except (TypeError, ValueError):
        return 0.0


def clean_payload(raw) -> dict:
    """Read the form's JSON into plain, safe values. Raises BulkOrderError for what is missing."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        raise BulkOrderError('The order could not be read. Please try again.')
    cust = data.get('customer') or {}
    name = str(cust.get('name') or '').strip()[:200]
    if not name:
        raise BulkOrderError('Please add who the order is for.')
    groups = []
    total_rows = 0
    for g in data.get('groups') or []:
        try:
            product_id = int(g.get('product_id'))
        except (TypeError, ValueError):
            continue
        rows = []
        for r in g.get('rows') or []:
            size = str(r.get('size') or '').strip()[:20]
            try:
                qty = max(1, min(int(float(r.get('qty') or 1)), 99))
            except (TypeError, ValueError):
                qty = 1
            person = str(r.get('person') or '').strip()[:120]
            back_name = str(r.get('back_name') or '').strip()[:60]
            number = str(r.get('number') or '').strip()[:10]
            if not (size or person or back_name or number):
                continue                                  # a blank row
            if not size:
                raise BulkOrderError(f'Please pick a size for {person or back_name or "every row"}.')
            rows.append({'person': person, 'size': size, 'qty': qty, 'back_name': back_name,
                         'number': number, 'color': str(r.get('color') or '').strip()[:100],
                         'email': str(r.get('email') or '').strip()[:200]})
        if rows:
            groups.append({'product_id': product_id, 'color': str(g.get('color') or '').strip()[:100],
                           'price': _money(g.get('price')), 'design_id': g.get('design_id'), 'rows': rows})
            total_rows += len(rows)
    if not groups:
        raise BulkOrderError('Please add at least one person with a size.')
    if total_rows > MAX_ROWS:
        raise BulkOrderError(f'That is more than {MAX_ROWS} rows. Please split it into two orders.')
    ship = data.get('ship') or {}
    return {
        'name': name,
        'company': str(cust.get('company') or '').strip()[:200],
        'email': str(cust.get('email') or '').strip()[:200],
        'phone': str(cust.get('phone') or '').strip()[:40],
        'fulfillment': 'pickup' if data.get('fulfillment') == 'pickup' else 'shipping',
        'ship': {k: str(ship.get(k) or '').strip()[:200] for k in ('street', 'street_2', 'city', 'state', 'zip')},
        'billing': 'individual' if data.get('billing') == 'individual' else 'one',
        'shipping': _money(data.get('shipping')),
        'tax_percent': min(_money(data.get('tax_percent')), 30.0),
        'note': str(data.get('note') or '').strip()[:400],
        'collection_id': data.get('collection_id'),
        'groups': groups,
    }


def invoice_lines(groups, products):
    """One invoice line per item / color / size / price, so a 20-shirt order is a few lines, not 20."""
    lines = OrderedDict()
    for g in groups:
        product = products[g['product_id']]
        for r in g['rows']:
            color = r['color'] or g['color'] or ''
            key = (product.id, color, r['size'], g['price'])
            line = lines.setdefault(key, {
                'description': f"{product.name} ({product.style_number})" + (f", {color}" if color else '') + f", {r['size']}",
                'qty': 0, 'unit': g['price']})
            line['qty'] += r['qty']
    return list(lines.values())


def create_bulk_order(payload: dict):
    """Make the Order and its invoice(s). Returns (order, [invoices]). Raises BulkOrderError.

    One invoice for everything by default. With billing 'individual' each person gets their own invoice
    (their shirts, their tax, and the shipping charge typed on the form), and all of them stay on the one order.
    """
    from models import Collection, Design, ManualInvoice, Order, Product, db
    from routes.checkout import build_order_items
    from sqlalchemy.exc import IntegrityError
    from utils.order_costs import default_due_date
    from utils.receipts import invoice_totals, next_invoice_number

    products = {}
    for g in payload['groups']:
        product = db.session.get(Product, g['product_id'])
        if not product:
            raise BulkOrderError('One of the items could not be found. Please pick it again.')
        products[product.id] = product
        if g['price'] <= 0:
            raise BulkOrderError(f'Please enter a price for {product.name}.')
        g['design'] = None
        try:
            did = int(g.get('design_id'))
            g['design'] = db.session.get(Design, did)
        except (TypeError, ValueError):
            pass

    payers = _payers(payload, products)
    totals = {k: round(sum(p['totals'][k] for p in payers), 2) for k in ('subtotal', 'tax', 'shipping', 'total')}

    collection_id = None
    try:
        cid = int(payload.get('collection_id') or 0)
        if cid and db.session.get(Collection, cid):
            collection_id = cid
    except (TypeError, ValueError):
        pass

    parts = payload['name'].split(' ', 1)
    ship = payload['ship']
    cart, people = [], []
    for g in payload['groups']:
        product = products[g['product_id']]
        design = g.get('design')
        for r in g['rows']:
            meta = {}
            if r['back_name']:
                meta['name'] = r['back_name']
            if r['number']:
                meta['number'] = r['number']
            people.append(r['person'])
            cart.append({
                'product_id': product.id, 'design_id': design.id if design else None,
                'size': r['size'], 'color': r['color'] or g['color'] or 'Unknown',
                'quantity': r['qty'], 'unit_price': g['price'],
                'back_design_meta': meta or None,
                'collection_id': collection_id,
            })

    order = Order(
        collection_id=collection_id, email=payload['email'] or None,
        first_name=parts[0], last_name=parts[1] if len(parts) > 1 else '', phone=payload['phone'] or None,
        fulfillment_method=payload['fulfillment'],
        shipping_recipient=payload['name'] if payload['fulfillment'] == 'shipping' else None,
        shipping_street=ship['street'] or None, shipping_street_2=ship['street_2'] or None,
        shipping_city=ship['city'] or None, shipping_state=ship['state'] or None, shipping_zip=ship['zip'] or None,
        subtotal=totals['subtotal'], shipping_cost=totals['shipping'], tax=totals['tax'], total=totals['total'],
        tax_rate_percent=payload['tax_percent'],
        payment_method='invoice', payment_status=AWAITING, amount_paid=0.0,
        status='new', production_stage='order_received', due_date=default_due_date(),
        customer_notes=payload['note'] or None,
    )
    db.session.add(order)
    db.session.flush()
    if not build_order_items(order, cart, rid='bulk-entry'):
        db.session.rollback()
        raise BulkOrderError('None of the items could be saved. Please try again.')
    from models import OrderItem
    for item, person in zip(OrderItem.query.filter_by(order_id=order.id).order_by(OrderItem.id).all(), people):
        if person:
            item.notes = f'For {person}'           # who each shirt is for, shown on the order page

    address = ', '.join(p for p in [ship['street'], ship['street_2'], ship['city'],
                                     ' '.join(x for x in [ship['state'], ship['zip']] if x)] if p)
    invoices = []
    for payer in payers:
        invoice = ManualInvoice(
            number=next_invoice_number(db.session, ManualInvoice, datetime.now().year),
            kind='invoice', customer_name=payer['name'], company=payload['company'],
            email=payer['email'], phone=payload['phone'], address=address,
            note=payload['note'], items_json=json.dumps(payer['lines']),
            tax_rate=payload['tax_percent'], shipping=payload['shipping'], discount=0.0,
            amount_paid=0.0, order_id=order.id, issued_at=datetime.utcnow(),
        )
        db.session.add(invoice)
        try:
            db.session.flush()                # the next invoice number counts this one
        except IntegrityError:
            db.session.rollback()
            raise BulkOrderError('Could not save the order. Please try again.')
        invoices.append(invoice)
    numbers = ', '.join(i.number for i in invoices)
    order.admin_notes = f'Entered by hand. Billed on invoice{"s" if len(invoices) > 1 else ""} {numbers}.'
    db.session.commit()
    return order, invoices


def _payers(payload, products):
    """Who gets an invoice: [{name, email, lines, totals}]. One payer, or one per person."""
    from utils.receipts import invoice_totals
    if payload.get('billing') != 'individual':
        lines = invoice_lines(payload['groups'], products)
        return [{'name': payload['name'], 'email': payload['email'], 'lines': lines,
                 'totals': invoice_totals(lines, payload['tax_percent'], payload['shipping'], 0)}]
    people = OrderedDict()
    for g in payload['groups']:
        for r in g['rows']:
            key = r['person'].lower() or '\0'
            entry = people.setdefault(key, {'name': r['person'] or payload['name'], 'email': '', 'groups': OrderedDict()})
            entry['email'] = entry['email'] or r['email']
            entry['groups'].setdefault(id(g), {**g, 'rows': []})['rows'].append(r)
    out = []
    for entry in people.values():
        lines = invoice_lines(list(entry['groups'].values()), products)
        out.append({'name': entry['name'], 'email': entry['email'], 'lines': lines,
                    'totals': invoice_totals(lines, payload['tax_percent'], payload['shipping'], 0)})
    return out


# ── Keeping the order in step with its invoice ──────────────────────────────────────────────

def invoices_for_order(order):
    from models import ManualInvoice
    return ManualInvoice.query.filter_by(order_id=order.id).order_by(ManualInvoice.id).all()


def invoice_for_order(order):
    found = invoices_for_order(order)
    return found[0] if found else None


def sync_order_from_invoice(inv):
    """After any payment on a bulk order's invoice: update the order. Never marks it 'paid',
    because the invoices are the money record and the books must count each one once.
    With several invoices the order is released once every one of them is paid."""
    if not getattr(inv, 'order_id', None):
        return None
    from models import Order, db
    from utils.receipts import doc_from_invoice
    order = db.session.get(Order, inv.order_id)
    if order is None:
        return None
    docs = [doc_from_invoice(i) for i in invoices_for_order(order)]
    order.amount_paid = round(sum(d['paid'] for d in docs), 2)
    if docs and all(d['paid'] > 0 and d['balance'] <= 0.004 for d in docs):
        order.payment_status = INVOICE_PAID
        order.paid_at = inv.paid_at or datetime.utcnow()
        if order.status == 'new':
            order.status = 'paid'
    elif order.payment_status == INVOICE_PAID:
        order.payment_status = AWAITING            # a refund or edit put a balance back
    db.session.commit()
    return order
