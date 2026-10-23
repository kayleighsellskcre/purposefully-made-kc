"""What the public sees of customer reviews: only approved ones, and photos only with permission."""
import time

_TTL_SECONDS = 120
_CACHE = {'at': 0.0, 'has': False}


def approved(limit=120):
    """Approved reviews as plain dicts, newest first. Photos are included only when the customer allowed it."""
    try:
        from models import Review
        rows = Review.query.filter_by(status='approved').order_by(Review.created_at.desc()).limit(limit).all()
    except Exception:
        return []
    out = []
    for r in rows:
        text = (r.body or '').strip()
        photos = r.photo_urls() if r.photos_ok else []
        if not text and not photos:
            continue
        occasion = ''
        try:
            occasion = (r.order.occasion_note or '') if r.order is not None else ''
        except Exception:
            pass
        out.append({'name': r.name, 'occasion': occasion, 'text': text, 'photos': photos, 'photo': photos[0] if photos else ''})
    return out


def tiles(reviews):
    """Flatten reviews into collage tiles: a photo tile per photo (the first carries the words), a quote tile for words alone."""
    out = []
    for r in reviews:
        if r['photos']:
            for i, url in enumerate(r['photos']):
                out.append({'kind': 'photo', 'url': url, 'name': r['name'], 'text': r['text'] if i == 0 else '',
                            'occasion': r['occasion'] if i == 0 else ''})
        else:
            out.append({'kind': 'quote', 'name': r['name'], 'text': r['text'], 'occasion': r['occasion']})
    return out


def has_reviews():
    """True when at least one approved review can be shown. Cached briefly so every page can ask."""
    now = time.time()
    if now - _CACHE['at'] < _TTL_SECONDS:
        return _CACHE['has']
    _CACHE.update(at=now, has=bool(approved(limit=1)))
    return _CACHE['has']


def clear_cache():
    _CACHE['at'] = 0.0
