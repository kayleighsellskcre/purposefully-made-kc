"""Garment mockups must share a consistent card so shop tiles and overlays match."""
from PIL import Image, ImageDraw

from services.image_normalize import (
    TANK_CANVAS_H,
    TANK_CANVAS_W,
    TANK_TARGET_BOTTOM,
    TANK_TARGET_TOP,
    detect_shirt_box,
    frame_tank_image,
    normalize_image,
)


def _tight_tank(width=500, height=625, fill=(20, 20, 20)):
    """S&S-style ghost: garment fills most of a 4:5 card."""
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    left = int(width * 0.22)
    right = int(width * 0.78)
    top = int(height * 0.05)
    bottom = int(height * 0.95)
    draw.polygon(
        [
            (left + 40, top),
            (right - 40, top),
            (right, top + 70),
            (right - 10, bottom),
            (left + 10, bottom),
            (left, top + 70),
        ],
        fill=fill,
    )
    return img


def test_default_normalize_keeps_bc3001_canvas():
    framed = normalize_image(_tight_tank())
    assert framed.size == (1000, 1250)


def test_tank_frame_matches_comfort_colors_widen_card():
    framed = frame_tank_image(_tight_tank())
    assert framed.size == (TANK_CANVAS_W, TANK_CANVAS_H)
    box = detect_shirt_box(framed)
    assert box is not None
    top, left, bottom, right = box
    height = framed.height
    width = framed.width
    top_frac = top / height
    height_frac = (bottom - top) / height
    center = ((left + right) / 2.0) / width
    assert abs(top_frac - TANK_TARGET_TOP) < 0.04
    assert abs(height_frac - (TANK_TARGET_BOTTOM - TANK_TARGET_TOP)) < 0.06
    assert abs(center - 0.5) < 0.04
    # Must not fill the shop card the way the raw S&S crop does (~0.91).
    assert height_frac < 0.78
    assert (right - left) / width < 0.55


def test_tank_frame_fallback_when_silhouette_is_missing():
    # Full-bleed black: no backdrop for detection.
    img = Image.new('RGB', (500, 625), (12, 12, 12))
    framed = frame_tank_image(img)
    assert framed.size == (TANK_CANVAS_W, TANK_CANVAS_H)
    box = detect_shirt_box(framed)
    assert box is not None
    top, left, bottom, right = box
    assert abs(((left + right) / 2.0) / framed.width - 0.5) < 0.05
    assert (bottom - top) / framed.height < 0.80


def test_tank_flag_follows_category_and_sleeve():
    from types import SimpleNamespace
    from utils.print_sizes import client_config, is_tank

    tank = SimpleNamespace(
        name='Comfort Colors Heavyweight Ring Spun Tank Top',
        category='Tank',
        sleeve_length='Sleeveless',
        age_group='adult',
        style_number='CC9360',
    )
    tee = SimpleNamespace(
        name='Comfort Colors Heavyweight Ring Spun Tee',
        category='T-Shirts',
        sleeve_length='Short',
        age_group='adult',
        style_number='CC1717',
    )
    assert is_tank(tank) is True
    assert is_tank(tee) is False
    assert client_config(tank)['is_tank'] is True
    assert client_config(tee)['is_tank'] is False
