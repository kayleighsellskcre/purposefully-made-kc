"""List pages show small copies of big design pictures; the originals are never touched."""
from utils import thumbs as T

R2 = 'https://pub-test.r2.dev'


def test_only_pictures_on_our_storage_are_shrunk(app):
    app.config['R2_PUBLIC_URL'] = R2
    with app.test_request_context():
        small = T.thumb_url(f'{R2}/designs/a.png', 300)
        assert small.startswith('/thumb?w=320&u=') and 'pub-test.r2.dev' in small
        assert T.thumb_url('https://evil.example.com/a.png', 300) == 'https://evil.example.com/a.png'
        assert T.thumb_url(f'{R2}/designs/a.pdf', 300) == f'{R2}/designs/a.pdf'
        assert T.thumb_url('/static/x.png') == '/static/x.png' and T.thumb_url(None) is None


def test_the_thumb_route_is_not_an_open_proxy(app, guest):
    app.config['R2_PUBLIC_URL'] = R2
    assert guest.get('/thumb?w=320&u=https%3A%2F%2Fevil.example.com%2Fa.png').status_code == 404
    assert guest.get('/thumb?w=999&u=' + 'https%3A%2F%2Fpub-test.r2.dev%2Fa.png').status_code in (302, 404)


def test_a_small_copy_is_made_cached_and_sent_for_a_year(app, guest, monkeypatch):
    import io
    from PIL import Image
    app.config['R2_PUBLIC_URL'] = R2
    buf = io.BytesIO()
    Image.new('RGBA', (1200, 900), (10, 20, 30, 255)).save(buf, 'PNG')
    raw = buf.getvalue()

    class Resp:
        status_code = 200
        class raw:
            @staticmethod
            def read(n, decode_content=True):
                return raw
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Resp())
    r = guest.get('/thumb?w=320&u=https%3A%2F%2Fpub-test.r2.dev%2Fdesigns%2Funique-test-pic.png')
    assert r.status_code == 200 and r.mimetype == 'image/webp'
    assert 'max-age=31536000' in r.headers['Cache-Control']
    assert Image.open(io.BytesIO(r.data)).width == 320 and len(r.data) < len(raw)
