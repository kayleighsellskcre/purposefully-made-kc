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


def test_admin_redraws_a_plain_front_logo_instead_of_the_saved_picture(app):
    from types import SimpleNamespace as NS
    from utils.order_artwork import artwork_kit
    item = NS(design=None, design_file_name='/static/uploads/x.png', proof_image='/static/uploads/proofs/proof_front_1.png',
              proof_back_image=None, placement='center_chest', color='Black', size='M', print_width=8.0, print_height=8.0,
              product=None, back_design_details=None)
    with app.test_request_context():
        kit = artwork_kit(item)
    assert kit['front_overlay_url'] and 'width:' in kit['front_overlay_style']
    assert not kit['proof_front_url']


def test_chest_widths_and_body_measure_exist_for_the_admin_redraw():
    from utils.print_sizes import garment_chest_width_in
    assert garment_chest_width_in('M', None) > garment_chest_width_in('YM', None) > 0


def test_admin_proof_box_is_the_shape_of_the_photo_so_logo_percentages_mean_something():
    from pathlib import Path
    css = Path(__file__).resolve().parents[1].joinpath('templates/admin/order_detail.html').read_text(encoding='utf-8')
    assert '.od-kit-proofs .pm-proof { height: 240px; aspect-ratio: 4 / 5; flex: 0 0 auto; }' in css
