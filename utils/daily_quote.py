"""The daily quote: one message per calendar day, the same for every visitor."""
import time
from datetime import date

_CACHE = {'day': None, 'text': None, 'at': 0.0}
_TTL_SECONDS = 600


def todays_quote():
    """Today's quote, or None. Looked up at most once every ten minutes."""
    today = date.today()
    now = time.time()
    if _CACHE['day'] == today and now - _CACHE['at'] < _TTL_SECONDS:
        return _CACHE['text']
    text = None
    try:
        day_index = (today - date(today.year, 1, 1)).days
        try:
            from models import Affirmation
            rows = (Affirmation.query.filter_by(is_active=True)
                    .order_by(Affirmation.sort_order, Affirmation.id).all())
            if rows:
                from affirmations_seed import normalize_affirmation_text
                text = normalize_affirmation_text(rows[day_index % len(rows)].text)
        except Exception:
            pass
        if not text:
            from affirmations_seed import AFFIRMATIONS, normalize_affirmation_text
            text = normalize_affirmation_text(AFFIRMATIONS[day_index % len(AFFIRMATIONS)])
    except Exception:
        text = None
    _CACHE.update(day=today, text=text, at=now)
    return text
