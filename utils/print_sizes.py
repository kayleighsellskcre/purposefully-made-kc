"""Central transfer sizing — the only place print measurements live.

Front/standard designs are ordered by WIDTH from the approved youth/adult
chart. Personalized back names and numbers are ordered by HEIGHT.

Do not duplicate these numbers in templates or routes. Preview, cart,
order records, production summaries, and admin displays all call these
functions.
"""

import re

# ---------------------------------------------------------------------------
# Approved front-design width chart (inches). Do not replace or invent new
# center-chest/center-back widths. Kayleigh signed this chart off.
# Youth: YS 7.5", YM 8", YL 8.5", YXL 9"
# Adult: XS 9", S 9.5", M 10", L 10.5", XL 11", 2XL 11.25", 3XL+ 11.75"
# ---------------------------------------------------------------------------
SIZE_PRINT_WIDTH_ADULT = {
    'XS': 9.0, 'S': 9.5, 'M': 10.0, 'L': 10.5,
    'XL': 11.0, '2XL': 11.25, 'XXL': 11.25,
    '3XL': 11.75, 'XXXL': 11.75, '4XL': 11.75, '5XL': 11.75,
}
SIZE_PRINT_WIDTH_YOUTH = {
    'YS': 7.5, 'YM': 8.0, 'YL': 8.5, 'YXL': 9.0,
    # When youth product uses adult size labels (S, M, L, XL), map to youth dimensions
    'S': 7.5, 'M': 8.0, 'L': 8.5, 'XL': 9.0,
}
# Combined for backward compatibility
SIZE_PRINT_WIDTH = {**SIZE_PRINT_WIDTH_YOUTH, **SIZE_PRINT_WIDTH_ADULT}

# Map adult size labels to youth equivalents (for youth products)
ADULT_TO_YOUTH_SIZE = {'XS': 'YS', 'S': 'S', 'M': 'M', 'L': 'L', 'XL': 'XL'}

YOUTH_SIZE_PREFIXES = ('YS', 'YM', 'YL', 'YXL', 'YOUTH')

# Existing placement CSS is 30% center / 12% left-right chest (12/30 = 0.4).
# Left/right chest transfers use that same ratio of the approved width chart.
PLACEMENT_WIDTH_FACTOR = {
    'center_chest': 1.0,
    'center_back': 1.0,
    'full_front': 1.0,
    'full_back': 1.0,
    'left_chest': 0.4,
    'right_chest': 0.4,
    'sleeve': 0.3,
}

# Hoodie logos sit above the kangaroo pocket. Keep the signed-off chart for
# tees/crewnecks, and print hoodie logos 1" narrower than that chart width.
# Personalized back name/number still uses the full chart as the safe max.
HOODIE_PRINT_WIDTH_REDUCTION_IN = 1.0
HOODIE_PRINT_WIDTH_MIN_IN = 6.0

# Personalized back — ordered by HEIGHT. Kayleigh's size-band chart.
# name + gap + number = total. Do not invent other heights.
# Fallback aliases for older callers (adult S–2XL band).
NAME_HEIGHT_ADULT = 2.0
NAME_HEIGHT_YOUTH = 1.5
NUMBER_HEIGHT_ADULT = 7.0
NUMBER_HEIGHT_YOUTH = 5.5
NAME_NUMBER_GAP_ADULT = 3.0
NAME_NUMBER_GAP_YOUTH = 2.5

# Safe printable area must clear the largest layout in each category.
SAFE_PRINT_HEIGHT_ADULT = 15.5
SAFE_PRINT_HEIGHT_YOUTH = 12.5
SAFE_PRINT_HEIGHT_TODDLER = 9.0
SAFE_PRINT_HEIGHT_BABY = 7.0

# (name_height, gap, number_height) — inches
BACK_LAYOUT_BANDS = (
    {'category': 'baby', 'label': 'Newborn–3M', 'name': 0.75, 'gap': 1.00, 'number': 2.50},
    {'category': 'baby', 'label': '6M–12M', 'name': 1.00, 'gap': 1.25, 'number': 3.00},
    {'category': 'baby', 'label': '18M–24M', 'name': 1.00, 'gap': 1.50, 'number': 3.50},
    {'category': 'toddler', 'label': '2T', 'name': 1.25, 'gap': 1.50, 'number': 4.00},
    {'category': 'toddler', 'label': '3T', 'name': 1.25, 'gap': 1.75, 'number': 4.50},
    {'category': 'toddler', 'label': '4T–5T', 'name': 1.25, 'gap': 2.00, 'number': 4.50},
    {'category': 'youth', 'label': 'Youth XS', 'name': 1.25, 'gap': 2.00, 'number': 4.50},
    {'category': 'youth', 'label': 'Youth S–M', 'name': 1.50, 'gap': 2.50, 'number': 5.50},
    {'category': 'youth', 'label': 'Youth L–XL', 'name': 1.75, 'gap': 3.00, 'number': 6.00},
    {'category': 'adult', 'label': 'Adult S–2XL', 'name': 2.00, 'gap': 3.00, 'number': 7.00},
    {'category': 'adult', 'label': 'Adult 3XL–4XL', 'name': 2.00, 'gap': 3.50, 'number': 7.50},
)

# A two-digit number reads far wider than a one-digit number at the same
# height. Keep the height, pull the digits closer, and squeeze the pair as one
# centered group until the visible number is this share of its natural width.
TWO_DIGIT_WIDTH_SCALE = 0.875
# Extra tracking between the two digits, as a fraction of the em, and the ink
# gap that must survive it. Athletic faces are drawn with almost no side
# bearing, so the customizer backs the tracking off before the digits touch.
TWO_DIGIT_TRACKING_EM = -0.02
MIN_DIGIT_GAP_EM = 0.012

# Preview: adult M 10" center print is the 30% mockup overlay.
PREVIEW_REF_WIDTH_IN = 10.0
PREVIEW_REF_PCT = 30.0

# ---------------------------------------------------------------------------
# Preview calibration only — never a production measurement.
#
# Nominal garment body length (high point shoulder to hem, inches). The
# customizer measures the shirt in the mockup photo, divides its height by the
# body length for the selected size, and gets pixels per inch. That is how a
# 2" name is drawn 2" tall against the garment instead of a percentage of the
# white product card behind it.
# ---------------------------------------------------------------------------
GARMENT_BODY_LENGTH_IN = {
    'adult': {
        'XS': 27.0, 'S': 28.0, 'M': 29.0, 'L': 30.0, 'XL': 31.0,
        '2XL': 32.0, '3XL': 33.0, '4XL': 34.0, '5XL': 34.5, '6XL': 35.0,
    },
    'youth': {
        'YXS': 19.0, 'YS': 20.5, 'YM': 22.0, 'YL': 23.5, 'YXL': 25.0,
        # Youth garments often carry plain S/M/L/XL labels.
        'XS': 19.0, 'S': 20.5, 'M': 22.0, 'L': 23.5, 'XL': 25.0,
        '2': 19.0, '4': 19.0, '6': 20.5, '8': 22.0, '10': 22.0,
        '12': 23.5, '14': 23.5, '16': 25.0,
    },
    'toddler': {'2T': 15.5, '3T': 16.5, '4T': 17.5, '5T': 18.5},
    'baby': {
        'NB': 12.5, 'PREMIE': 11.5, '0M': 12.5, '3M': 13.0, '6M': 13.5,
        '9M': 14.0, '12M': 14.5, '18M': 15.5, '24M': 16.5,
    },
}
GARMENT_BODY_LENGTH_DEFAULT = {
    'adult': 29.0, 'youth': 22.0, 'toddler': 16.5, 'baby': 14.0,
}

# Top of a back name sits this far below the shoulder seam, as a share of body
# length (adult M: 29" x 0.12 = 3.5"). Keeps the layout on the upper back.
BACK_COLLAR_DROP_RATIO = 0.12

# Athletic block fonts. char_width and the spacings are fractions of the font's
# em size; cap_ratio is how much of that em the visible capital letters fill.
# Chart heights are visible letter heights, so an em is height / cap_ratio.
# Used only when the customizer did not send a canvas-measured width.
FONT_METRICS = {
    'Bebas Neue': {'char_width': 0.48, 'letter_spacing': 0.06, 'number_spacing': 0.02, 'cap_ratio': 0.73},
    'Oswald': {'char_width': 0.55, 'letter_spacing': 0.07, 'number_spacing': 0.04, 'cap_ratio': 0.72},
    'Anton': {'char_width': 0.52, 'letter_spacing': 0.05, 'number_spacing': 0.02, 'cap_ratio': 0.73},
    'Teko': {'char_width': 0.50, 'letter_spacing': 0.06, 'number_spacing': 0.03, 'cap_ratio': 0.66},
    'Jersey M54': {'char_width': 0.58, 'letter_spacing': 0.05, 'number_spacing': 0.02, 'cap_ratio': 0.72},
    'Varsity Regular': {'char_width': 0.62, 'letter_spacing': 0.04, 'number_spacing': 0.02, 'cap_ratio': 0.70},
    'Varsity Regular Solid': {'char_width': 0.58, 'letter_spacing': 0.04, 'number_spacing': 0.02, 'cap_ratio': 0.72},
}
DEFAULT_CAP_RATIO = 0.72

PLACEMENT_LABELS = {
    'center_chest': 'Center Chest',
    'center_back': 'Center Back',
    'left_chest': 'Left Chest',
    'right_chest': 'Right Chest',
    'full_front': 'Full Front',
    'full_back': 'Full Back',
    'sleeve': 'Sleeve',
}

_YOUTH_AGE_GROUPS = frozenset(('youth', 'toddler', 'baby', 'kids', 'kid', 'infant'))
_YOUTH_NAME_TOKENS = ('youth', 'toddler', 'infant', 'baby', 'kids', 'kid')


def _is_youth_size(size):
    """Check if size unambiguously indicates youth (YS, YM, YL, YXL or numeric 2-16).
    S, M, L, XL alone are ambiguous - use product data for those."""
    if not size:
        return False
    s = str(size).strip().upper()
    if s in ('YS', 'YM', 'YL', 'YXL'):
        return True
    if any(s.startswith(p) for p in YOUTH_SIZE_PREFIXES):
        return True
    if s in ('2', '4', '6', '8', '10', '12', '14', '16'):
        return True
    return False


def classify_age(product=None, size=None):
    """Return 'youth' or 'adult'. Prefer structured product.age_group."""
    if product is not None:
        age = (getattr(product, 'age_group', None) or '').strip().lower()
        if age in _YOUTH_AGE_GROUPS:
            return 'youth'
        if age == 'adult':
            return 'adult'
        category = (getattr(product, 'category', None) or '').strip().lower()
        if category in _YOUTH_AGE_GROUPS:
            return 'youth'
        name = (getattr(product, 'name', None) or '').lower()
        if any(token in name for token in _YOUTH_NAME_TOKENS):
            return 'youth'
    if _is_youth_size(size):
        return 'youth'
    return 'adult'


def classify_category(product=None, size=None):
    """Return baby, toddler, youth, or adult."""
    if product is not None:
        age = (getattr(product, 'age_group', None) or '').strip().lower()
        if age in ('baby', 'infant'):
            return 'baby'
        if age == 'toddler':
            return 'toddler'
        if age in ('youth', 'kids', 'kid'):
            return 'youth'
        if age == 'adult':
            return 'adult'
        category = (getattr(product, 'category', None) or '').strip().lower()
        if category in ('baby', 'infant'):
            return 'baby'
        if category in ('toddler', 'youth', 'adult'):
            return category
        name = (getattr(product, 'name', None) or '').lower()
        if any(token in name for token in ('infant', 'baby', 'onesie', 'newborn')):
            return 'baby'
        if 'toddler' in name:
            return 'toddler'
        if any(token in name for token in _YOUTH_NAME_TOKENS):
            return 'youth'
    key = _norm_back_size(size)
    if key in ('NB', 'NEWBORN', 'N', 'PREMIE', 'PREEMIE') or _month_start(key) is not None:
        return 'baby'
    if re.match(r'^\d+T$', key or ''):
        return 'toddler'
    if _is_youth_size(size) or (key or '').startswith('Y'):
        return 'youth'
    return classify_age(product, size)


def _norm_back_size(size):
    s = str(size or '').strip().upper()
    s = s.replace('X-LARGE', 'XL').replace('X LARGE', 'XL')
    s = s.replace('XX-LARGE', 'XXL').replace('XX LARGE', 'XXL')
    s = re.sub(r'(\d+)\s*[-/]\s*(\d+)\s*M', r'\1TO\2M', s)
    s = re.sub(r'[\s_\-]+', '', s)
    s = s.replace('YOUTH', 'Y').replace('TODDLER', '').replace('ADULT', '')
    s = s.replace('BABY', '').replace('INFANT', '').replace('MONTHS', 'M').replace('MONTH', 'M')
    aliases = {
        'NEWBORN': 'NB', 'PREEMIE': 'PREMIE',
        'XXL': '2XL', 'XXXL': '3XL', '2X': '2XL', '3X': '3XL', '4X': '4XL', '5X': '5XL',
        'YXXL': 'Y2XL', 'XSM': 'XS', 'XSMALL': 'XS', 'SM': 'S', 'SMALL': 'S',
        'MD': 'M', 'MED': 'M', 'MEDIUM': 'M', 'LG': 'L', 'LARGE': 'L',
        'XLG': 'XL', 'XLARGE': 'XL',
    }
    return aliases.get(s, s)


def _month_start(key):
    if key in ('NB', 'NEWBORN', 'N', 'PREMIE', 'PREEMIE', '0M'):
        return 0
    m = re.match(r'^(\d+)(?:TO(\d+))?M$', key or '')
    if m:
        return int(m.group(1))
    return None


def _layout_tuple(band):
    name, gap, number = band['name'], band['gap'], band['number']
    return {
        'category': band['category'],
        'label': band['label'],
        'name_height': name,
        'gap': gap,
        'number_height': number,
        'total_height': round(name + gap + number, 2),
    }


def back_layout(size=None, product=None):
    """Name / gap / number heights for this garment size. Source of truth."""
    category = classify_category(product, size)
    key = _norm_back_size(size)
    month = _month_start(key)

    if category == 'baby' or month is not None:
        if month is None or month <= 3:
            return _layout_tuple(BACK_LAYOUT_BANDS[0])
        if month <= 12:
            return _layout_tuple(BACK_LAYOUT_BANDS[1])
        return _layout_tuple(BACK_LAYOUT_BANDS[2])

    if category == 'toddler' or re.match(r'^\d+T$', key or ''):
        if key == '2T':
            return _layout_tuple(BACK_LAYOUT_BANDS[3])
        if key == '3T':
            return _layout_tuple(BACK_LAYOUT_BANDS[4])
        return _layout_tuple(BACK_LAYOUT_BANDS[5])  # 4T–5T

    if category == 'youth' or (key or '').startswith('Y') or _is_youth_size(size):
        letter = key[1:] if (key or '').startswith('Y') and len(key) > 1 else key
        if letter in ('XS', 'XXS', '2XS') or key in ('2', '4'):
            return _layout_tuple(BACK_LAYOUT_BANDS[6])
        if letter in ('S', 'M') or key in ('6', '8', '10'):
            return _layout_tuple(BACK_LAYOUT_BANDS[7])
        if letter in ('L', 'XL', '2XL', 'XXL') or key in ('12', '14', '16'):
            return _layout_tuple(BACK_LAYOUT_BANDS[8])
        return _layout_tuple(BACK_LAYOUT_BANDS[7])

    # Adult — XS rides with S–2XL; 3XL+ uses the larger number/gap
    if key in ('3XL', '4XL', '5XL', '6XL', '7XL', 'XXXL'):
        return _layout_tuple(BACK_LAYOUT_BANDS[10])
    return _layout_tuple(BACK_LAYOUT_BANDS[9])


def garment_body_length_in(size=None, product=None):
    """Nominal shoulder-to-hem length for preview scaling. Not for production."""
    category = classify_category(product, size)
    table = GARMENT_BODY_LENGTH_IN.get(category, {})
    default = GARMENT_BODY_LENGTH_DEFAULT.get(category, 29.0)
    key = _norm_back_size(size)
    if key in table:
        return table[key]

    month = _month_start(key)
    if month is not None:
        baby = GARMENT_BODY_LENGTH_IN['baby']
        for months in sorted(int(k[:-1]) for k in baby if k.endswith('M') and k[:-1].isdigit()):
            if month <= months:
                return baby[f'{months}M']
        return baby['24M']

    if category == 'youth' and key.startswith('Y') and len(key) > 1:
        return table.get(key[1:], default)
    return default


def back_collar_drop_in(size=None, product=None):
    """How far below the shoulder seam the top of the name starts."""
    return garment_body_length_in(size, product) * BACK_COLLAR_DROP_RATIO


def is_hoodie(product=None):
    """True for hoodie / hooded garments, not crewneck sweatshirts."""
    if product is None:
        return False
    from utils.product_filters import infer_category
    return infer_category(product) == 'Hoodie'


def chart_width_for_size(size, product=None):
    """Approved youth/adult center-chest width. No hoodie pocket adjustment."""
    if not size:
        return None
    s = str(size).strip().upper()
    is_youth = classify_age(product, size) == 'youth'

    if is_youth:
        if s in SIZE_PRINT_WIDTH_YOUTH:
            return SIZE_PRINT_WIDTH_YOUTH[s]
        size_map_youth = {
            'YOUTH SMALL': 7.5, 'YOUTH MEDIUM': 8.0, 'YOUTH LARGE': 8.5, 'YOUTH XL': 9.0,
        }
        if s in size_map_youth:
            return size_map_youth[s]
        if s in ('2', '4', '6', '8', '10', '12', '14', '16'):
            return 7.5
        return 7.5
    if s in SIZE_PRINT_WIDTH_ADULT:
        return SIZE_PRINT_WIDTH_ADULT[s]
    size_map_adult = {
        'ADULT XSMALL': 9.0, 'ADULT SMALL': 9.5, 'ADULT MEDIUM': 10.0, 'ADULT LARGE': 10.5,
        'ADULT XLARGE': 11.0, 'ADULT XXLARGE': 11.25, 'ADULT XXXLARGE': 11.75,
    }
    if s in size_map_adult:
        return size_map_adult[s]
    if s.startswith('2') and 'XL' in s:
        return 11.25
    if any(s.startswith(x) for x in ('3', '4', '5')):
        return 11.75
    return None


def get_print_width_for_size(size, product=None):
    """Return logo/standard-transfer width in inches for a given size.

    Use youth dimensions (e.g. S=7.5", YS=7.5") when classify_age is youth.
    Width chart values are unchanged from the approved mapping except on
    hoodies, which print 1" narrower so the logo clears the kangaroo pocket.
    """
    width = chart_width_for_size(size, product)
    if width is None:
        return None
    if is_hoodie(product):
        return max(width - HOODIE_PRINT_WIDTH_REDUCTION_IN, HOODIE_PRINT_WIDTH_MIN_IN)
    return width


def placement_label(placement):
    if not placement:
        return 'Center Chest'
    return PLACEMENT_LABELS.get(placement, str(placement).replace('_', ' ').title())


def placement_width_factor(placement):
    if not placement:
        return 1.0
    return PLACEMENT_WIDTH_FACTOR.get(str(placement).strip().lower(), 1.0)


def safe_print_width(size, product=None, placement=None):
    """Max printable width for this garment size (center-chest chart width)."""
    width = chart_width_for_size(size, product)
    if width is None:
        width = 7.5 if classify_age(product, size) == 'youth' else 10.0
    # Chest logos use a smaller assigned width, but the safe max is still the
    # full chart width so a left-chest design is not flagged against 4".
    if placement in ('left_chest', 'right_chest', 'sleeve'):
        return width
    return width


def safe_print_height(product=None, size=None):
    category = classify_category(product, size)
    if category == 'baby':
        return SAFE_PRINT_HEIGHT_BABY
    if category == 'toddler':
        return SAFE_PRINT_HEIGHT_TODDLER
    if category == 'youth':
        return SAFE_PRINT_HEIGHT_YOUTH
    return SAFE_PRINT_HEIGHT_ADULT


def name_height_in(product=None, size=None):
    return back_layout(size, product)['name_height']


def number_height_in(product=None, size=None):
    return back_layout(size, product)['number_height']


def name_number_gap_in(product=None, size=None):
    return back_layout(size, product)['gap']


def inches(value, digits=2):
    """Round for display only. Keep raw floats for calculations."""
    if value is None:
        return None
    return round(float(value) + 0.0, digits)


def format_inches(value, digits=2):
    if value is None:
        return 'N/A'
    return f'{inches(value, digits):.{digits}f}'


def format_wh(width, height, digits=2):
    return f'{format_inches(width, digits)}\u2033 W \u00d7 {format_inches(height, digits)}\u2033 H'


def height_from_width(width, aspect_w, aspect_h):
    """Preserve aspect ratio: height = width * (h / w)."""
    if not width or not aspect_w:
        return width
    return float(width) * (float(aspect_h) / float(aspect_w))


def front_transfer_size(size, product=None, placement='center_chest', aspect_w=None, aspect_h=None):
    """Assigned front/standard transfer. Ordered by WIDTH from the chart."""
    chart_width = get_print_width_for_size(size, product)
    if chart_width is None:
        chart_width = 7.5 if classify_age(product, size) == 'youth' else 10.0
    width = chart_width * placement_width_factor(placement)
    if aspect_w and aspect_h:
        height = height_from_width(width, aspect_w, aspect_h)
    else:
        height = width
    max_h = safe_print_height(product, size)
    max_w = safe_print_width(size, product, placement)
    exceeds = bool(width > max_w + 0.001 or height > max_h + 0.001)
    return {
        'order_by': 'WIDTH',
        'width': width,
        'height': height,
        'width_display': inches(width),
        'height_display': inches(height),
        'exceeds_safe_area': exceeds,
        'safe_width': max_w,
        'safe_height': max_h,
    }


def estimate_text_width(text, height, font='Bebas Neue', kind='name'):
    """Fallback width when the customizer did not measure the rendered glyphs.

    `height` is the visible capital-letter height from the chart, so scale it
    back up to the font's em size before applying the per-character widths.
    """
    if not text or not height:
        return 0.0
    metrics = FONT_METRICS.get(font) or FONT_METRICS['Bebas Neue']
    chars = list(str(text))
    spacing_em = metrics['letter_spacing'] if kind == 'name' else metrics['number_spacing']
    em = float(height) / (metrics.get('cap_ratio') or DEFAULT_CAP_RATIO)
    char_w = em * metrics['char_width']
    gap = em * spacing_em
    return len(chars) * char_w + max(0, len(chars) - 1) * gap


def number_group_scale(number):
    """Horizontal scale applied to the number, treated as one centered group.

    Two digits get squeezed; one digit is left alone. Height never changes.
    """
    digits = len(str(number or '').strip())
    return TWO_DIGIT_WIDTH_SCALE if digits == 2 else 1.0


def back_name_number_size(size, product=None, name='', number='', font='Bebas Neue',
                          measured_name_width=None, measured_number_width=None):
    """Personalized back transfers. Ordered by HEIGHT. Width grows with the text.

    Measured widths are the natural rendered widths — the visible glyph bounds
    at the chart height before any squeeze — so the squeeze rules below stay
    the single source of truth for the final printed width.
    """
    layout = back_layout(size, product)
    n_h = layout['name_height']
    num_h = layout['number_height']
    gap = layout['gap']
    max_w = safe_print_width(size, product, 'center_back')

    name_text = (name or '').strip()
    number_text = (number or '').strip()

    if measured_name_width is not None and name_text:
        natural_name_w = float(measured_name_width)
    else:
        natural_name_w = estimate_text_width(name_text, n_h, font, 'name') if name_text else 0.0

    if measured_number_width is not None and number_text:
        natural_number_w = float(measured_number_width)
    else:
        natural_number_w = estimate_text_width(number_text, num_h, font, 'number') if number_text else 0.0

    condense = 1.0
    name_w = natural_name_w
    if name_text and natural_name_w > max_w + 0.001:
        condense = max_w / natural_name_w
        name_w = max_w

    number_digits = len(number_text)
    number_scale = number_group_scale(number_text) if number_text else 1.0
    number_w = natural_number_w * number_scale
    if number_text and number_w > max_w + 0.001:
        number_scale *= max_w / number_w
        number_w = max_w

    combined_w = max(name_w, number_w) if (name_text or number_text) else 0.0
    combined_h = 0.0
    if name_text and number_text:
        combined_h = n_h + gap + num_h
    elif name_text:
        combined_h = n_h
    elif number_text:
        combined_h = num_h

    exceeds = bool(combined_w > max_w + 0.001 or combined_h > safe_print_height(product, size) + 0.001)

    return {
        'order_by': 'HEIGHT',
        'layout_label': layout['label'],
        'category': layout['category'],
        'name_height': n_h,
        'name_width': name_w,
        'name_width_natural': natural_name_w,
        'number_height': num_h,
        'number_width': number_w,
        'number_width_natural': natural_number_w,
        'number_digits': number_digits,
        'number_scale': number_scale,
        'number_scale_percent': None if number_scale >= 0.999 else round((1.0 - number_scale) * 100, 1),
        'gap': gap,
        'combined_width': combined_w,
        'combined_height': combined_h,
        'condense': condense,
        'condense_percent': None if condense >= 0.999 else round((1.0 - condense) * 100, 1),
        'exceeds_safe_area': exceeds,
        'safe_width': max_w,
        'name_height_display': inches(n_h),
        'name_width_display': inches(name_w),
        'number_height_display': inches(num_h),
        'number_width_display': inches(number_w),
        'number_width_natural_display': inches(natural_number_w),
        'gap_display': inches(gap),
        'combined_width_display': inches(combined_w),
        'combined_height_display': inches(combined_h),
    }


def client_config(product=None):
    """JSON-safe config for the customizer. Same numbers the server uses."""
    age = classify_age(product)
    category = classify_category(product)
    return {
        'age_group': age,
        'category': category,
        'is_hoodie': is_hoodie(product),
        'hoodie_width_reduction': HOODIE_PRINT_WIDTH_REDUCTION_IN,
        'hoodie_width_min': HOODIE_PRINT_WIDTH_MIN_IN,
        'widths_adult': SIZE_PRINT_WIDTH_ADULT,
        'widths_youth': SIZE_PRINT_WIDTH_YOUTH,
        'placement_factors': PLACEMENT_WIDTH_FACTOR,
        'back_chart': [
            {
                'category': b['category'],
                'label': b['label'],
                'name': b['name'],
                'gap': b['gap'],
                'number': b['number'],
                'total': round(b['name'] + b['gap'] + b['number'], 2),
            }
            for b in BACK_LAYOUT_BANDS
        ],
        'name_height_adult': NAME_HEIGHT_ADULT,
        'name_height_youth': NAME_HEIGHT_YOUTH,
        'number_height_adult': NUMBER_HEIGHT_ADULT,
        'number_height_youth': NUMBER_HEIGHT_YOUTH,
        'gap_adult': NAME_NUMBER_GAP_ADULT,
        'gap_youth': NAME_NUMBER_GAP_YOUTH,
        'safe_height_adult': SAFE_PRINT_HEIGHT_ADULT,
        'safe_height_youth': SAFE_PRINT_HEIGHT_YOUTH,
        'preview_ref_width': PREVIEW_REF_WIDTH_IN,
        'preview_ref_pct': PREVIEW_REF_PCT,
        'fonts': FONT_METRICS,
        'default_cap_ratio': DEFAULT_CAP_RATIO,
        # Two-digit numbers: same height, tighter pair, narrower group.
        'two_digit_scale': TWO_DIGIT_WIDTH_SCALE,
        'two_digit_tracking_em': TWO_DIGIT_TRACKING_EM,
        'min_digit_gap_em': MIN_DIGIT_GAP_EM,
        # Preview scale: measured garment height / body length = pixels per inch.
        'body_lengths': GARMENT_BODY_LENGTH_IN,
        'body_length_defaults': GARMENT_BODY_LENGTH_DEFAULT,
        'collar_drop_ratio': BACK_COLLAR_DROP_RATIO,
    }


def build_item_production(
    *,
    product=None,
    size=None,
    color=None,
    placement=None,
    quantity=1,
    design_name=None,
    design_id=None,
    aspect_w=None,
    aspect_h=None,
    has_front=True,
    back_name=None,
    back_number=None,
    back_font=None,
    back_text_color=None,
    back_outline=None,
    back_outline_color=None,
    customer_name=None,
    measured_name_width=None,
    measured_number_width=None,
    garment_style=None,
):
    """Full production snapshot stored on the cart item and order line."""
    age = classify_age(product, size)
    style = garment_style or (getattr(product, 'name', None) if product is not None else None)
    qty = int(quantity or 1)
    payload = {
        'garment_style': style,
        'style_number': getattr(product, 'style_number', None) if product is not None else None,
        'age_group': age,
        'size': size,
        'color': color,
        'quantity': qty,
        'front': None,
        'back': None,
    }

    if has_front and placement != 'center_back':
        front = front_transfer_size(size, product, placement or 'center_chest', aspect_w, aspect_h)
        payload['front'] = {
            'kind': 'standard',
            'design_name': design_name,
            'design_id': design_id,
            'garment_style': style,
            'age_group': age,
            'size': size,
            'color': color,
            'placement': placement or 'center_chest',
            'placement_label': placement_label(placement or 'center_chest'),
            'order_by': 'WIDTH',
            'width': front['width'],
            'height': front['height'],
            'width_display': front['width_display'],
            'height_display': front['height_display'],
            'exceeds_safe_area': front['exceeds_safe_area'],
            'quantity': qty,
        }
    elif has_front and placement == 'center_back' and not (back_name or back_number):
        front = front_transfer_size(size, product, 'center_back', aspect_w, aspect_h)
        payload['front'] = {
            'kind': 'standard',
            'design_name': design_name,
            'design_id': design_id,
            'garment_style': style,
            'age_group': age,
            'size': size,
            'color': color,
            'placement': 'center_back',
            'placement_label': 'Center Back',
            'order_by': 'WIDTH',
            'width': front['width'],
            'height': front['height'],
            'width_display': front['width_display'],
            'height_display': front['height_display'],
            'exceeds_safe_area': front['exceeds_safe_area'],
            'quantity': qty,
        }

    if back_name or back_number:
        back = back_name_number_size(
            size, product,
            name=back_name, number=back_number, font=back_font or 'Bebas Neue',
            measured_name_width=measured_name_width,
            measured_number_width=measured_number_width,
        )
        payload['back'] = {
            'kind': 'personalized',
            'customer_name': customer_name,
            'name': (back_name or '').strip(),
            'number': (back_number or '').strip(),
            'font': back_font or 'Bebas Neue',
            'text_color': back_text_color,
            'outline': back_outline,
            'outline_color': back_outline_color,
            'garment_style': style,
            'age_group': age,
            'size': size,
            'color': color,
            'placement': 'center_back',
            'placement_label': 'Center Back',
            'order_by': 'HEIGHT',
            'layout_label': back.get('layout_label'),
            'category': back.get('category'),
            'name_height': back['name_height'],
            'name_width': back['name_width'],
            'name_width_natural': back['name_width_natural'],
            'number_height': back['number_height'],
            'number_width': back['number_width'],
            'number_width_natural': back['number_width_natural'],
            'number_digits': back['number_digits'],
            'number_scale': back['number_scale'],
            'number_scale_percent': back['number_scale_percent'],
            'gap': back['gap'],
            'combined_width': back['combined_width'],
            'combined_height': back['combined_height'],
            'condense': back['condense'],
            'condense_percent': back['condense_percent'],
            'exceeds_safe_area': back['exceeds_safe_area'],
            'name_height_display': back['name_height_display'],
            'name_width_display': back['name_width_display'],
            'number_height_display': back['number_height_display'],
            'number_width_display': back['number_width_display'],
            'number_width_natural_display': back['number_width_natural_display'],
            'gap_display': back['gap_display'],
            'combined_width_display': back['combined_width_display'],
            'combined_height_display': back['combined_height_display'],
            'quantity': qty,
        }
        from utils.personalization_layout import enrich_back_snapshot
        payload['back'] = enrich_back_snapshot(payload['back'])
    return payload


def production_from_stored(stored, quantity=None):
    """Refresh display rounding on a stored snapshot. Quantity can be updated."""
    if not stored:
        return None
    data = dict(stored)
    if quantity is not None:
        data['quantity'] = int(quantity)
        if data.get('front'):
            data['front'] = dict(data['front'])
            data['front']['quantity'] = int(quantity)
        if data.get('back'):
            data['back'] = dict(data['back'])
            data['back']['quantity'] = int(quantity)
    return data


def production_from_order_item(item, customer_name=None):
    """Stored snapshot if present, otherwise recompute from the line item."""
    stored = None
    raw = getattr(item, 'transfer_production', None)
    if raw:
        if isinstance(raw, dict):
            stored = raw
        else:
            try:
                import json
                stored = json.loads(raw)
            except Exception:
                stored = None
    if stored:
        return production_from_stored(stored, quantity=getattr(item, 'quantity', None))

    product = getattr(item, 'product', None)
    design = getattr(item, 'design', None)
    design_name = None
    aspect_w = aspect_h = None
    if design:
        design_name = design.title or design.original_filename or design.filename
        if design.width and design.height:
            aspect_w, aspect_h = design.width, design.height
    if not design_name:
        design_name = getattr(item, 'design_file_name', None)

    back = getattr(item, 'back_design_details', None) or {}
    has_front = bool(design or getattr(item, 'design_file_name', None) or getattr(item, 'design_id', None))
    if getattr(item, 'placement', None) == 'center_back' and (back.get('name') or back.get('number')):
        # Extra back name/number with a front design still counts as front+back.
        has_front = bool(design or getattr(item, 'design_id', None))

    return build_item_production(
        product=product,
        size=getattr(item, 'size', None),
        color=getattr(item, 'color', None),
        placement=getattr(item, 'placement', None),
        quantity=getattr(item, 'quantity', 1) or 1,
        design_name=design_name,
        design_id=getattr(item, 'design_id', None),
        aspect_w=aspect_w,
        aspect_h=aspect_h,
        has_front=has_front,
        back_name=back.get('name'),
        back_number=back.get('number'),
        back_font=back.get('font'),
        back_text_color=back.get('text_color'),
        back_outline=back.get('outline'),
        back_outline_color=back.get('outline_color'),
        customer_name=customer_name or back.get('customer_name'),
        # Natural widths, so the squeeze is applied once and not compounded.
        measured_name_width=back.get('name_width_natural') or back.get('name_width'),
        measured_number_width=back.get('number_width_natural') or back.get('number_width'),
        garment_style=getattr(item, 'product_name', None),
    )


def group_production_rows(rows, group_by='design'):
    """Group standard transfers; keep personalized names/numbers as their own rows."""
    standard = {}
    personalized = []
    for row in rows:
        qty = int(row.get('quantity') or 1)
        if row.get('kind') == 'personalized':
            personalized.append(dict(row))
            continue
        key = (
            str(row.get('design_id') or ''),
            str(row.get('design_name') or ''),
            inches(row.get('width')),
            inches(row.get('height')),
            str(row.get('placement') or ''),
            str(row.get('text_color') or ''),
        )
        if key not in standard:
            standard[key] = dict(row)
            standard[key]['quantity'] = qty
            standard[key]['sizes'] = [row.get('size')]
            standard[key]['colors'] = [row.get('color')]
        else:
            standard[key]['quantity'] += qty
            if row.get('size') not in standard[key]['sizes']:
                standard[key]['sizes'].append(row.get('size'))
            if row.get('color') not in standard[key]['colors']:
                standard[key]['colors'].append(row.get('color'))

    grouped = list(standard.values()) + personalized

    def sort_key(row):
        if group_by == 'garment':
            return (row.get('garment_style') or '', row.get('age_group') or '', row.get('size') or '')
        if group_by == 'age':
            return (row.get('age_group') or '', row.get('size') or '', row.get('design_name') or row.get('name') or '')
        if group_by == 'size':
            return (row.get('size') or '', row.get('design_name') or row.get('name') or '')
        if group_by == 'placement':
            return (row.get('placement') or '', row.get('design_name') or row.get('name') or '')
        if group_by == 'dimensions':
            return (inches(row.get('width') or row.get('name_width') or 0), inches(row.get('height') or row.get('name_height') or 0))
        return (row.get('kind') or '', row.get('design_name') or row.get('name') or '', row.get('placement') or '')

    grouped.sort(key=sort_key)
    return grouped


def flatten_production_rows(item_productions):
    """One row per transfer (front design, back name, back number) for CSV/summary."""
    rows = []
    for prod in item_productions:
        if not prod:
            continue
        front = prod.get('front')
        if front:
            rows.append({
                **front,
                'section': 'FRONT TRANSFER',
                'garment_style': prod.get('garment_style') or front.get('garment_style'),
                'style_number': prod.get('style_number'),
                'mockup_url': prod.get('mockup_front_url'),
                'overlay_url': prod.get('front_overlay_url'),
                'proof_url': prod.get('front_proof_url'),
                'placement': front.get('placement') or prod.get('front_placement') or 'center_chest',
                'order_number': prod.get('order_number'),
            })
        back = prod.get('back')
        if back:
            rows.append({
                **back,
                'section': 'BACK NAME / NUMBER',
                'kind': 'personalized',
                'garment_style': prod.get('garment_style') or back.get('garment_style'),
                'style_number': prod.get('style_number'),
                'width': back.get('combined_width'),
                'height': back.get('combined_height'),
                'mockup_url': prod.get('mockup_back_url') or prod.get('mockup_front_url'),
                'order_number': prod.get('order_number'),
            })
    return rows
