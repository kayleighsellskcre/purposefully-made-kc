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


_SWATCH_HEX = {
    'navy': '#1e3a5f', 'black': '#000000', 'white': '#ffffff', 'red': '#c41e3a',
    'royal': '#4169e1', 'true royal': '#4169e1', 'royal blue': '#4169e1',
    'team purple': '#4b0082', 'purple': '#800080', 'heather': '#9e9e9e',
    'heather gray': '#9e9e9e', 'heather grey': '#9e9e9e',
    'grey': '#808080', 'gray': '#808080', 'ash': '#b2beb5', 'charcoal': '#36454f',
    'terracotta': '#e2725b', 'toast': '#c4a484', 'forest': '#228b22', 'kelly': '#4cbb17',
    'aqua': '#00ffff', 'teal': '#008080', 'maroon': '#800000', 'burgundy': '#800020',
    'gold': '#ffd700', 'yellow': '#ffff00', 'orange': '#ff8c00', 'pink': '#ffc0cb',
    'lime': '#32cd32', 'mint': '#98ff98', 'sky': '#87ceeb', 'baby blue': '#89cff0',
    'berry': '#8e3a59', 'asphalt': '#3d3d3d', 'athletic heather': '#b8b8b8',
    'natural': '#f3ead3', 'sand': '#c2b280', 'olive': '#556b2f', 'military': '#4b5320',
    'cardinal': '#8c1515', 'carolina': '#4b9cd3', 'indigo': '#3f00ff',
    'cream': '#fffdd0', 'ivory': '#fffff0', 'rust': '#b7410e', 'wine': '#722f37',
    'coral': '#ff7f50', 'lilac': '#c8a2c8', 'lavender': '#e6e6fa', 'mustard': '#ffdb58',
    'peach': '#ffcba4', 'rose': '#ff66cc', 'tan': '#d2b48c', 'khaki': '#c3b091',
    'storm': '#4f5b66', 'slate': '#708090', 'silver': '#c0c0c0', 'brown': '#6f4e37',
    'green': '#228b22', 'blue': '#2a52be', 'camo': '#5c6b4f',
}


def swatch_hex(name, supplied=None):
    """Supplier hex if present, otherwise a name lookup. Never writes to the DB."""
    raw = (supplied or '').strip()
    if raw:
        if not raw.startswith('#'):
            raw = '#' + raw
        if re.fullmatch(r'#[0-9a-fA-F]{3,8}', raw):
            return raw
    label = display_color_name(name) or (name or '')
    key = label.lower().strip()
    if key in _SWATCH_HEX:
        return _SWATCH_HEX[key]
    compact = key.replace(' ', '')
    if compact in _SWATCH_HEX:
        return _SWATCH_HEX[compact]
    for part in reversed(key.split()):
        if part in _SWATCH_HEX:
            return _SWATCH_HEX[part]
    return None


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
