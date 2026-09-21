"""Round 2 audit item 4: honeypot, per-field limits, and a Subject dropdown."""
import pytest

from app import mail


def _form(**over):
    form = {
        'name': 'Casey Customer',
        'email': 'casey@example.com',
        'subject': 'Order question',
        'message': 'When will my order ship?',
    }
    form.update(over)
    return form


def test_the_honeypot_field_is_never_shown_to_a_person(guest):
    body = guest.get('/contact').get_data(as_text=True)
    assert 'name="website"' in body
    assert 'cf-hp' in body


def test_filling_the_honeypot_silently_drops_the_message(guest, outbox):
    resp = guest.post('/contact', data=_form(website='http://spam.example'), follow_redirects=True)
    assert resp.status_code == 200
    assert b'Thank you for reaching out' in resp.data
    assert len(outbox) == 0


def test_a_real_submission_with_an_empty_honeypot_sends(guest, outbox):
    resp = guest.post('/contact', data=_form(), follow_redirects=True)
    assert resp.status_code == 200
    assert len(outbox) == 1


@pytest.mark.parametrize('field,limit', [
    ('name', 100), ('email', 254), ('subject', 150), ('message', 3000),
])
def test_oversized_fields_are_rejected_server_side(guest, outbox, field, limit):
    resp = guest.post('/contact', data=_form(**{field: 'x' * (limit + 1)}), follow_redirects=True)
    assert resp.status_code == 200
    assert b'too long' in resp.data or b'longer than we can take' in resp.data
    assert len(outbox) == 0


def test_fields_right_at_the_limit_still_go_through(guest, outbox):
    resp = guest.post('/contact', data=_form(name='x' * 100), follow_redirects=True)
    assert resp.status_code == 200
    assert len(outbox) == 1


def test_subject_is_a_dropdown_with_the_expected_options(guest):
    body = guest.get('/contact').get_data(as_text=True)
    assert '<select id="subject" name="subject"' in body
    for option in ('Order question', 'Group order', 'Custom design', 'Something else'):
        assert option in body


def test_name_and_email_fields_carry_maxlength_and_autocomplete(guest):
    body = guest.get('/contact').get_data(as_text=True)
    assert 'maxlength="100"' in body
    assert 'maxlength="254"' in body
    assert 'maxlength="3000"' in body
    assert 'autocomplete="name"' in body
    assert 'autocomplete="email"' in body


def test_contact_page_shows_the_confirmed_phone_number(guest):
    body = guest.get('/contact').get_data(as_text=True)
    assert '(785) 249-1464' in body
    assert 'tel:+17852491464' in body
