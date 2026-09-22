"""Round 2 audit item 16: My Group Orders said "No group orders yet" even
though two stores were live. Stores made from Admin -> Collections never
recorded a creator, so they belonged to no one's My Group Orders page -
not even the admin who runs the shop.
"""
from models import db, Collection


def _make_collection(name, slug, created_by_user_id=None):
    c = Collection(
        name=name, slug=slug, is_active=True, shipping_enabled=True,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(c)
    db.session.commit()
    return c


def test_admin_sees_a_creatorless_store_in_my_group_orders(app, client, login, seed):
    from tests.conftest import ADMIN_EMAIL
    with app.app_context():
        _make_collection('Orphaned Store', 'orphaned-store', created_by_user_id=None)

    login(client, ADMIN_EMAIL)
    body = client.get('/account/group-orders').get_data(as_text=True)
    assert 'Orphaned Store' in body
    assert 'No group orders yet' not in body


def test_admin_still_sees_stores_they_actually_created(client, login, seed):
    from tests.conftest import ADMIN_EMAIL
    login(client, ADMIN_EMAIL)
    body = client.get('/account/group-orders').get_data(as_text=True)
    # The seed fixture's collection is created_by_user_id=admin.id.
    assert seed['collection_slug'] in body or 'Test Elementary Spirit Wear' in body


def test_admin_does_not_see_a_customers_own_store(app, client, login, seed):
    from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL
    with app.app_context():
        from models import User
        customer = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        _make_collection('Customer Store', 'customer-store', created_by_user_id=customer.id)

    login(client, ADMIN_EMAIL)
    body = client.get('/account/group-orders').get_data(as_text=True)
    assert 'Customer Store' not in body


def test_a_regular_customer_does_not_see_creatorless_stores(app, client, login, seed):
    """The NULL-creator fallback is admin-only - a customer must never see
    an unowned store show up as if it were theirs."""
    from tests.conftest import CUSTOMER_EMAIL
    with app.app_context():
        _make_collection('Orphaned Store', 'orphaned-store-2', created_by_user_id=None)

    login(client, CUSTOMER_EMAIL)
    body = client.get('/account/group-orders').get_data(as_text=True)
    assert 'Orphaned Store' not in body


def test_admin_creating_a_store_records_them_as_the_creator(client, login, app, seed):
    from tests.conftest import ADMIN_EMAIL
    login(client, ADMIN_EMAIL)
    resp = client.post('/admin/collections/add', data={
        'name': 'New Admin Store',
        'group_kind': 'other',
        'products': [str(seed['tee_id'])],
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        from models import User
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        created = Collection.query.filter_by(name='New Admin Store').first()
        assert created is not None
        assert created.created_by_user_id == admin.id
