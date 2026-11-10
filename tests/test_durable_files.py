"""An order's artwork is copied to permanent storage while it still exists, and a missing file says so plainly."""
from utils import durable_files


def test_is_local():
    assert durable_files.is_local('/static/uploads/designs/a.png')
    assert not durable_files.is_local('https://cdn.example.com/a.png')
    assert not durable_files.is_local('')


def test_a_permanent_address_is_left_alone(app):
    with app.app_context():
        assert durable_files.make_durable(app, 'https://cdn.example.com/a.png') == 'https://cdn.example.com/a.png'


def test_a_local_file_is_copied_when_cloud_storage_is_on(app, monkeypatch, tmp_path):
    import utils.cloud_storage as cs
    with app.app_context():
        folder = tmp_path / 'static' / 'uploads' / 'designs'
        folder.mkdir(parents=True)
        (folder / 'logo.png').write_bytes(b'\x89PNG fake')
        monkeypatch.setattr(app, 'root_path', str(tmp_path))
        monkeypatch.setattr(cs, 'r2_configured', lambda a: True)
        sent = {}
        def fake_upload(data, a, filename, subfolder='designs', public_id_prefix='x'):
            sent['data'], sent['name'] = data, filename
            return 'https://cdn.example.com/designs/logo-1.png'
        monkeypatch.setattr(cs, 'upload_bytes', fake_upload)
        out = durable_files.make_durable(app, '/static/uploads/designs/logo.png')
    assert out == 'https://cdn.example.com/designs/logo-1.png' and sent['data'] == b'\x89PNG fake'


def test_a_file_that_is_already_gone_is_left_as_is(app, monkeypatch):
    import utils.cloud_storage as cs
    with app.app_context():
        monkeypatch.setattr(cs, 'r2_configured', lambda a: True)
        assert durable_files.make_durable(app, '/static/uploads/designs/nope-404.png') == '/static/uploads/designs/nope-404.png'


def _order():
    from models import Order, User, db
    from tests.conftest import CUSTOMER_EMAIL
    uid = User.query.filter_by(email=CUSTOMER_EMAIL).first().id
    o = Order(order_number='PMKC-DUR1', email=CUSTOMER_EMAIL, user_id=uid, first_name='C', last_name='C', subtotal=30,
              total=32.85, status='paid', payment_status='paid', payment_method='stripe')
    db.session.add(o)
    db.session.flush()
    return o


def test_audit_finds_a_recent_order_whose_print_file_is_gone(app, seed):
    from datetime import datetime

    from models import Order, OrderItem, db
    from utils.artwork_audit import find_missing
    with app.app_context():
        order = _order()
        item = OrderItem(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black',
                         quantity=1, unit_price=10, subtotal=10, design_file_name='lost-forever-xyz.png')
        db.session.add(item)
        db.session.commit()
        found = find_missing(app)
    assert any(f[1] == item.id and f[2] == 'front' for f in found)


def test_admin_can_replace_a_missing_print_file(app, seed, admin_client, monkeypatch):
    import io

    from models import Order, OrderItem, db
    import utils.cloud_storage as cs
    monkeypatch.setattr(cs, 'store_upload', lambda f, sub, prefix: 'https://cdn.example.com/designs/new.png')
    monkeypatch.setattr(cs, 'r2_configured', lambda a: True)
    with app.app_context():
        order = _order()
        item = OrderItem(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black',
                         quantity=1, unit_price=10, subtotal=10, design_file_name='gone.png')
        db.session.add(item)
        db.session.commit()
        oid, iid = order.id, item.id
    resp = admin_client.post(f'/admin/orders/{oid}/items/{iid}/replace-artwork',
                             data={'artwork': (io.BytesIO(b'\x89PNG fake'), 'art.png')}, content_type='multipart/form-data')
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(OrderItem, iid).design_file_name == 'https://cdn.example.com/designs/new.png'


def test_sweeper_moves_a_recent_local_design_to_permanent_storage(app, seed, monkeypatch, tmp_path):
    from datetime import datetime

    from models import Design, db
    import utils.cloud_storage as cs
    folder = tmp_path / 'static' / 'uploads' / 'designs'
    folder.mkdir(parents=True)
    (folder / 'stray.png').write_bytes(b'\x89PNG fake')
    with app.app_context():
        monkeypatch.setattr(app, 'root_path', str(tmp_path))
        monkeypatch.setattr(cs, 'r2_configured', lambda a: True)
        monkeypatch.setattr(cs, 'upload_bytes', lambda data, a, filename, subfolder='designs', public_id_prefix='x': 'https://cdn.example.com/designs/stray-1.png')
        d = Design(filename='stray.png', file_path='uploads/designs/stray.png', title='Stray', uploaded_at=datetime.utcnow())
        db.session.add(d)
        db.session.commit()
        moved = durable_files.promote_local_files(app)
        db.session.refresh(d)
        assert moved >= 1 and d.file_path == 'https://cdn.example.com/designs/stray-1.png'


def test_shared_uploader_retries_before_giving_up(app, monkeypatch):
    import io

    from werkzeug.datastructures import FileStorage

    import utils.cloud_storage as cs
    calls = {'n': 0}
    def flaky(fs, a, subfolder, prefix):
        calls['n'] += 1
        if calls['n'] < 3:
            raise RuntimeError('cloud hiccup')
        return 'https://cdn.example.com/ok.png'
    monkeypatch.setattr(cs, 'r2_configured', lambda a: True)
    monkeypatch.setattr(cs, '_upload_to_r2', flaky)
    monkeypatch.setattr('time.sleep', lambda s: None)
    with app.app_context():
        out = cs.upload_image(FileStorage(io.BytesIO(b'x'), filename='a.png'), app, subfolder='designs')
    assert out == 'https://cdn.example.com/ok.png' and calls['n'] == 3


def test_admin_picture_of_a_logo_is_drawn_true_to_size_not_enlarged():
    from utils.order_artwork import ADMIN_LOGO_EASE
    assert ADMIN_LOGO_EASE == 1.0
