"""SEO-friendly product slugs for /shop/product/<slug> and /shop/customize/<slug>."""
from __future__ import annotations

from slugify import slugify

from utils.product_filters import infer_brand
from utils.product_names import display_product_name

# Keep these off product slugs so a collision never shadows a real /shop/ route
# if we later add /shop/<slug> shortcuts.
RESERVED_PRODUCT_SLUGS = frozenset({
    'group-orders',
    'designs',
    'product',
    'customize',
    'favorites',
    'cart',
    'admin',
    'new',
    'index',
})

_LISTENER_REGISTERED = False


def slug_from_product(product):
    """Build the preferred slug from brand + customer-facing name."""
    brand = infer_brand(product) or ''
    name = display_product_name(product)
    brand_slug = slugify(brand) if brand else ''
    name_slug = slugify(name) if name else ''
    if brand_slug and name_slug.startswith(brand_slug):
        base = name_slug
    else:
        base = slugify(f'{brand} {name}'.strip())
    style = str(getattr(product, 'style_number', None) or '').strip()
    if not base:
        base = slugify(style) or 'product'
    if base.isdigit():
        base = slugify(f'style {style or base}') or f'style-{base}'
    return base[:180]


def unique_slug(base, taken, style_number=None):
    """Return a slug that is not reserved and not already used."""
    taken = taken if taken is not None else set()
    candidate = (base or 'product')[:200]
    if candidate in RESERVED_PRODUCT_SLUGS or candidate in taken or candidate.isdigit():
        style_part = slugify(str(style_number or '')) or 'style'
        candidate = f'{base}-{style_part}'[:200]
    original = candidate
    n = 2
    while candidate in RESERVED_PRODUCT_SLUGS or candidate in taken or candidate.isdigit():
        suffix = f'-{n}'
        candidate = f'{original[:200 - len(suffix)]}{suffix}'
        n += 1
    return candidate


def existing_slugs(session=None, exclude_id=None):
    from models import Product

    query = Product.query.with_entities(Product.slug).filter(Product.slug.isnot(None))
    if exclude_id:
        query = query.filter(Product.id != exclude_id)
    taken = {slug for (slug,) in query.all() if slug}
    if session is not None:
        for obj in list(session.new) + list(session.dirty):
            if isinstance(obj, Product) and obj.slug:
                taken.add(obj.slug)
    return taken


def assign_product_slug(product, taken=None):
    """Set product.slug when missing. Mutates `taken` when provided."""
    current = (getattr(product, 'slug', None) or '').strip()
    if current:
        if taken is not None:
            taken.add(current)
        return current
    if taken is None:
        from models import db
        taken = existing_slugs(db.session, exclude_id=getattr(product, 'id', None))
    slug = unique_slug(
        slug_from_product(product),
        taken,
        getattr(product, 'style_number', None),
    )
    product.slug = slug
    taken.add(slug)
    return slug


def backfill_product_slugs():
    """Assign slugs to every catalog row that is still blank. Safe to re-run."""
    from models import Product, db

    products = Product.query.filter(
        (Product.slug.is_(None)) | (Product.slug == '')
    ).order_by(Product.id).all()
    if not products:
        return 0
    taken = existing_slugs(db.session)
    for product in products:
        assign_product_slug(product, taken=taken)
    db.session.commit()
    return len(products)


def register_product_slug_listener():
    """Fill slugs on insert/update so admin syncs and tests stay covered."""
    global _LISTENER_REGISTERED
    if _LISTENER_REGISTERED:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from models import Product

    @event.listens_for(Session, 'before_flush')
    def _ensure_product_slugs(session, _flush_context, _instances):
        pending = [
            obj for obj in list(session.new) + list(session.dirty)
            if isinstance(obj, Product) and not (getattr(obj, 'slug', None) or '').strip()
        ]
        if not pending:
            return
        taken = existing_slugs(session)
        for product in pending:
            assign_product_slug(product, taken=taken)

    _LISTENER_REGISTERED = True
