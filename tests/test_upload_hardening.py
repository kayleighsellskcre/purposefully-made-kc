"""What /api/upload-design will accept, and from whom.

The route saves a file under static/ and returns the same-origin URL for it in
its JSON reply. Two things were wrong with that.

It read its allowlist from config['ALLOWED_EXTENSIONS'], which included 'svg'
and 'pdf'. An SVG is a document that may carry <script>, and the branch that
rewrites uploads runs only for raster formats, so a vector file was stored
exactly as supplied. Anyone could therefore obtain a URL on our own domain
that ran their JavaScript against whoever opened it.

It also required no login, so the file store and the designs table were open to
anonymous writes, and strangers could park arbitrary pictures on the domain.

These tests pin both shut while keeping the ordinary PNG upload working.
"""

import io

import pytest
from PIL import Image


ENDPOINT = '/api/upload-design'

SVG_BOMB = (
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)">'
    b'<script>fetch("/admin/products")</script></svg>'
)


def png_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(buf, format='PNG')
    return buf.getvalue()


def upload(client, filename, payload):
    return client.post(
        ENDPOINT,
        data={'file': (io.BytesIO(payload), filename)},
        content_type='multipart/form-data',
    )


@pytest.fixture()
def scratch_uploads(app, tmp_path):
    """Keep accepted uploads out of the real static/ tree.

    The app fixture is session scoped, so this has to be put back afterwards or
    it leaks into every later test.
    """
    previous = app.config['UPLOAD_FOLDER']
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    try:
        yield tmp_path
    finally:
        app.config['UPLOAD_FOLDER'] = previous


@pytest.fixture()
def no_bg_removal(monkeypatch):
    """Stop the accept tests from invoking rembg.

    process_artwork_file may load a segmentation model, which is far too slow
    and too network-dependent for a test whose subject is the allowlist.
    """
    try:
        import services.image_processing as processing
    except Exception:
        return  # the route's own try/except skips processing, which suits us

    monkeypatch.setattr(
        processing, 'process_artwork_file',
        lambda *a, **k: {'path': None, 'engine': 'stub', 'validation': {}},
    )


# ── Who may upload at all ────────────────────────────────────────────────────

def test_guests_cannot_upload(guest):
    """A signed-out caller should not be able to write to our file store."""
    resp = upload(guest, 'anything.png', png_bytes())
    assert resp.status_code != 200
    assert resp.status_code in (301, 302, 401, 403), resp.status_code


def test_guest_upload_writes_nothing(guest, scratch_uploads):
    upload(guest, 'anything.png', png_bytes())
    assert not [p for p in scratch_uploads.rglob('*') if p.is_file()]


# ── Formats that must not be stored ──────────────────────────────────────────

@pytest.mark.parametrize('filename', [
    'evil.svg',
    'EVIL.SVG',
    'logo.png.svg',
    'evil.pdf',
])
def test_scriptable_uploads_are_refused(customer_client, filename):
    """Checked as a signed-in customer, so the allowlist is what refuses it."""
    resp = upload(customer_client, filename, SVG_BOMB)
    assert resp.status_code == 400, (
        f'{filename} was accepted; response: {resp.get_data(as_text=True)[:300]}'
    )


def test_refusal_writes_nothing(customer_client, scratch_uploads):
    upload(customer_client, 'evil.svg', SVG_BOMB)
    written = [p for p in scratch_uploads.rglob('*') if p.is_file()]
    assert not written, f'files left behind: {written}'


def test_error_message_no_longer_advertises_vector_formats(customer_client):
    """The old copy invited exactly the upload we now reject."""
    resp = upload(customer_client, 'evil.svg', SVG_BOMB)
    body = resp.get_data(as_text=True).lower()
    assert 'svg' not in body
    assert 'pdf' not in body


# ── The format the feature actually exists for ──────────────────────────────

def test_png_from_a_signed_in_customer_still_works(
        customer_client, scratch_uploads, no_bg_removal):
    resp = upload(customer_client, 'my-logo.png', png_bytes())
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()['success'] is True


def test_stored_name_discards_the_submitted_one(
        customer_client, scratch_uploads, no_bg_removal):
    """A caller-chosen name never reaches the filesystem, so traversal cannot."""
    resp = upload(customer_client, '../../../../etc/passwd.png', png_bytes())
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    files = [p for p in scratch_uploads.rglob('*') if p.is_file()]
    assert len(files) == 1, f'expected one stored file, got {files}'
    stored = files[0]
    assert stored.parent.name == 'designs'
    assert 'passwd' not in stored.name
    assert stored.suffix == '.png'


# ── The allowlists themselves ───────────────────────────────────────────────

SCRIPTABLE = {'svg', 'pdf', 'html', 'htm', 'xml', 'js', 'swf'}


def test_config_allowlist_holds_no_scriptable_formats(app):
    """Guards the config, since anything in it is servable from our origin."""
    allowed = {e.lower() for e in app.config['ALLOWED_EXTENSIONS']}
    assert not (allowed & SCRIPTABLE), f'scriptable formats allowed: {allowed & SCRIPTABLE}'


def test_upload_route_does_not_defer_to_the_config_allowlist():
    """The route keeps its own list so a config change cannot widen it."""
    from routes.api import _UPLOAD_EXTENSIONS

    assert not (_UPLOAD_EXTENSIONS & SCRIPTABLE)


def test_custom_request_allowlist_holds_no_scriptable_formats():
    """The other route that accepts customer artwork."""
    from routes.custom_request import allowed_file

    for name in ('evil.svg', 'evil.pdf', 'evil.html'):
        assert not allowed_file(name), f'{name} was allowed'
    assert allowed_file('photo.png')


def test_allowed_file_survives_a_nameless_upload():
    from routes.api import allowed_file

    assert not allowed_file('')
    assert not allowed_file(None)
    assert not allowed_file('noextension')
