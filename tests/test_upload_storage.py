"""Cart uploads must go to cloud storage: the web server disk is wiped on deploy."""
from io import BytesIO
from unittest.mock import patch


def test_cart_previews_and_artwork_go_to_cloud_storage(client, seed, app):
    calls = []

    def fake_r2(file_storage, app_, subfolder, prefix):
        calls.append((subfolder, prefix))
        return f'https://cdn.example.com/{subfolder}/{prefix}.png'

    with patch('utils.cloud_storage.r2_configured', return_value=True), \
         patch('utils.cloud_storage._upload_to_r2', side_effect=fake_r2):
        resp = client.post('/cart/add', data={
            'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
            'placement': 'center_chest',
            'design': (BytesIO(b'\x89PNG\r\n'), 'logo.png'),
            'proof_front': (BytesIO(b'\x89PNG\r\n'), 'proof_front.png'),
        }, content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert ('designs', 'cart_design') in calls
    assert ('proofs', 'proof_front') in calls
    with client.session_transaction() as sess:
        item = sess['cart'][-1]
    assert item['design_url'].startswith('https://cdn.example.com/')
    assert item['proof_front_url'].startswith('https://cdn.example.com/')


def test_upload_falls_back_to_local_when_cloud_fails(client, seed, app):
    with patch('utils.cloud_storage.r2_configured', return_value=True), \
         patch('utils.cloud_storage._upload_to_r2', side_effect=RuntimeError('r2 down')):
        resp = client.post('/cart/add', data={
            'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 1,
            'placement': 'center_chest', 'design_id': seed['free_design_id'],
            'proof_front': (BytesIO(b'\x89PNG\r\n'), 'proof_front.png'),
        }, content_type='multipart/form-data')
    assert resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess['cart'][-1]['proof_front_url'].startswith('/static/uploads/proofs/')
