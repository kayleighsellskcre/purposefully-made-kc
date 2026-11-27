"""Small text in the brand rose must be dark enough to read (WCAG AA, 4.5:1 on white)."""
import re
from pathlib import Path


def _lum(h):
    h = h.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def test_the_rose_text_color_is_readable_on_white_and_ivory():
    css = Path('static/css/main.css').read_text(encoding='utf-8')
    rose = re.search(r'--terra-cotta-text:\s*(#[0-9A-Fa-f]{6})', css).group(1)
    for bg in ('#FFFFFF', '#FDF8F3'):
        hi, lo = sorted((_lum(rose), _lum(bg)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5


def test_text_is_not_set_in_the_light_rose_any_more():
    bad = re.compile(r'(?<![-\w])color:\s*(var\(--terra-cotta\)|var\(--accent-color\)|#B87C6F)', re.I)
    offenders = [str(p) for p in list(Path('static/css').glob('*.css')) + list(Path('templates').rglob('*.html')) if bad.search(p.read_text(encoding='utf-8', errors='ignore'))]
    assert not offenders, offenders
