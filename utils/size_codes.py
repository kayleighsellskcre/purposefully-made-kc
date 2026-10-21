"""Short size codes for the production sheets: YS, YM, YL, YXL, XS, S, M, L, XL, 2XL, 3XL, 4XL (and baby/toddler)."""
from collections import Counter

from utils.print_sizes import _norm_back_size, classify_category

_PLAIN = {'XXS', '2XS', 'XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL'}


def size_code(size, product=None):
    """The little letters printed next to a design: a youth M is YM, an adult M is just M."""
    key = _norm_back_size(size)
    if not key:
        return ''
    if key in _PLAIN and classify_category(product, size) == 'youth':
        return 'Y' + key
    return key


def size_order(code):
    """Sort sizes smallest to largest (youth first), so a breakdown reads naturally."""
    ladder = ['NB', '0-3M', '3-6M', '6-12M', '12-18M', '18-24M', '2T', '3T', '4T', '5T', 'YXS', 'YS', 'YM', 'YL', 'YXL', 'Y2XL',
              'XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL']
    return (ladder.index(code) if code in ladder else len(ladder), code)


def breakdown(counter):
    """{'YM': 2, 'L': 1} -> 'YM ×2 · L ×1' in size order."""
    items = sorted(Counter(counter).items(), key=lambda kv: size_order(kv[0]))
    return ' · '.join(f'{code} ×{n}' for code, n in items if code)
