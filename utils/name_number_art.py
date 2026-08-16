"""Build name/number production PNGs from the saved layout snapshot.

300 DPI files are generated only when an admin explicitly saves a transfer.
Page loads must never call this.
"""
import logging
import threading
import time
from collections import OrderedDict

from utils.personalization_layout import (
    render_snapshot_png,
    snapshot_from_item,
    validate_snapshot_png,
)

_log = logging.getLogger(__name__)
_CACHE_MAX = 24
_CACHE = OrderedDict()
_CACHE_GUARD = threading.Lock()
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _item_lock(key):
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _mem_kb():
    try:
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        return None


def _cache_key(item_id, piece, snapshot):
    return (
        item_id,
        piece,
        snapshot.get('layout_version'),
        snapshot.get('name'),
        snapshot.get('number'),
        snapshot.get('name_height'),
        snapshot.get('number_height'),
        snapshot.get('gap'),
        snapshot.get('condense'),
        snapshot.get('number_scale'),
        snapshot.get('font'),
    )


def _cache_get(key):
    with _CACHE_GUARD:
        data = _CACHE.get(key)
        if data is not None:
            _CACHE.move_to_end(key)
        return data


def _cache_put(key, data):
    with _CACHE_GUARD:
        _CACHE[key] = data
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _piece_snapshot(snapshot, piece):
    if piece == 'name':
        one = dict(snapshot)
        one['number'] = ''
        one['gap'] = 0
        one['combined_width'] = snapshot.get('name_width')
        one['combined_height'] = snapshot.get('name_height')
        return one
    if piece == 'number':
        one = dict(snapshot)
        one['name'] = ''
        one['gap'] = 0
        one['combined_width'] = snapshot.get('number_width')
        one['combined_height'] = snapshot.get('number_height')
        return one
    return snapshot


def personalized_png(app, item, piece, customer_name=None):
    """Return PNG bytes for the combined back, or a name/number crop."""
    data, _snapshot = generate_personalized_png(app, item, piece, customer_name=customer_name)
    return data


def generate_personalized_png(app, item, piece, customer_name=None):
    """Render one transfer. Safe to call from the Save endpoint only."""
    snapshot = snapshot_from_item(item, customer_name=customer_name)
    if piece == 'name' and not snapshot.get('name'):
        return None, snapshot
    if piece == 'number' and not snapshot.get('number'):
        return None, snapshot

    key = _cache_key(item.id, piece, snapshot)
    cached = _cache_get(key)
    if cached is not None:
        _log.info(
            'dtf cache-hit item=%s piece=%s order_item=%s bytes=%s',
            getattr(item, 'id', None), piece, getattr(item, 'id', None), len(cached),
        )
        return cached, snapshot

    lock = _item_lock(key)
    with lock:
        cached = _cache_get(key)
        if cached is not None:
            return cached, snapshot
        started = time.monotonic()
        mem_before = _mem_kb()
        try:
            data = render_snapshot_png(_piece_snapshot(snapshot, piece))
        except Exception as exc:
            _log.exception(
                'dtf generate-failed item=%s piece=%s name=%s number=%s '
                'name_h=%s number_h=%s gap=%s mem_kb=%s duration_ms=%s error=%s',
                getattr(item, 'id', None),
                piece,
                snapshot.get('name'),
                snapshot.get('number'),
                snapshot.get('name_height'),
                snapshot.get('number_height'),
                snapshot.get('gap'),
                _mem_kb(),
                int((time.monotonic() - started) * 1000),
                exc,
            )
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        _log.info(
            'dtf generate-ok item=%s piece=%s name=%s number=%s '
            'name_h=%s number_h=%s gap=%s bytes=%s duration_ms=%s '
            'mem_kb_before=%s mem_kb_after=%s',
            getattr(item, 'id', None),
            piece,
            snapshot.get('name'),
            snapshot.get('number'),
            snapshot.get('name_height'),
            snapshot.get('number_height'),
            snapshot.get('gap'),
            len(data) if data else 0,
            duration_ms,
            mem_before,
            _mem_kb(),
        )
        if data:
            _cache_put(key, data)
        return data, snapshot


def combined_png_and_report(item, customer_name=None):
    snapshot = snapshot_from_item(item, customer_name=customer_name)
    data = render_snapshot_png(snapshot)
    ok, failures = validate_snapshot_png(snapshot, data)
    return data, snapshot, ok, failures
