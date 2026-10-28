"""Donations: shirts given away (a school silent auction, say). Each winner gets a private link, picks a shirt, and the free
order it makes goes through production like any other. What it cost is booked as a charitable donation, at cost."""
import json
import re
import secrets
from datetime import datetime

from models import Design, Donation, DonationClaim, Order, Product, db
from utils.json_fields import parse_json_list


def new_token():
    return secrets.token_urlsafe(16).replace('-', 'a').replace('_', 'b')[:22]


def get_claim(token):
    return DonationClaim.query.filter_by(token=str(token or '')).first()


def _ids(raw):
    out = []
    for x in parse_json_list(raw or ''):
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def tee_products():
    """Plain T-shirt styles a winner can be offered (adult short sleeve tees)."""
    rows = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    return [p for p in rows if 'tee' in (p.category or '').lower() and 'long' not in (p.category or '').lower()
            and (p.age_group or 'adult') == 'adult']


def group_designs(collection):
    from utils.group_orders import allowed_design_ids
    ids = allowed_design_ids(collection) if collection else []
    if not ids:
        return []
    found = {d.id: d for d in Design.query.filter(Design.id.in_(ids)).all()}
    return [found[i] for i in ids if i in found]


def available_designs(donation):
    """The designs a winner can pick: the ones chosen for this donation, else all of the group's."""
    pool = group_designs(donation.collection)
    chosen = set(_ids(donation.design_ids))
    return [d for d in pool if d.id in chosen] if chosen else pool


def available_products(donation):
    chosen = _ids(donation.product_ids)
    if not chosen:
        return []
    found = {p.id: p for p in Product.query.filter(Product.id.in_(chosen)).all()}
    return [found[i] for i in chosen if i in found and found[i].is_active]


def create_donation(*, recipient, occasion, donated_on, winners, collection_id, product_ids, note):
    recipient = ' '.join((recipient or '').split())[:200]
    if not recipient:
        raise ValueError('Who is the donation for?')
    if not donated_on:
        raise ValueError('Choose the date of the donation.')
    winners = max(1, min(int(winners or 1), 50))
    donation = Donation(recipient=recipient, occasion=(occasion or '').strip()[:200] or None, donated_on=donated_on,
                        winners_expected=winners, collection_id=collection_id or None,
                        product_ids=json.dumps([int(i) for i in product_ids]), note=(note or '').strip() or None)
    db.session.add(donation)
    db.session.flush()
    for _ in range(winners):                      # one empty slot per winner, each with its own private link
        db.session.add(DonationClaim(donation_id=donation.id, token=new_token()))
    db.session.commit()
    return donation


def cost_so_far(donation):
    """(cost in dollars, orders counted, true if any cost is still an estimate)."""
    total, count, estimate = 0.0, 0, False
    for claim in donation.claims:
        o = claim.order
        if o is None:
            continue
        count += 1
        total += float(o.cost_of_goods or 0)
        estimate = estimate or not o.cogs_is_actual
    return round(total, 2), count, estimate


def place_claim(claim, form):
    """Turn a winner's choices into a free order. Returns (order, error)."""
    from routes.checkout import build_order_items
    from utils.order_costs import apply_order_defaults, default_due_date
    from utils.print_sizes import build_item_production

    if claim.order_id:
        return None, 'This gift has already been chosen.'
    donation = claim.donation
    try:
        product = db.session.get(Product, int(form.get('product_id') or 0))
        design = db.session.get(Design, int(form.get('design_id') or 0))
    except (TypeError, ValueError):
        product = design = None
    if product is None or product not in available_products(donation):
        return None, 'Please choose a shirt.'
    if design is None or design not in available_designs(donation):
        return None, 'Please choose a design.'
    color = ' '.join((form.get('color') or '').split())
    from flask import current_app
    from utils.mockups import get_color_variants_data_for_product
    colors = {c['color_name'] for c in get_color_variants_data_for_product(product, current_app._get_current_object())}
    if color not in colors:
        return None, 'Please choose a color.'
    size = (form.get('size') or '').strip()
    if size not in set(parse_json_list(product.available_sizes)):
        return None, 'Please choose a size.'
    first = ' '.join((form.get('first_name') or '').split())[:100]
    last = ' '.join((form.get('last_name') or '').split())[:100]
    email = (form.get('email') or '').strip()[:120]
    if not first or not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return None, 'Please add your name and a good email so we can reach you.'
    ship = form.get('fulfillment') == 'shipping'
    street = ' '.join((form.get('shipping_street') or '').split())[:200]
    city = ' '.join((form.get('shipping_city') or '').split())[:100]
    state = ' '.join((form.get('shipping_state') or '').split())[:50]
    zip_code = ' '.join((form.get('shipping_zip') or '').split())[:20]
    if ship and not (street and city and state and zip_code):
        return None, 'Please add the full address to ship to, or choose pickup.'

    production = build_item_production(
        product=product, size=size, color=color, placement='center_chest', quantity=1, design_name=design.title,
        design_id=design.id, aspect_w=float(design.width) if design.width else None,
        aspect_h=float(design.height) if design.height else None, has_front=True, customer_name=f'{first} {last}'.strip())
    front = (production or {}).get('front') or {}
    line = {'product_id': product.id, 'design_id': design.id, 'color': color, 'size': size, 'quantity': 1, 'unit_price': 0.0,
            'placement': 'center_chest', 'print_type': 'DTF', 'transfer_production': production,
            'print_width': front.get('width'), 'print_height': front.get('height')}
    order = Order(
        email=email, first_name=first, last_name=last, phone=(form.get('phone') or '').strip()[:20],
        fulfillment_method='shipping' if ship else 'pickup',
        shipping_recipient=f'{first} {last}'.strip() if ship else None, shipping_street=street if ship else None,
        shipping_city=city if ship else None, shipping_state=state if ship else None, shipping_zip=zip_code if ship else None,
        subtotal=0.0, shipping_cost=0.0, tax=0.0, total=0.0, payment_method='donation', payment_status='paid', amount_paid=0.0,
        paid_at=datetime.utcnow(), status='paid', production_stage='order_received', due_date=default_due_date(),
        occasion_note=f'Donation: {donation.recipient}'[:200],
    )
    db.session.add(order)
    db.session.flush()
    if not build_order_items(order, [line], rid=f'donation-{claim.id}'):
        db.session.rollback()
        return None, 'We could not save your choice. Please try again.'
    apply_order_defaults(order)
    claim.order_id = order.id
    claim.claimed_at = datetime.utcnow()
    claim.winner_name = claim.winner_name or f'{first} {last}'.strip()
    claim.winner_email = claim.winner_email or email
    db.session.commit()
    return order, None
