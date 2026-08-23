"""The "Have Us Recreate It" design-request flow, end to end.

Covers the form, file validation, what gets saved, what the customer sees, what
the admin sees, and that a refresh or a double tap cannot duplicate a request.
"""
import io

import pytest

from models import db, CustomDesignRequest

PNG_HEADER = b'\x89PNG\r\n\x1a\n'


def a_png(size_bytes=2048, name='reference.png'):
    return (io.BytesIO(PNG_HEADER + b'\x00' * size_bytes), name)


def submit(client, description='Please recreate this logo in navy and cream.',
           upload=None, **extra):
    data = {'description': description}
    if upload is not None:
        data['reference_image'] = upload
    data.update(extra)
    return client.post('/custom-design/submit', data=data,
                       content_type='multipart/form-data',
                       follow_redirects=True)


def only_request(app):
    with app.app_context():
        return CustomDesignRequest.query.one()


def request_count(app):
    with app.app_context():
        return CustomDesignRequest.query.count()


# ── Getting to the form ──────────────────────────────────────────────────────

def test_the_landing_page_is_public(guest):
    assert guest.get('/custom-design/').status_code == 200


def test_a_guest_is_sent_to_sign_in_to_submit(guest):
    resp = guest.get('/custom-design/submit', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_the_form_opens_for_a_signed_in_customer(customer_client):
    resp = customer_client.get('/custom-design/submit')
    assert resp.status_code == 200
    assert 'reference_image' in resp.get_data(as_text=True)


# ── A good submission ────────────────────────────────────────────────────────

def test_a_complete_request_is_saved(customer_client, seed, app):
    submit(customer_client, upload=a_png())
    assert request_count(app) == 1


def test_a_saved_request_keeps_what_the_customer_typed(customer_client, seed, app):
    submit(customer_client, description='Cursive "Riverview" with a paw print.',
           upload=a_png())
    req = only_request(app)
    assert req.description == 'Cursive "Riverview" with a paw print.'


def test_a_saved_request_belongs_to_the_customer_who_sent_it(customer_client,
                                                             seed, app):
    submit(customer_client, upload=a_png())
    assert only_request(app).user_id == seed['customer_id']


def test_a_saved_request_starts_out_pending(customer_client, seed, app):
    submit(customer_client, upload=a_png())
    assert only_request(app).status == 'pending'


def test_the_uploaded_file_stays_linked_to_the_request(customer_client, seed, app):
    submit(customer_client, upload=a_png(name='my-logo.png'))
    req = only_request(app)
    assert req.reference_original_filename == 'my-logo.png'
    assert req.reference_file_path
    assert 'custom_requests' in req.reference_file_path


def test_the_uploaded_file_is_actually_written(customer_client, seed, app):
    import os
    submit(customer_client, upload=a_png())
    req = only_request(app)
    with app.app_context():
        path = os.path.join(app.config['UPLOAD_FOLDER'],
                            req.reference_file_path.replace('uploads/', '', 1))
    assert os.path.exists(path), 'the reference image was not saved to disk'


def test_the_stored_filename_is_not_the_one_the_customer_chose(customer_client,
                                                               seed, app):
    """A predictable path would let anyone guess another customer's artwork."""
    submit(customer_client, upload=a_png(name='logo.png'))
    stored = only_request(app).reference_file_path
    assert not stored.endswith('/logo.png')
    assert 'request_' in stored


def test_a_dangerous_filename_cannot_escape_the_upload_folder(customer_client,
                                                              seed, app):
    submit(customer_client, upload=a_png(name='../../evil.png'))
    stored = only_request(app).reference_file_path
    assert '..' not in stored


def test_the_customer_lands_on_a_confirmation(customer_client, seed):
    resp = submit(customer_client, upload=a_png())
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lower()
    assert 'thank' in body or 'received' in body or 'got your' in body


def test_the_request_shows_up_under_my_requests(customer_client, seed):
    submit(customer_client, description='A cardinal mascot, bold outline.',
           upload=a_png())
    body = customer_client.get('/custom-design/my-requests').get_data(as_text=True)
    assert 'cardinal mascot' in body.lower()


# ── Validation ───────────────────────────────────────────────────────────────

def test_a_missing_description_is_refused(customer_client, seed, app):
    resp = submit(customer_client, description='', upload=a_png())
    assert 'describe what you want' in resp.get_data(as_text=True).lower()
    assert request_count(app) == 0


def test_a_whitespace_only_description_is_refused(customer_client, seed, app):
    submit(customer_client, description='   \n  ', upload=a_png())
    assert request_count(app) == 0


def test_a_missing_file_is_refused(customer_client, seed, app):
    resp = submit(customer_client, upload=None)
    assert 'upload a reference image' in resp.get_data(as_text=True).lower()
    assert request_count(app) == 0


@pytest.mark.parametrize('name', ['notes.txt', 'sheet.xlsx', 'script.js',
                                  'payload.php', 'archive.zip', 'movie.mp4'])
def test_an_unsupported_file_type_is_refused(customer_client, seed, app, name):
    resp = submit(customer_client, upload=(io.BytesIO(b'not an image'), name))
    assert 'png, jpg, webp, or heic' in resp.get_data(as_text=True).lower()
    assert request_count(app) == 0


def test_an_empty_file_is_refused(customer_client, seed, app):
    resp = submit(customer_client, upload=(io.BytesIO(b''), 'empty.png'))
    assert 'could not read that image' in resp.get_data(as_text=True).lower()
    assert request_count(app) == 0


def test_an_oversized_file_is_refused_with_a_useful_message(customer_client,
                                                            seed, app):
    thirteen_mb = a_png(size_bytes=13 * 1024 * 1024)
    resp = submit(customer_client, upload=thirteen_mb)
    body = resp.get_data(as_text=True).lower()
    assert 'too large' in body
    assert '12 mb' in body, 'the message should say what the limit is'
    assert request_count(app) == 0


def test_a_rejected_submission_returns_you_to_the_form(customer_client, seed):
    resp = submit(customer_client, description='', upload=a_png())
    assert 'reference_image' in resp.get_data(as_text=True)


# ── Duplicates ───────────────────────────────────────────────────────────────

def test_reloading_the_confirmation_does_not_create_a_second_request(
    customer_client, seed, app
):
    submit(customer_client, upload=a_png())
    req_id = only_request(app).id
    for _ in range(3):
        assert customer_client.get(
            f'/custom-design/confirmation/{req_id}'
        ).status_code == 200
    assert request_count(app) == 1


def test_the_confirmation_page_does_not_resend_the_emails(customer_client, seed,
                                                          app, outbox):
    submit(customer_client, upload=a_png())
    req_id = only_request(app).id
    sent_after_submit = len(outbox)
    customer_client.get(f'/custom-design/confirmation/{req_id}')
    customer_client.get(f'/custom-design/confirmation/{req_id}')
    assert len(outbox) == sent_after_submit


# ── Who can see what ─────────────────────────────────────────────────────────

def test_a_customer_cannot_open_someone_elses_request(client, seed, login, app):
    from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL

    login(client, CUSTOMER_EMAIL)
    submit(client, description='My private artwork idea.', upload=a_png())
    req_id = only_request(app).id
    client.get('/auth/logout')

    login(client, OTHER_EMAIL)
    resp = client.get(f'/custom-design/confirmation/{req_id}',
                      follow_redirects=True)
    assert 'My private artwork idea.' not in resp.get_data(as_text=True)


def test_a_customer_does_not_see_someone_elses_request_in_their_list(
    client, seed, login, app
):
    from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL

    login(client, CUSTOMER_EMAIL)
    submit(client, description='My private artwork idea.', upload=a_png())
    client.get('/auth/logout')

    login(client, OTHER_EMAIL)
    body = client.get('/custom-design/my-requests').get_data(as_text=True)
    assert 'My private artwork idea.' not in body


def test_a_customer_cannot_delete_someone_elses_request(client, seed, login, app):
    from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL

    login(client, CUSTOMER_EMAIL)
    submit(client, upload=a_png())
    req_id = only_request(app).id
    client.get('/auth/logout')

    login(client, OTHER_EMAIL)
    assert client.post(f'/custom-design/requests/{req_id}/delete').status_code == 403
    with app.app_context():
        assert db.session.get(CustomDesignRequest, req_id).is_deleted is not True


def test_a_customer_can_remove_their_own_request_from_their_list(customer_client,
                                                                 seed, app):
    submit(customer_client, upload=a_png())
    req_id = only_request(app).id
    assert customer_client.post(
        f'/custom-design/requests/{req_id}/delete'
    ).status_code == 200
    body = customer_client.get('/custom-design/my-requests').get_data(as_text=True)
    assert f'/confirmation/{req_id}' not in body


def test_the_admin_sees_the_request_in_the_admin_area(admin_client, client,
                                                      seed, login, app):
    from tests.conftest import CUSTOMER_EMAIL

    shopper = client
    login(shopper, CUSTOMER_EMAIL)
    submit(shopper, description='Bold varsity lettering, gold on black.',
           upload=a_png())

    body = admin_client.get('/admin/custom-design-requests').get_data(as_text=True)
    assert 'Casey' in body or 'varsity' in body.lower()


def test_the_admin_can_open_the_request_detail(admin_client, client, seed,
                                               login, app):
    from tests.conftest import CUSTOMER_EMAIL

    login(client, CUSTOMER_EMAIL)
    submit(client, description='Bold varsity lettering.', upload=a_png())
    req_id = only_request(app).id
    resp = admin_client.get(f'/admin/custom-design-requests/{req_id}')
    assert resp.status_code == 200
    assert 'varsity' in resp.get_data(as_text=True).lower()
