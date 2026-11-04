"""Customers stay signed in until they log out themselves."""
from tests.conftest import CUSTOMER_EMAIL, PASSWORD


def test_login_sets_a_year_long_remember_cookie_and_survives_losing_the_session_cookie(app, seed):
    client = app.test_client()
    resp = client.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': PASSWORD})
    cookies = ' '.join(resp.headers.getlist('Set-Cookie'))
    assert 'remember_token=' in cookies and 'Expires=' in cookies
    assert int(app.permanent_session_lifetime.total_seconds()) >= 365 * 86400
    client.delete_cookie('session')                       # the browser forgot the session
    assert b'/auth/logout' in client.get('/account/profile').data      # still signed in


def test_logging_out_really_logs_out(app, seed):
    client = app.test_client()
    client.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': PASSWORD})
    client.get('/auth/logout')
    assert client.get('/account/profile').status_code == 302
