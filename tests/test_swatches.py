import pytest


@pytest.fixture()
def fake_static(tmp_path, monkeypatch):
    import utils.swatches as swatches

    monkeypatch.setattr(swatches, '_ROOT', str(tmp_path))
    swatches._local_file_exists.cache_clear()
    (tmp_path / 'static').mkdir()
    yield tmp_path / 'static'
    swatches._local_file_exists.cache_clear()


def _shirt_photo(path, shirt_rgb):
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (200, 250), (255, 255, 255))
    ImageDraw.Draw(img).rectangle((40, 40, 160, 230), fill=shirt_rgb)
    img.save(path)


def test_garment_photo_gives_the_real_shirt_color_not_the_background(fake_static):
    from utils.swatches import true_color_hex

    _shirt_photo(fake_static / 'pink_front.jpg', (240, 170, 200))
    hex_value = true_color_hex(None, '/static/pink_front.jpg')
    r, g, b = (int(hex_value[i:i + 2], 16) for i in (1, 3, 5))
    assert abs(r - 240) <= 4 and abs(g - 170) <= 4 and abs(b - 200) <= 4


def test_manufacturer_swatch_wins_over_the_photo(fake_static):
    from PIL import Image
    from utils.swatches import true_color_hex

    Image.new('RGB', (35, 35), (10, 120, 60)).save(fake_static / 'swatch.gif')
    _shirt_photo(fake_static / 'front.jpg', (200, 0, 0))
    assert true_color_hex('/static/swatch.gif', '/static/front.jpg') == '#0a783c'


def test_missing_swatch_file_is_not_used(fake_static):
    from utils.swatches import swatch_background, usable_swatch_url

    assert usable_swatch_url('/static/nope.gif') is None
    assert swatch_background('#123456', '/static/nope.gif') == 'background-color:#123456'


def test_swatch_background_layers_the_fabric_image_over_its_color(fake_static):
    from PIL import Image
    from utils.swatches import swatch_background

    Image.new('RGB', (35, 35), (1, 2, 3)).save(fake_static / 'heather.gif')
    css = swatch_background('#010203', '/static/heather.gif')
    assert css.startswith('background-color:#010203;')
    assert "background-image:url('/static/heather.gif')" in css
