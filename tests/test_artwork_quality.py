"""Uploaded artwork keeps its real pixels, and small files get a plain-English heads-up."""
import io

from PIL import Image, ImageDraw

from services.image_processing import issue_messages, process_artwork_bytes


def _photo(size):
    """Opaque picture on a cream backdrop with a dark shape, like a phone photo of a drawing."""
    img = Image.new('RGB', size, (245, 240, 225))
    d = ImageDraw.Draw(img)
    w, h = size
    d.ellipse((w * 0.25, h * 0.25, w * 0.75, h * 0.75), fill=(20, 40, 160))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=95)
    return buf.getvalue()


def test_big_upload_is_not_shrunk_for_the_cut():
    result = process_artwork_bytes(_photo((3600, 3000)))
    out = Image.open(io.BytesIO(result['data']))
    assert out.mode == 'RGBA'
    assert max(out.size) > 1600          # old code returned at most 1600 px
    assert result['has_transparency']
    # corner is background (transparent), centre is the artwork (opaque)
    assert out.getpixel((2, 2))[3] == 0
    assert out.getpixel((out.width // 2, out.height // 2))[3] == 255


def test_small_upload_warns_but_stays_usable():
    result = process_artwork_bytes(_photo((900, 900)))
    assert 'soft_for_print' in result['validation']['issues']
    assert any('small' in m for m in issue_messages(result['validation']))


def test_large_upload_has_no_size_warning():
    result = process_artwork_bytes(_photo((3600, 3600)))
    assert 'soft_for_print' not in result['validation']['issues']
