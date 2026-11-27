"""Round 3 audit: /auth/emergency-unlock and /auth/promote-admin had no rate
limit, no logging, and a non-constant-time token check, giving an attacker
unlimited silent guesses at the token that grants admin takeover.
"""
from tests.conftest import ADMIN_EMAIL


def test_wrong_token_is_rejected_on_emergency_unlock(client, seed, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    resp = client.get('/auth/emergency-unlock?token=wrong')
    assert resp.status_code == 403


def test_wrong_length_token_is_rejected_without_500(client, seed, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    resp = client.get('/auth/emergency-unlock?token=x')
    assert resp.status_code == 403


def test_missing_token_is_rejected_on_emergency_unlock(client, seed, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    resp = client.get('/auth/emergency-unlock')
    assert resp.status_code == 403


def test_no_env_token_configured_rejects_everything(client, seed, monkeypatch):
    """If ADMIN_PROMOTE_TOKEN was never set, nothing should ever match it -
    including an empty/missing token compared against an empty expected."""
    monkeypatch.delenv('ADMIN_PROMOTE_TOKEN', raising=False)
    resp = client.get('/auth/emergency-unlock?token=')
    assert resp.status_code == 403


def test_correct_token_unlocks_the_admin_account(client, seed, app, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    with app.app_context():
        from models import db, User
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        admin.failed_logins = 3
        db.session.commit()

    resp = client.get('/auth/emergency-unlock?token=the-real-token')
    assert resp.status_code == 200
    assert b'unlocked' in resp.data

    with app.app_context():
        from models import User
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        assert admin.failed_logins == 0


def test_correct_token_promotes_the_admin_account(client, seed, app, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    with app.app_context():
        from models import db, User
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        admin.is_admin = False
        db.session.commit()

    resp = client.get('/auth/promote-admin?token=the-real-token', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        from models import User
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        assert admin.is_admin is True


def test_wrong_token_is_rejected_on_promote_admin(client, seed, app, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    with app.app_context():
        from models import db, User
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        admin.is_admin = False
        db.session.commit()

    client.get('/auth/promote-admin?token=wrong', follow_redirects=True)

    with app.app_context():
        from models import User
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        assert admin.is_admin is False


def test_repeated_wrong_guesses_get_rate_limited(client, seed, app, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    from app import limiter
    was_enabled = app.config.get('RATELIMIT_ENABLED')
    app.config['RATELIMIT_ENABLED'] = True
    limiter.enabled = True
    limiter.reset()
    try:
        last = None
        for _ in range(11):
            last = client.get('/auth/emergency-unlock?token=guess')
        assert last.status_code == 429
    finally:
        limiter.reset()
        app.config['RATELIMIT_ENABLED'] = was_enabled
        limiter.enabled = bool(was_enabled)


def test_a_password_in_the_link_is_ignored(client, seed, app, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    resp = client.get('/auth/emergency-unlock?token=the-real-token&pw=NewSecret123')
    assert resp.status_code == 200 and b'name="new_password"' in resp.data
    with app.app_context():
        from models import User
        assert not User.query.filter_by(email=ADMIN_EMAIL).first().check_password('NewSecret123')


def test_the_new_password_is_set_from_the_form_not_the_address(client, seed, app, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    resp = client.post('/auth/emergency-unlock', data={'token': 'the-real-token', 'new_password': 'NewSecret123'})
    assert resp.status_code == 200 and b'New password saved' in resp.data
    with app.app_context():
        from models import User
        assert User.query.filter_by(email=ADMIN_EMAIL).first().check_password('NewSecret123')


def test_the_form_rejects_a_wrong_token_and_a_short_password(client, seed, app, monkeypatch):
    monkeypatch.setenv('ADMIN_PROMOTE_TOKEN', 'the-real-token')
    monkeypatch.setenv('ADMIN_EMAIL', ADMIN_EMAIL)
    assert client.post('/auth/emergency-unlock', data={'token': 'wrong', 'new_password': 'NewSecret123'}).status_code == 403
    short = client.post('/auth/emergency-unlock', data={'token': 'the-real-token', 'new_password': 'abc'})
    assert short.status_code == 400 and b'too short' in short.data
