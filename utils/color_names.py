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
    if name in FAMILY_SWATCHES:
        return FAMILY_SWATCHES[name]
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


def color_in_allowed_set(name, allowed):
    """True when a stored color matches an allowed display or supplier name."""
    if allowed is None:
        return True
    name_key = color_match_key(name)
    raw = (name or '').strip().lower()
    for item in allowed:
        if color_match_key(item) and color_match_key(item) == name_key:
            return True
        if (item or '').strip().lower() == raw:
            return True
    return False


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


# ── Color family grouping (round 2 audit item 8, tightened later) ──────────
# 458+ colors in one flat <select> was unusable. These keyword sets bucket
# each display name into a family. The shop filter now offers the families
# (with swatches) instead of every shade. Exact-color query values such as
# ?color=Navy still match one shade so older links keep working.

FAMILY_ORDER = [
    'Blacks and Grays', 'Whites and Creams', 'Blues', 'Greens',
    'Reds and Pinks', 'Purples', 'Yellows and Oranges', 'Browns and Neutrals',
    'Patterns and Camo', 'Other Colors',
]

FAMILY_SHORT = {
    'Blacks and Grays': 'Black',
    'Whites and Creams': 'White',
    'Blues': 'Blue',
    'Greens': 'Green',
    'Reds and Pinks': 'Red',
    'Purples': 'Purple',
    'Yellows and Oranges': 'Gold',
    'Browns and Neutrals': 'Neutral',
    'Patterns and Camo': 'Pattern',
    'Other Colors': 'Other',
}

FAMILY_SWATCHES = {
    'Blacks and Grays': '#36454f',
    'Whites and Creams': '#f5f0e1',
    'Blues': '#1e3a5f',
    'Greens': '#556b2f',
    'Reds and Pinks': '#c41e3a',
    'Purples': '#6b3fa0',
    'Yellows and Oranges': '#e67e22',
    'Browns and Neutrals': '#8b6914',
    'Patterns and Camo': '#5c6b4f',
    'Other Colors': '#7f6c50',
}

# Any of these appearing anywhere in the name wins outright: a patterned or
# camo print is not usefully described by its dominant hue.
_PATTERN_WORDS = {
    'camo', 'camouflage', 'tie', 'dye', 'tiedye', 'marble', 'leopard',
    'reptile', 'stripe', 'striped', 'plaid', 'rainbow', 'spiral',
    'colorburst', 'houndstooth', 'tweed', 'acid', 'galaxy', 'multi',
}

# Words that modify a color but never identify one on their own - skipped
# during matching so e.g. "Royal Purple" is read as Purple, not stopped at
# "Royal" (itself handled below as ambiguous, not a modifier).
_MODIFIER_WORDS = {
    'heathered', 'triblend', 'blend', 'vintage', 'solid',
    'athletic', 'true', 'classic', 'dark', 'light', 'bright', 'neon',
    'safety', 'team', 'pro', 'fleck', 'slub', 'prism', 'blackout', 'soft',
    'dusty', 'hot', 'bubble', 'candy', 'cotton', 'fan', 'dyed', 'new',
    'old', 'mid', 'sun', 'desert', 'coyote', 'duck', 'deep', 'g', 'french',
    'national', 'heathers',
}

# Color-ish words that are too ambiguous to trust as a first match (they
# usually modify a real color word elsewhere in the same name), used only
# when nothing stronger is found anywhere in the name. Bare "Heather" is
# here rather than in the modifier list: on its own (no other color word in
# the name) it means heather grey in apparel catalogs far more often than
# not, so it is a fallback guess rather than a true no-op.
_LOW_PRIORITY_FAMILY = {
    'storm': 'Blacks and Grays', 'frost': 'Blues', 'ice': 'Blues',
    'mist': 'Blues', 'royal': 'Blues', 'stone': 'Browns and Neutrals',
    'heather': 'Blacks and Grays',
}

_FAMILY_WORDS = {
    'Blacks and Grays': {
        'black', 'gray', 'grey', 'charcoal', 'ash', 'slate', 'smoke',
        'graphite', 'asphalt', 'carbon', 'anthracite', 'gunmetal', 'nickel',
        'titanium', 'pepper', 'iron', 'coal', 'cement', 'granite',
        'concrete', 'shadow', 'silver', 'steel', 'midnight',
    },
    'Whites and Creams': {
        'white', 'cream', 'creme', 'ivory', 'natural', 'bone', 'oatmeal',
        'vanilla', 'porcelain', 'snow', 'gardenia',
    },
    'Blues': {
        'blue', 'navy', 'sky', 'teal', 'aqua', 'aquatic', 'cyan', 'indigo',
        'denim', 'cobalt', 'powder', 'carolina', 'columbia', 'turquoise',
        'sapphire', 'cool', 'chambray', 'atlantic', 'pacific', 'caribbean',
        'lagoon', 'lapis', 'tropic', 'tropical', 'topaz', 'oxford', 'metro',
        'neptune', 'tidal', 'tundra', 'marine',
    },
    'Greens': {
        'green', 'forest', 'olive', 'kelly', 'mint', 'sage', 'hunter',
        'military', 'lime', 'army', 'basil', 'moss', 'evergreen', 'jade',
        'emerald', 'pistachio', 'eucalyptus', 'thyme', 'leaf', 'apple',
        'laurel', 'alpine', 'aloe', 'turf', 'spruce', 'glazed', 'honeydew',
        'lemongrass', 'pine', 'seafoam', 'celadon', 'mosstone',
        'greenstone',
    },
    'Reds and Pinks': {
        'red', 'pink', 'maroon', 'burgundy', 'wine', 'cardinal', 'coral',
        'rose', 'cherry', 'crimson', 'salmon', 'fuchsia', 'magenta',
        'raspberry', 'blush', 'garnet', 'ruby', 'scarlet', 'sangria',
        'watermelon', 'poppy', 'azalea', 'mauve', 'brick', 'rouge',
        'passionfruit', 'pomegranate', 'berry',
    },
    'Purples': {
        'purple', 'lavender', 'lilac', 'violet', 'plum', 'orchid', 'grape',
        'iris', 'wisteria', 'tanzanite',
    },
    'Yellows and Oranges': {
        'yellow', 'orange', 'gold', 'mustard', 'peach', 'amber',
        'tangerine', 'banana', 'butter', 'citron', 'maize', 'ochre',
        'papaya', 'sunset', 'sunkissed', 'marmalade', 'autumn', 'lemon',
        'cantaloupe', 'peachy',
    },
    'Browns and Neutrals': {
        'brown', 'tan', 'khaki', 'beige', 'taupe', 'camel', 'chocolate',
        'coffee', 'mocha', 'sand', 'clay', 'terracotta', 'nude', 'chestnut',
        'cinnamon', 'espresso', 'russet', 'saddle', 'toast', 'rust',
        'latte', 'yam', 'woodland', 'heritage', 'vegas', 'cocoa',
        'sandstone',
    },
}


def color_family(display_name):
    """Which optgroup a display color name belongs under.

    Scans right to left so a qualifier-plus-hue name like "Slate Blue" or
    "Royal Purple" resolves to the trailing, more specific color word
    rather than the first word encountered.
    """
    text = (display_name or '').lower()
    words = re.findall(r"[a-z]+", text)
    if not words:
        return 'Other Colors'

    joined = ' '.join(words)
    if any(w in _PATTERN_WORDS for w in words) or 'tie dye' in joined:
        return 'Patterns and Camo'

    for word in reversed(words):
        if word in _MODIFIER_WORDS:
            continue
        for family, keywords in _FAMILY_WORDS.items():
            if word in keywords:
                return family

    for word in reversed(words):
        if word in _LOW_PRIORITY_FAMILY:
            return _LOW_PRIORITY_FAMILY[word]

    return 'Other Colors'


def grouped_colors_by_family(display_names):
    """[(family, [colors]), ...] in FAMILY_ORDER, skipping empty families."""
    buckets = {family: [] for family in FAMILY_ORDER}
    for name in display_names or []:
        buckets[color_family(name)].append(name)
    return [(family, buckets[family]) for family in FAMILY_ORDER if buckets[family]]


def family_short_label(family):
    return FAMILY_SHORT.get(family, family)


def family_swatch_hex(family):
    return FAMILY_SWATCHES.get(family, '#7f6c50')


def selected_color_family(selected):
    """Family to highlight in the shop filter for a ?color= value."""
    if not selected:
        return ''
    if selected in FAMILY_ORDER:
        return selected
    label = display_color_name(selected) or selected
    return color_family(label)


def parse_color_filters(raw_values):
    """Unique, non-empty color query values, first-seen order."""
    seen = set()
    out = []
    for value in raw_values or []:
        cleaned = (value or '').strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def selected_color_families(filter_values):
    """Families to highlight for one or more ?color= values."""
    families = []
    for value in filter_values or []:
        family = selected_color_family(value)
        if family and family not in families:
            families.append(family)
    return families


def color_matches_filter(raw_name, filter_value):
    """True when a stored variant belongs to a family or exact color filter."""
    if not filter_value:
        return True
    if filter_value in FAMILY_ORDER:
        label = display_color_name(raw_name) or (raw_name or '')
        return color_family(label) == filter_value
    wanted = color_match_key(filter_value)
    return bool(wanted) and color_match_key(raw_name) == wanted


def color_matches_any_filter(raw_name, filter_values):
    """True when a stored variant belongs to any selected family or shade."""
    if not filter_values:
        return True
    return any(color_matches_filter(raw_name, value) for value in filter_values)


def filter_carousel_to_color_filters(carousel, filter_values):
    """Keep only carousel slides that match the selected color filters."""
    if not filter_values:
        return list(carousel or [])
    return [
        item for item in (carousel or [])
        if color_matches_any_filter(item.get('color_name'), filter_values)
    ]
