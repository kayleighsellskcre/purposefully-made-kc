"""Display-only color name cleanup. Stored catalog values are left untouched."""
import re

_TEST_KEYS = {
    'test', 'testcolor', 'testcolour', 'testing', 'dummy', 'placeholder',
}

_GLUED_SUFFIXES = (
    'heathered', 'heather', 'marble', 'camo', 'frost', 'slub', 'triblend',
)


def _compact(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').lower())


def _looks_like_test(raw, compact):
    if compact in _TEST_KEYS:
        return True
    return bool(re.search(r'\btest(color|colour)?\b', raw or '', flags=re.I))


def _split_known_words(text):
    compact = _compact(text)
    if not compact:
        return ''
    for suffix in _GLUED_SUFFIXES:
        if compact.endswith(suffix) and len(compact) > len(suffix):
            return f'{compact[:-len(suffix)]} {suffix}'
    return text.strip()


def display_color_name(raw):
    """Readable label for a supplier color, or None to hide it."""
    text = re.sub(r'[\s_/,-]+', ' ', (raw or '').strip())
    text = re.sub(r'\bdtg\b', '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    compact = _compact(text)
    if not compact or _looks_like_test(raw, compact):
        return None
    if ' ' not in text:
        split = _split_known_words(text)
        if split:
            text = split
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return None
    return text.title()


def color_match_key(raw):
    """Case-insensitive merge key after display cleanup."""
    label = display_color_name(raw)
    return _compact(label) if label else None


def unique_display_colors(raw_names):
    """Deduplicated, sorted display names. Test and empty values are dropped."""
    best = {}
    for raw in raw_names or []:
        label = display_color_name(raw)
        key = color_match_key(raw)
        if not label or not key:
            continue
        previous = best.get(key)
        if previous is None or label.count(' ') > previous.count(' '):
            best[key] = label
    return [best[key] for key in sorted(best, key=lambda item: best[item].lower())]
