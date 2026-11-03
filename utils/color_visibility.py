"""Which garment colors the shop may show for a product.

The supplier is the only source of truth: the nightly check (services/color_availability.py) records the colors
SanMar or S&S no longer list for the exact style, or list with zero stock in every size. Those never show.
Display only: nothing here deletes a color, so past orders and saved designs keep their color names.
"""
from utils.json_fields import parse_json_list
from utils.stock import color_key


def _keys(value):
    return {color_key(name) for name in parse_json_list(value) if color_key(name)}


def visibility_rules(product):
    """Set of color keys the supplier check has hidden for this product."""
    return _keys(getattr(product, 'supplier_hidden_colors', None))


def color_is_visible(color_name, hidden):
    key = color_key(color_name)
    return bool(key) and key not in hidden


def visible_color_names(product, names):
    hidden = visibility_rules(product)
    return [name for name in names if color_is_visible(name, hidden)]


def visible_pair_filter(product_ids):
    """Return keep(product_id, color_name) for admin color pickers that read ProductColorVariant rows directly."""
    from models import Product, db

    ids = list({pid for pid in product_ids if pid})
    hidden = {}
    if ids:
        rows = db.session.query(Product.id, Product.supplier_hidden_colors).filter(Product.id.in_(ids)).all()
        hidden = {pid: _keys(value) for pid, value in rows}

    def keep(product_id, color_name):
        return color_is_visible(color_name, hidden.get(product_id, set()))

    return keep
