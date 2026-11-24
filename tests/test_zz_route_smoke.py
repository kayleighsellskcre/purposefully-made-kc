"""Every page that needs no id opens without an error, and every admin page refuses a visitor."""
import pytest

SKIP = ('/static', '/logout', '/auth/logout', '/emergency', '/stripe-webhook', '/api/', '/cart/clear')


def _plain_get_rules(app):
    out = []
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods or rule.arguments:
            continue
        if rule.rule.startswith(SKIP) or any(s in rule.rule for s in ('logout', 'emergency', 'download', 'export', 'sync', 'delete')):
            continue
        out.append(rule.rule)
    return sorted(set(out))


def test_every_plain_page_opens_for_a_visitor_without_a_server_error(app, seed, guest):
    broken = []
    for path in _plain_get_rules(app):
        if path.startswith('/admin'):
            continue
        r = guest.get(path, follow_redirects=False)
        if r.status_code >= 500:
            broken.append((path, r.status_code))
    assert not broken, broken


def test_every_admin_page_turns_a_visitor_away(app, seed, guest):
    open_to_all = []
    for path in _plain_get_rules(app):
        if not path.startswith('/admin'):
            continue
        r = guest.get(path, follow_redirects=False)
        if r.status_code == 200:
            open_to_all.append(path)
    assert not open_to_all, open_to_all


def test_every_plain_admin_page_opens_for_the_owner_without_a_server_error(app, seed, admin_client):
    broken = []
    for path in _plain_get_rules(app):
        if not path.startswith('/admin'):
            continue
        r = admin_client.get(path, follow_redirects=False)
        if r.status_code >= 500:
            broken.append((path, r.status_code))
    assert not broken, broken
