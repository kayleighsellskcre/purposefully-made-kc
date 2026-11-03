"""Preview overlay sizing is visual-only and must track ordered print inches."""
from utils.order_artwork import preview_overlay_style
from utils.print_sizes import PREVIEW_REF_PCT, PREVIEW_REF_WIDTH_IN


def test_preview_overlay_scales_with_print_width():
    style = preview_overlay_style(
        {'size': 'M', 'print_width': 10.0, 'print_height': 10.0, 'product': None},
        'center_chest',
    )
    assert 'max-width:none' in style
    assert f'width:{PREVIEW_REF_PCT:.1f}%' in style


def test_preview_overlay_taller_logo_is_only_mildly_trimmed():
    style = preview_overlay_style(
        {'size': 'M', 'print_width': 10.0, 'print_height': 15.0, 'product': None},
        'center_chest',
    )
    # 38 * 0.88 = 33.44 — must stay well above the old 22% tall-logo floor
    assert 'width:33.4%' in style or 'width:33.5%' in style


def test_preview_overlay_side_chest_is_smaller():
    style = preview_overlay_style(
        {'size': 'M', 'print_width': 10.0, 'print_height': 10.0, 'product': None},
        'left_chest',
    )
    assert 'width:15.0%' in style or 'width:16.0%' in style or 'width:14.' in style


def test_preview_ref_pct_is_roomy():
    assert PREVIEW_REF_PCT >= 36
    assert PREVIEW_REF_WIDTH_IN == 10.0
