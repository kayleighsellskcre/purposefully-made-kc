"""Build name/number production PNGs from the saved layout snapshot."""
from io import BytesIO

from utils.personalization_layout import (
    render_snapshot_png,
    snapshot_from_item,
    validate_snapshot_png,
)


def personalized_png(app, item, piece, customer_name=None):
    """Return PNG bytes for the combined back, or a name/number crop."""
    snapshot = snapshot_from_item(item, customer_name=customer_name)
    if piece == 'name' and not snapshot.get('name'):
        return None
    if piece == 'number' and not snapshot.get('number'):
        return None
    if piece in ('name', 'number'):
        one = dict(snapshot)
        if piece == 'name':
            one['number'] = ''
            one['gap'] = 0
            one['combined_width'] = snapshot.get('name_width')
            one['combined_height'] = snapshot.get('name_height')
        else:
            one['name'] = ''
            one['gap'] = 0
            one['combined_width'] = snapshot.get('number_width')
            one['combined_height'] = snapshot.get('number_height')
        return render_snapshot_png(one)
    return render_snapshot_png(snapshot)


def combined_png_and_report(item, customer_name=None):
    snapshot = snapshot_from_item(item, customer_name=customer_name)
    data = render_snapshot_png(snapshot)
    ok, failures = validate_snapshot_png(snapshot, data)
    return data, snapshot, ok, failures
