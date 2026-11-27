"""A new account is emailed a link to confirm its address. Nothing is blocked while it waits."""
from unittest import mock

from models import User, db


def _user(app, email):
    with app.app_context():
        return User.query.filter_by(email=email).first()


def test_signing_up_emails_a_confirmation_link_and_does_not_block_anything(app, seed, client):
    with mock.patch('utils.background.run_in_background') as bg:
        resp = client.post('/auth/register', data={'email': 'newbie@example.com', 'password': 'goodpassword1',
                                                   'confirm_password': 'goodpassword1', 'first_name': 'Nia'})
    assert resp.status_code == 302
    assert any(c.args[1].__name__ == 'send_confirmation' for c in bg.call_args_list)
    assert _user(app, 'newbie@example.com').email_confirmed_at is None
    assert client.get('/cart/').status_code == 200                        # signed in and shopping right away


def test_opening_the_link_confirms_the_address(app, seed, client):
    from utils.email_confirm import make_token
    with app.app_context():
        user = User.query.filter_by(email='newbie2@example.com').first() or User(email='newbie2@example.com', first_name='Ana')
        user.set_password('goodpassword1')
        db.session.add(user)
        db.session.commit()
        token = make_token(user)
    resp = client.get(f'/auth/confirm-email/{token}')
    assert resp.status_code == 302
    assert _user(app, 'newbie2@example.com').email_confirmed_at is not None


def test_a_bad_or_old_link_confirms_nothing(app, seed, client):
    resp = client.get('/auth/confirm-email/not-a-real-token')
    assert resp.status_code == 302
    from utils.email_confirm import make_token, user_for_token
    with app.app_context():
        user = User.query.filter_by(email='newbie3@example.com').first() or User(email='newbie3@example.com')
        user.set_password('goodpassword1')
        db.session.add(user)
        db.session.commit()
        token = make_token(user)
        user.email = 'changed3@example.com'                                 # the address changed after the link was sent
        db.session.commit()
        assert user_for_token(token) is None


def test_the_reminder_only_shows_for_an_account_that_was_sent_a_link(app, seed, customer_client):
    page = customer_client.get('/account/profile').get_data(as_text=True)
    assert 'Please confirm your email address' not in page               # older accounts are never nagged
    with app.app_context():
        from datetime import datetime
        u = User.query.filter_by(email=customer_client.email).first() if hasattr(customer_client, 'email') else db.session.get(User, seed['customer_id'])
        u.email_confirm_sent_at = datetime.utcnow()
        db.session.commit()
    page = customer_client.get('/account/profile').get_data(as_text=True)
    assert 'Please confirm your email address' in page and 'Send it again' in page


def test_resetting_a_password_by_email_also_confirms_the_address(app, seed, client):
    with app.app_context():
        u = db.session.get(User, seed['customer_id'])
        token = u.generate_reset_token()
        db.session.commit()
    client.post(f'/auth/reset-password/{token}', data={'password': 'brandnewpass1', 'confirm_password': 'brandnewpass1'})
    with app.app_context():
        assert db.session.get(User, seed['customer_id']).email_confirmed_at is not None
