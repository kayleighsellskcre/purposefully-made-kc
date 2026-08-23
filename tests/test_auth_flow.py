"""Sign up, sign in, sign out, password reset, profile, and order history.

Also the boundary that matters most: one customer must never see another
customer's orders, designs, or details.
"""
import pytest

from models import db, Design, Order, User
from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL, PASSWORD

NEW_EMAIL = 'brand-new-test@example.com'
NEW_PASSWORD = 'Str0ngEnough!42'


def register(client, **over):
    form = {
        'first_name': 'Nina',
        'last_name': 'Newcomer',
        'email': NEW_EMAIL,
        'password': NEW_PASSWORD,
        'confirm_password': NEW_PASSWORD,
    }
    form.update(over)
    return client.post('/auth/register', data=form, follow_redirects=True)


def signed_in_as(client):
    """The email of whoever this client is signed in as, or None."""
    resp = client.get('/account/profile', follow_redirects=False)
    if resp.status_code != 200:
        return None
    body = client.get('/account/profile').get_data(as_text=True)
    for email in (NEW_EMAIL, CUSTOMER_EMAIL, OTHER_EMAIL):
        if email in body:
            return email
    return 'unknown'


# ── Sign up ──────────────────────────────────────────────────────────────────

def test_the_register_page_loads(guest):
    assert guest.get('/auth/register').status_code == 200


def test_a_new_customer_can_sign_up(guest, seed, app):
    resp = register(guest)
    assert resp.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email=NEW_EMAIL).count() == 1


def test_a_new_password_is_stored_hashed(guest, seed, app):
    register(guest)
    with app.app_context():
        user = User.query.filter_by(email=NEW_EMAIL).one()
        assert user.password_hash
        assert NEW_PASSWORD not in user.password_hash
        assert user.check_password(NEW_PASSWORD)


def test_signing_up_signs_you_in(guest, seed):
    register(guest)
    assert guest.get('/account/profile').status_code == 200


def test_an_email_already_in_use_is_refused(guest, seed, app):
    resp = register(guest, email=CUSTOMER_EMAIL)
    assert resp.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email=CUSTOMER_EMAIL).count() == 1


def test_mismatched_passwords_are_refused(guest, seed, app):
    register(guest, confirm_password='SomethingElse!99')
    with app.app_context():
        assert User.query.filter_by(email=NEW_EMAIL).count() == 0


@pytest.mark.parametrize('bad', [
    'not-an-email',
    'casey@gmial',        # a real, common typo — no dot in the domain
    'casey at example.com',
    '@example.com',
    'casey@',
    'casey@@example.com',
])
def test_an_address_that_is_not_an_address_is_refused(guest, seed, app, bad):
    """Regression: any string was accepted, so a typo created an account that
    could never receive a receipt or a password reset."""
    register(guest, email=bad)
    with app.app_context():
        assert User.query.filter_by(email=bad).count() == 0
        assert User.query.filter_by(email=bad.strip().lower()).count() == 0


def test_a_valid_address_with_odd_casing_is_still_accepted(guest, seed, app):
    register(guest, email='Nina.Newcomer+shop@Example.COM')
    with app.app_context():
        assert User.query.filter_by(email='nina.newcomer+shop@example.com').count() == 1


def test_an_address_is_stored_lower_case(guest, seed, app):
    register(guest, email=NEW_EMAIL.upper())
    with app.app_context():
        assert User.query.filter_by(email=NEW_EMAIL).count() == 1


def test_the_same_address_cannot_register_twice_in_different_casing(guest, seed, app):
    """Regression: the duplicate check was case-sensitive but login is not, so
    one person could end up with two accounts and reach either at random."""
    register(guest, email=NEW_EMAIL)
    guest.get('/auth/logout')
    register(guest, email=NEW_EMAIL.upper())
    with app.app_context():
        matches = User.query.filter(
            db.func.lower(User.email) == NEW_EMAIL
        ).count()
    assert matches == 1, 'the same address registered twice'


def test_you_can_sign_in_with_the_casing_you_registered_with(app, seed):
    signup = app.test_client()
    register(signup, email='Mixed.Case@Example.com')
    signup.get('/auth/logout')

    signin = app.test_client()
    signin.post('/auth/login', data={'email': 'Mixed.Case@Example.com',
                                     'password': NEW_PASSWORD},
                follow_redirects=True)
    assert signin.get('/account/profile').status_code == 200


def test_a_new_account_is_not_an_admin(guest, seed, app):
    register(guest)
    with app.app_context():
        assert User.query.filter_by(email=NEW_EMAIL).one().is_admin is False


def test_signing_up_cannot_grant_yourself_admin(guest, seed, app):
    """The form has no admin field; posting one anyway must be ignored."""
    register(guest, is_admin='true')
    with app.app_context():
        assert User.query.filter_by(email=NEW_EMAIL).one().is_admin is False


# ── Sign in and out ──────────────────────────────────────────────────────────

def test_the_login_page_loads(guest):
    assert guest.get('/auth/login').status_code == 200


def test_a_customer_can_sign_in(client, seed, login):
    login(client, CUSTOMER_EMAIL)
    assert client.get('/account/profile').status_code == 200


def test_a_wrong_password_does_not_sign_you_in(client, seed):
    client.post('/auth/login', data={'email': CUSTOMER_EMAIL,
                                     'password': 'wrong-password'},
                follow_redirects=True)
    assert client.get('/account/profile', follow_redirects=False).status_code == 302


def test_an_unknown_email_does_not_sign_you_in(client, seed):
    client.post('/auth/login', data={'email': 'nobody@example.com',
                                     'password': PASSWORD},
                follow_redirects=True)
    assert client.get('/account/profile', follow_redirects=False).status_code == 302


def test_a_failed_sign_in_does_not_say_which_half_was_wrong(client, seed):
    """Confirming an address exists helps someone enumerate customers."""
    unknown = client.post('/auth/login', data={'email': 'nobody@example.com',
                                               'password': PASSWORD},
                          follow_redirects=True).get_data(as_text=True).lower()
    wrong_pw = client.post('/auth/login', data={'email': CUSTOMER_EMAIL,
                                                'password': 'wrong-password'},
                           follow_redirects=True).get_data(as_text=True).lower()
    assert 'no account' not in unknown
    assert 'incorrect password' not in wrong_pw


def test_signing_out_ends_the_session(customer_client):
    customer_client.get('/auth/logout', follow_redirects=True)
    resp = customer_client.get('/account/profile', follow_redirects=False)
    assert resp.status_code == 302


def test_signing_out_then_back_in_works(client, seed, login):
    login(client, CUSTOMER_EMAIL)
    client.get('/auth/logout', follow_redirects=True)
    login(client, CUSTOMER_EMAIL)
    assert client.get('/account/profile').status_code == 200


# ── Password reset ───────────────────────────────────────────────────────────

def test_the_forgot_password_page_loads(guest):
    assert guest.get('/auth/forgot-password').status_code == 200


def test_asking_for_a_reset_gives_the_same_answer_for_any_address(guest, seed):
    """Differing replies would reveal which addresses have accounts."""
    known = guest.post('/auth/forgot-password', data={'email': CUSTOMER_EMAIL},
                       follow_redirects=True).get_data(as_text=True)
    unknown = guest.post('/auth/forgot-password',
                         data={'email': 'nobody@example.com'},
                         follow_redirects=True).get_data(as_text=True)
    for phrase in ('reset', 'email', 'sent'):
        assert (phrase in known.lower()) == (phrase in unknown.lower())


def test_a_reset_token_lets_you_set_a_new_password(guest, seed, app):
    guest.post('/auth/forgot-password', data={'email': CUSTOMER_EMAIL},
               follow_redirects=True)
    with app.app_context():
        token = User.query.filter_by(email=CUSTOMER_EMAIL).one().reset_token
    assert token, 'no reset token was issued'

    guest.post(f'/auth/reset-password/{token}',
               data={'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD},
               follow_redirects=True)
    with app.app_context():
        user = User.query.filter_by(email=CUSTOMER_EMAIL).one()
        assert user.check_password(NEW_PASSWORD)
        assert not user.check_password(PASSWORD), 'the old password still works'


def test_a_used_reset_token_cannot_be_replayed(guest, seed, app):
    guest.post('/auth/forgot-password', data={'email': CUSTOMER_EMAIL},
               follow_redirects=True)
    with app.app_context():
        token = User.query.filter_by(email=CUSTOMER_EMAIL).one().reset_token

    guest.post(f'/auth/reset-password/{token}',
               data={'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD},
               follow_redirects=True)
    guest.post(f'/auth/reset-password/{token}',
               data={'password': 'Second!Attempt99',
                     'confirm_password': 'Second!Attempt99'},
               follow_redirects=True)
    with app.app_context():
        user = User.query.filter_by(email=CUSTOMER_EMAIL).one()
        assert user.check_password(NEW_PASSWORD), 'a spent token was reused'


def test_a_made_up_reset_token_is_rejected(guest, seed, app):
    guest.post('/auth/reset-password/not-a-real-token',
               data={'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD},
               follow_redirects=True)
    with app.app_context():
        assert User.query.filter_by(email=CUSTOMER_EMAIL).one().check_password(PASSWORD)


# ── Profile ──────────────────────────────────────────────────────────────────

def test_the_profile_page_shows_the_customers_own_details(customer_client):
    body = customer_client.get('/account/profile').get_data(as_text=True)
    assert CUSTOMER_EMAIL in body
    assert 'Casey' in body


def test_a_customer_can_update_their_details(customer_client, seed, app):
    customer_client.post('/account/profile', data={
        'first_name': 'Cassandra', 'last_name': 'Customer',
        'email': CUSTOMER_EMAIL, 'phone': '816-555-0199',
    }, follow_redirects=True)
    with app.app_context():
        user = db.session.get(User, seed['customer_id'])
        assert user.first_name == 'Cassandra'
        assert user.phone == '816-555-0199'


def test_the_profile_form_cannot_change_the_email_address(customer_client, seed, app):
    """The sign-in address is deliberately fixed; the form ignores the field."""
    customer_client.post('/account/profile', data={
        'first_name': 'Casey', 'last_name': 'Customer', 'email': OTHER_EMAIL,
    }, follow_redirects=True)
    with app.app_context():
        assert db.session.get(User, seed['customer_id']).email == CUSTOMER_EMAIL


def test_a_customer_cannot_make_themselves_an_admin(customer_client, seed, app):
    customer_client.post('/account/profile', data={
        'first_name': 'Casey', 'last_name': 'Customer', 'is_admin': 'true',
    }, follow_redirects=True)
    with app.app_context():
        assert db.session.get(User, seed['customer_id']).is_admin is False


def test_a_customer_can_change_their_password(customer_client, seed, app):
    customer_client.post('/account/profile', data={
        'first_name': 'Casey', 'last_name': 'Customer',
        'current_password': PASSWORD,
        'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD,
    }, follow_redirects=True)
    with app.app_context():
        assert db.session.get(User, seed['customer_id']).check_password(NEW_PASSWORD)


def test_a_wrong_current_password_blocks_the_change(customer_client, seed, app):
    customer_client.post('/account/profile', data={
        'first_name': 'Casey', 'last_name': 'Customer',
        'current_password': 'not-my-password',
        'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD,
    }, follow_redirects=True)
    with app.app_context():
        assert db.session.get(User, seed['customer_id']).check_password(PASSWORD)


# ── Order history and cross-customer access ──────────────────────────────────

@pytest.fixture()
def other_customers_order(app, seed):
    """One paid order belonging to the *other* customer."""
    with app.app_context():
        order = Order(
            order_number='PMK-OTHER-1',
            user_id=seed['other_id'],
            first_name='Otto', last_name='Other', email=OTHER_EMAIL,
            subtotal=30.0, total=30.0,
            payment_status='paid', status='new',
            fulfillment_method='pickup',
        )
        db.session.add(order)
        db.session.commit()
        return {'id': order.id, 'number': order.order_number}


def test_the_order_history_page_loads_when_empty(customer_client):
    resp = customer_client.get('/account/orders')
    assert resp.status_code == 200


def test_a_customer_sees_their_own_order(customer_client, seed, app):
    with app.app_context():
        order = Order(
            order_number='PMK-MINE-1', user_id=seed['customer_id'],
            first_name='Casey', last_name='Customer', email=CUSTOMER_EMAIL,
            subtotal=30.0, total=30.0, payment_status='paid',
            status='new', fulfillment_method='pickup',
        )
        db.session.add(order)
        db.session.commit()
    body = customer_client.get('/account/orders').get_data(as_text=True)
    assert 'PMK-MINE-1' in body


def test_a_customer_does_not_see_someone_elses_order_in_their_history(
    customer_client, other_customers_order
):
    body = customer_client.get('/account/orders').get_data(as_text=True)
    assert other_customers_order['number'] not in body


def test_a_customer_cannot_open_someone_elses_order(customer_client,
                                                    other_customers_order):
    resp = customer_client.get(f'/account/orders/{other_customers_order["id"]}',
                               follow_redirects=False)
    assert resp.status_code != 200, "another customer's order was served"


def test_a_guest_cannot_open_an_order_at_all(guest, other_customers_order):
    resp = guest.get(f'/account/orders/{other_customers_order["id"]}',
                     follow_redirects=False)
    assert resp.status_code != 200


def test_a_customer_does_not_see_another_customers_designs(customer_client,
                                                           seed, app):
    with app.app_context():
        private = Design(
            filename='ottos-secret.png',
            file_path='uploads/designs/ottos-secret.png',
            title='Otto Private Artwork',
            uploaded_by_user_id=seed['other_id'],
        )
        db.session.add(private)
        db.session.commit()
    body = customer_client.get('/account/designs').get_data(as_text=True)
    assert 'Otto Private Artwork' not in body
