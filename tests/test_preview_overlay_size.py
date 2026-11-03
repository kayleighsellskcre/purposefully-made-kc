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


def test_small_prints_are_drawn_small_not_padded_up():
    four = preview_overlay_style({'size': 'M', 'print_width': 4.0, 'print_height': 4.0, 'product': None}, 'center_chest')
    ten = preview_overlay_style({'size': 'M', 'print_width': 10.0, 'print_height': 10.0, 'product': None}, 'center_chest')
    assert 'width:15.2%' in four and 'width:38.0%' in ten


def test_garment_metrics_reports_the_body_width_apart_from_the_sleeves():
    import io
    from PIL import Image, ImageDraw
    from services.garment_metrics import _silhouette
    img = Image.new('RGB', (400, 500), 'white')
    d = ImageDraw.Draw(img)
    d.rectangle((150, 50, 250, 450), fill=(20, 20, 20))      # body: 100 px wide
    d.rectangle((60, 50, 140, 300), fill=(20, 20, 20))       # left sleeve hangs apart from the body
    d.rectangle((260, 50, 340, 300), fill=(20, 20, 20))      # right sleeve
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    got = _silhouette(buf.getvalue())
    assert got['ok'] and abs(got['torso'] - 0.25) < 0.03       # 100 of 400 px, not the 280 px with sleeves
    assert got['width'] > 0.6


def test_chest_widths_are_exported_for_the_customizer():
    from utils.print_sizes import GARMENT_CHEST_WIDTH_IN, GARMENT_CHEST_WIDTH_DEFAULT
    assert GARMENT_CHEST_WIDTH_IN['adult']['M'] > GARMENT_CHEST_WIDTH_IN['youth']['YM'] > GARMENT_CHEST_WIDTH_IN['toddler']['3T']
    assert set(GARMENT_CHEST_WIDTH_DEFAULT) == {'adult', 'youth', 'toddler', 'baby'}
