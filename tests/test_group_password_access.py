"""Admins see every group; everyone else needs the access code."""
from models import db, Collection


def _protect(app, seed, code='letmein'):
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.set_password(code)
        db.session.commit()
        return coll.slug


def test_a_guest_is_sent_to_the_access_code_page(guest, app, seed):
    slug = _protect(app, seed)
    resp = guest.get(f'/c/{slug}')
    assert resp.status_code == 302 and f'/c/{slug}/password' in resp.headers['Location']


def test_a_logged_in_customer_still_needs_the_code(customer_client, app, seed):
    slug = _protect(app, seed)
    resp = customer_client.get(f'/c/{slug}')
    assert resp.status_code == 302 and '/password' in resp.headers['Location']


def test_the_admin_sees_a_protected_group_without_the_code(admin_client, app, seed):
    slug = _protect(app, seed)
    assert admin_client.get(f'/c/{slug}').status_code == 200
    assert admin_client.get(f'/c/{slug}?path=fan').status_code == 200
    assert admin_client.get(f'/c/{slug}/share').status_code == 200


def test_the_admin_is_never_shown_the_access_code_page(admin_client, app, seed):
    slug = _protect(app, seed)
    resp = admin_client.get(f'/c/{slug}/password')
    assert resp.status_code == 302 and resp.headers['Location'].endswith(f'/c/{slug}')


def test_the_code_still_works_for_everyone_else(guest, app, seed):
    slug = _protect(app, seed)
    wrong = guest.post(f'/c/{slug}/password', data={'password': 'nope'})
    assert wrong.status_code == 200                       # stays on the access-code page
    assert guest.get(f'/c/{slug}').status_code == 302     # still locked
    right = guest.post(f'/c/{slug}/password', data={'password': 'letmein'})
    assert right.status_code == 302
    assert guest.get(f'/c/{slug}').status_code == 200


def test_the_admin_sees_a_protected_team_inside_an_organization(admin_client, client, app, seed):
    from tests.test_org_fan_wear import _build, _store
    _build(admin_client, app, seed)
    name = 'Basketball: Rainbow Cheetahs'
    with app.app_context():
        coll = Collection.query.filter_by(name=name).one()
        coll.set_password('letmein')
        db.session.commit()
    slug = _store(app, name)[1]
    assert admin_client.get(f'/c/{slug}').status_code == 200
    # the same browser, once the admin signs out, is a guest again
    admin_client.get('/auth/logout')
    assert client.get(f'/c/{slug}').status_code == 302
