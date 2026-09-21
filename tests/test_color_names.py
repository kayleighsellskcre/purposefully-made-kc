from utils.color_names import (
    color_family,
    color_in_allowed_set,
    color_match_key,
    display_color_name,
    grouped_colors_by_family,
    swatch_hex,
    unique_display_colors,
)


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


def test_swatch_hex_prefers_supplier_value_then_lookup():
    assert swatch_hex('Berry', '#8e3a59') == '#8e3a59'
    assert swatch_hex('Black') == '#000000'
    assert swatch_hex('Athletic Heather') == '#b8b8b8'
    assert swatch_hex('Heather Navy') == '#1e3a5f'


def test_cleaned_allowed_color_matches_supplier_name():
    assert color_in_allowed_set('Dtg Black', {'Black'})
    assert color_in_allowed_set('athleticheather', {'Athletic Heather'})
    assert not color_in_allowed_set('Red', {'Black'})


def test_unique_display_colors_dedupes_and_sorts():
    assert unique_display_colors([
        'black', 'Black', 'Dtg Black', 'athleticheather', 'White_Black',
    ]) == ['Athletic Heather', 'Black', 'White Black']


# ── Round 2 audit item 8: color dropdown grouping ───────────────────────────

def test_color_family_plain_colors():
    assert color_family('Black') == 'Blacks and Grays'
    assert color_family('White') == 'Whites and Creams'
    assert color_family('Navy') == 'Blues'
    assert color_family('Forest Green') == 'Greens'
    assert color_family('Red') == 'Reds and Pinks'
    assert color_family('Purple') == 'Purples'
    assert color_family('Gold') == 'Yellows and Oranges'
    assert color_family('Brown') == 'Browns and Neutrals'


def test_color_family_prefers_the_trailing_hue_word():
    """A qualifier-plus-hue name reads by its more specific trailing word,
    not whichever color word happens to come first."""
    assert color_family('Slate Blue') == 'Blues'
    assert color_family('Royal Purple') == 'Purples'
    assert color_family('Team Purple') == 'Purples'
    assert color_family('True Royal') == 'Blues'


def test_color_family_patterns_win_over_any_color_word():
    assert color_family('Black Camo') == 'Patterns and Camo'
    assert color_family('Natural Camo') == 'Patterns and Camo'
    assert color_family('White Marble') == 'Patterns and Camo'
    assert color_family('Rainbow Stripe') == 'Patterns and Camo'


def test_color_family_bare_heather_defaults_to_grays():
    assert color_family('Heather') == 'Blacks and Grays'
    assert color_family('Dark Heather') == 'Blacks and Grays'
    assert color_family('Heather Blue') == 'Blues'


def test_color_family_falls_back_to_other_colors():
    assert color_family('Stargazer') == 'Other Colors'
    assert color_family('') == 'Other Colors'


def test_grouped_colors_by_family_keeps_every_color_and_skips_empty_families():
    groups = grouped_colors_by_family(['Black', 'Navy', 'White'])
    families = [name for name, _ in groups]
    assert families == ['Blacks and Grays', 'Whites and Creams', 'Blues']
    total = sum(len(colors) for _, colors in groups)
    assert total == 3


def test_grouped_colors_by_family_preserves_incoming_order_within_a_family():
    groups = dict(grouped_colors_by_family(['White', 'Black', 'Navy', 'Charcoal']))
    assert groups['Blacks and Grays'] == ['Black', 'Charcoal']
