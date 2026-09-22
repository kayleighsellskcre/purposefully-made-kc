from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dtf_list_has_no_save_to_phone_button():
    html = (ROOT / 'templates' / 'admin' / 'dtf_batch_sheets.html').read_text(encoding='utf-8')
    assert 'Save to phone' not in html
    assert 'photos_item_artwork' not in html
    assert 'press and hold the picture' in html.lower()
    assert 'Download PNG' in html


def test_order_detail_downloads_png_without_a_photos_redirect():
    html = (ROOT / 'templates' / 'admin' / 'order_detail.html').read_text(encoding='utf-8')
    assert 'photos_item_artwork' not in html
    assert "url_for('admin.save_item_artwork'" in html
    assert 'Save to phone' not in html
    assert 'Press and hold the picture' in html


def test_preview_artwork_serves_a_file_instead_of_redirecting():
    from routes import admin as admin_routes
    import inspect
    source = inspect.getsource(admin_routes.preview_item_artwork)
    assert 'return redirect(stored)' not in source
    assert 'local_file_for_url' in source


def test_image_url_rewrites_widen_quality_placeholder():
    from utils.cloud_storage import image_url
    url = image_url(
        'https://embed.widencdn.net/img/medialibrary1/abc/600px/shirt.png?q={quality}&x.template=y'
    )
    assert '{quality}' not in url
    assert 'q=80' in url
