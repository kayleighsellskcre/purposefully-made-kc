"""The SanMar size chart table for styles S&S does not carry."""
from utils.sanmar_size_charts import CHARTS, chart_for
from utils.size_charts import _odd


def test_every_sanmar_chart_is_complete_and_grows_with_size():
    assert len(CHARTS) == 19
    for style in CHARTS:
        chart = chart_for(style)
        assert chart and len(chart) >= 5, style
        assert _odd(chart) == '', style                 # a bigger size is never narrower or shorter than the one before it
        assert all(row['chest'] and row['length'] and row['sleeve'] for row in chart.values()), style


def test_numbers_match_the_spec_sheet():
    pc54 = chart_for('pc54')
    assert pc54['S'] == {'chest': '18', 'length': '28', 'sleeve': '16.75'}
    assert pc54['6XL'] == {'chest': '33', 'length': '35', 'sleeve': '22.75'}
    assert chart_for('DT6000')['XS']['sleeve'] == '15.875'
    assert chart_for('PC147YLS')['M']['sleeve'] == '27.125'
    assert chart_for('STTU169')['XXS'] == {'chest': '18', 'length': '26.75', 'sleeve': '17.125'}
    assert chart_for('STTU169')['5XL'] == {'chest': '32.5', 'length': '34.75', 'sleeve': '22.25'}


def test_styles_left_out_on_purpose_are_not_filled():
    for style in ('BC3787', 'BC3945Y', 'G64500', 'STSW013', 'STTU755', 'NOPE'):
        assert chart_for(style) is None
