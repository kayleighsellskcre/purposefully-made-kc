"""SanMar size charts for the styles the S&S Activewear data does not carry.

Taken from each style's official SanMar "Spec Sheet + Measurements" page on Nov 27, 2026. Inches, garment laid flat:
chest (or bust) across the front one inch below the armhole, body length, and sleeve length. Used by
utils/size_charts.py when a product's style is not at S&S. A product that already has a chart is left alone.

Left out on purpose: BC3787 (a sweatshort: waist and inseam, not chest and length), STTU169 (SanMar sells that tee as
SXU001 and the owner still has to confirm it is the same shirt), and BC3945Y, G64500, STSW013, STTU755 (not on SanMar).
"""
from __future__ import annotations

_A = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']
_W = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL', '4XL']
_X = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']
_6 = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL']
_Y = ['XS', 'S', 'M', 'L', 'XL']

# style: (sizes, chest, length, sleeve), every number as the spec sheet prints it
CHARTS = {
    'DM130': (_A, '18 19 20.25 22.25 23.75 25.25 27.25 29.25', '27 28 29 30 31 32 32.5 33', '16.75 17.5 18.25 19 19.75 20.5 21.25 22'),
    'DT6000': (_6, '17 19 20 21.5 23 24.5 26.5 28.5 30.5 32.5', '27 28 29 30 31 32 32.5 33 33.5 34',
               '15.875 17 17.75 18.5 19.25 20 20.75 21.5 22.25 23'),
    'DT8000': (_A, '17.5 19 20.5 22 23.5 25 27 29', '27 28 29 30 31 32 32.5 33', '16.75 17.5 18.25 19 19.75 20.5 21.25 22'),
    'LPC147V': (_W, '18.5 19.5 20.5 22 23.5 25 27 29', '26 26.5 27 28 29 30 30.5 31', '14.5 15 15.5 16 16.5 17 17.5 17.5'),
    'LPC54': (_W, '18.5 19.5 20.5 22 23.5 25 27 29', '26 26.5 27 28 29 30 30.5 31', '14.5 15 15.5 16 16.5 17 17.5 17.5'),
    'PC144': (_X, '20 22 24 26 28 30 32', '28 29 30 31 32 33 34', '34.125 35.125 36.125 37.125 37.625 38.125 38.625'),
    'PC145': (_X, '18 20 22 24 26 28 30', '28 29 30 31 32 33 34', '16.75 17.75 18.75 19.75 20.75 21.75 22.75'),
    'PC146': (_X, '20 22 24 26 28 30 32', '28 29 30 31 32 33 34', '34.125 35.125 36.125 37.125 37.625 38.125 38.625'),
    'PC146Y': (_Y, '14 16 17 18 20', '20 22.5 25 27 28.5', '22.625 25.625 28.625 31.125 33.625'),
    'PC147': (_X, '18 20 22 24 26 28 30', '28 29 30 31 32 33 34', '16.75 17.75 18.75 19.75 20.75 21.75 22.75'),
    'PC147LS': (_X, '18 20 22 24 26 28 30', '28 29 30 31 32 33 34', '34 35 36 37 38 38.5 39'),
    'PC147Y': (_Y, '14 16 17 18 19', '19 21 23 25 27', '11.75 13.75 14.75 15.75 16.75'),
    'PC147YLS': (_Y, '14 16 17 18 19', '19 21 23 25 27', '21.5 24.5 27.125 30.5 33.5'),
    'PC54': (['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL'], '18 20 22 24 26 28 30 31 33', '28 29 30 31 32 33 34 34.5 35',
             '16.75 17.75 18.75 19.75 20.75 21.75 22.75 22.75 22.75'),
    'PC78H': (['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL'], '20 22 24 26 28 30 32 33 35',
              '27.25 28.25 29.25 30.25 31.25 32.25 33.25 33.75 34.25', '34.25 35 35.75 36.5 37.25 38 38.75 38.75 38.75'),
    'LST350': (_W, '18 19 20 21.5 23 24.5 26.5 28.5', '25 25.5 26 27 28 29 29.5 30', '14 14.5 15 15.75 16.5 17.25 18 18.75'),
    'ST254': (_A, '20.5 22 23.5 25 26.5 28 30 32', '27 28 29 30 31 32 32.5 33', '34.75 35.5 36.25 37 37.75 38.5 39.25 40'),
    'ST350': (_6, '18.5 20 21.5 23 24.5 26 28 30 32 34', '27 28 29 30 31 32 32.5 33 33.5 34',
              '17.75 18.5 19.25 20 20.75 21.5 22.25 23 23.5 24'),
}


def _show(value):
    return f'{float(value):.3f}'.rstrip('0').rstrip('.')


def chart_for(style_number):
    """{size: {'chest', 'length', 'sleeve'}} for a style SanMar publishes here, or None."""
    entry = CHARTS.get(str(style_number or '').strip().upper())
    if not entry:
        return None
    sizes, chest, length, sleeve = entry
    chest, length, sleeve = chest.split(), length.split(), sleeve.split()
    if not (len(sizes) == len(chest) == len(length) == len(sleeve)):
        return None                                        # a typo in this table must never save a half chart
    return {size: {'chest': _show(c), 'length': _show(l), 'sleeve': _show(s)} for size, c, l, s in zip(sizes, chest, length, sleeve)}
