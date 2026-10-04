"""Admin can start a group order and pass it to the organizer."""
from models import db, Collection, User


def _pass_store(client, seed, organizer, **extra):
    data = {
        'name': 'Test Elementary Spirit Wear',
        'products': [str(seed['tee_id'])],
        'is_active': 'on',
        'shipping_enabled': 'on',
        'organizer': organizer,
    }
    data.update(extra)
    return client.post(
        f'/admin/collections/{seed["collection_id"]}/edit',
        data=data,
        follow_redirects=True,
    )


def test_admin_can_pass_a_store_by_organizer_name(admin_client, seed, app):
    html = _pass_store(admin_client, seed, 'Casey Customer').get_data(as_text=True)
    assert 'This store now belongs to Casey Customer (customer-test@example.com)' in html
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.created_by_user_id == seed['customer_id']
        assert saved.pending_organizer_email is None


def test_admin_can_pass_a_store_by_email(admin_client, seed, app):
    _pass_store(admin_client, seed, 'Customer-Test@Example.com')
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.created_by_user_id == seed['customer_id']


def test_a_first_name_alone_is_not_enough(admin_client, seed, app):
    html = _pass_store(admin_client, seed, 'Casey').get_data(as_text=True)
    assert 'full name or email' in html
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.created_by_user_id == seed['admin_id']


def test_the_named_organizer_can_edit_and_a_stranger_cannot(admin_client, seed, login):
    from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL

    _pass_store(admin_client, seed, 'Casey Customer')
    admin_client.get('/auth/logout')

    login(admin_client, CUSTOMER_EMAIL)
    edit = admin_client.get(f'/shop/group-orders/{seed["collection_slug"]}/edit')
    assert edit.status_code == 200
    assert 'name="organizer"' not in edit.get_data(as_text=True)
    mine = admin_client.get('/account/group-orders').get_data(as_text=True)
    assert 'Test Elementary Spirit Wear' in mine
    admin_client.get('/auth/logout')

    login(admin_client, OTHER_EMAIL)
    blocked = admin_client.get(
        f'/shop/group-orders/{seed["collection_slug"]}/edit',
        follow_redirects=True,
    )
    assert 'only edit group orders you created' in blocked.get_data(as_text=True).lower()


def test_organizer_saving_their_edit_keeps_the_store(admin_client, seed, login, app):
    from tests.conftest import CUSTOMER_EMAIL

    _pass_store(admin_client, seed, 'Casey Customer')
    admin_client.get('/auth/logout')
    login(admin_client, CUSTOMER_EMAIL)
    admin_client.post(
        f'/shop/group-orders/{seed["collection_slug"]}/edit',
        data={
            'name': 'Test Elementary Spirit Wear',
            'products': [str(seed['tee_id'])],
            'is_active': 'on',
            'pickup_instructions': 'Casey will hand them out at practice.',
            'organizer': 'otto-other@example.com',
        },
        follow_redirects=True,
    )
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.created_by_user_id == seed['customer_id']
        assert saved.pickup_instructions == 'Casey will hand them out at practice.'


def test_admin_can_still_edit_after_passing_the_store(admin_client, seed):
    _pass_store(admin_client, seed, 'Casey Customer')
    resp = admin_client.get(f'/admin/collections/{seed["collection_id"]}/edit')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="organizer"' in html
    assert 'value="customer-test@example.com"' in html
    assert 'belongs to Casey Customer' in html


def test_resaving_without_changes_keeps_the_organizer_quietly(admin_client, seed, app):
    _pass_store(admin_client, seed, 'Casey Customer')
    html = _pass_store(admin_client, seed, 'customer-test@example.com').get_data(as_text=True)
    assert 'This store now belongs to' not in html
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.created_by_user_id == seed['customer_id']


def test_unknown_organizer_name_leaves_the_owner_in_place(admin_client, seed, app):
    resp = _pass_store(admin_client, seed, 'Nobody Named This')
    assert 'could not find an account' in resp.get_data(as_text=True).lower()
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.created_by_user_id == seed['admin_id']


def test_an_unknown_email_waits_until_they_register(admin_client, seed, app):
    _pass_store(admin_client, seed, 'abby@example.com')
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.pending_organizer_email == 'abby@example.com'
        assert saved.created_by_user_id == seed['admin_id']
    admin_client.get('/auth/logout')

    admin_client.post('/auth/register', data={
        'email': 'abby@example.com',
        'password': 'AbbyPassw0rd!',
        'confirm_password': 'AbbyPassw0rd!',
        'first_name': 'Abby',
        'last_name': 'Hayes',
    }, follow_redirects=True)
    mine = admin_client.get('/account/group-orders').get_data(as_text=True)
    assert 'Test Elementary Spirit Wear' in mine
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        abby = User.query.filter_by(email='abby@example.com').one()
        assert saved.created_by_user_id == abby.id
        assert saved.pending_organizer_email is None


def test_an_existing_account_claims_a_waiting_store_on_login(admin_client, seed, login, app):
    from tests.conftest import CUSTOMER_EMAIL

    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        saved.pending_organizer_email = CUSTOMER_EMAIL
        db.session.commit()
    admin_client.get('/auth/logout')
    resp = login(admin_client, CUSTOMER_EMAIL)
    assert 'ready for you to finish' in resp.get_data(as_text=True)
    with app.app_context():
        saved = db.session.get(Collection, seed['collection_id'])
        assert saved.created_by_user_id == seed['customer_id']
        assert saved.pending_organizer_email is None


def test_customers_do_not_see_the_organizer_field(customer_client, seed):
    html = customer_client.get('/shop/group-orders/create').get_data(as_text=True)
    assert 'name="organizer"' not in html


def test_admin_create_and_edit_forms_offer_the_organizer_field(admin_client, seed):
    create = admin_client.get('/admin/collections/add').get_data(as_text=True)
    edit = admin_client.get(
        f'/admin/collections/{seed["collection_id"]}/edit'
    ).get_data(as_text=True)
    assert 'name="organizer"' in create
    assert 'name="organizer"' in edit
    assert 'Abby Hayes or their email' in create


def test_admin_can_start_a_store_for_someone_else(admin_client, seed, app):
    resp = admin_client.post('/admin/collections/add', data={
        'name': 'Soccer Moms Starter',
        'group_kind': 'other',
        'products': [str(seed['tee_id'])],
        'organizer': 'Casey Customer',
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        created = Collection.query.filter_by(name='Soccer Moms Starter').one()
        assert created.created_by_user_id == seed['customer_id']


def test_admin_list_shows_who_has_the_store(admin_client, seed):
    _pass_store(admin_client, seed, 'abby@example.com')
    html = admin_client.get('/admin/collections').get_data(as_text=True)
    assert 'Waiting for abby@example.com' in html
