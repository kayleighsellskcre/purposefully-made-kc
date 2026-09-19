from utils.color_names import color_match_key, display_color_name, unique_display_colors


def test_display_color_name_merges_case_and_strips_dtg():
    assert display_color_name('black') == 'Black'
    assert display_color_name('Black') == 'Black'
    assert display_color_name('Dtg Black') == 'Black'
    assert display_color_name('DTG White') == 'White'
    assert color_match_key('Dtg Black') == color_match_key('black')


def test_display_color_name_splits_underscores_slashes_and_concatenated_words():
    assert display_color_name('athleticheather') == 'Athletic Heather'
    assert display_color_name('blackmarble') == 'Black Marble'
    assert display_color_name('White_Black') == 'White Black'
    assert display_color_name('White/ Black') == 'White Black'


def test_test_colors_are_dropped():
    assert display_color_name('TestColor') is None
    assert display_color_name('test') is None
    assert 'TestColor' not in unique_display_colors(['Black', 'TestColor', 'black'])


def test_unique_display_colors_dedupes_and_sorts():
    assert unique_display_colors([
        'black', 'Black', 'Dtg Black', 'athleticheather', 'White_Black',
    ]) == ['Athletic Heather', 'Black', 'White Black']
