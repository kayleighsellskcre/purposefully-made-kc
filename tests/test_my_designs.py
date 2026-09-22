"""Round 2 audit item 17: My Designs loaded 87 images at once with no
search. Adds pagination (24 per page) and a search box; the friendly
title (instead of a raw filename) was already in place from round 1.
"""
from models import db, Design


def _add_designs(app, customer_id, count, title_prefix='Design'):
    with app.app_context():
        for i in range(count):
            db.session.add(Design(
                filename=f'file{i}.png', original_filename=f'file{i}.png',
                file_path=f'uploads/designs/file{i}.png',
                title=f'{title_prefix} {i}', is_gallery=False,
                uploaded_by_user_id=customer_id,
            ))
        db.session.commit()


def test_my_designs_paginates_at_24_per_page(app, client, login, seed):
    from tests.conftest import CUSTOMER_EMAIL
    _add_designs(app, seed['customer_id'], 30)
    login(client, CUSTOMER_EMAIL)

    page1 = client.get('/account/designs').get_data(as_text=True)
    assert page1.count('<div class="design-card-image">') <= 24
    assert 'Page 1 of' in page1

    page2 = client.get('/account/designs?page=2').get_data(as_text=True)
    assert 'Page 2 of' in page2


def test_my_designs_search_finds_a_design_by_title(app, client, login, seed):
    from tests.conftest import CUSTOMER_EMAIL
    _add_designs(app, seed['customer_id'], 5, title_prefix='Sunset Camp')
    login(client, CUSTOMER_EMAIL)

    body = client.get('/account/designs?q=Sunset').get_data(as_text=True)
    assert 'Sunset Camp 0' in body
    assert 'search' in body.lower()


def test_my_designs_search_with_no_matches_shows_a_friendly_message(client, login, seed):
    from tests.conftest import CUSTOMER_EMAIL
    login(client, CUSTOMER_EMAIL)
    body = client.get('/account/designs?q=zzzznotfound').get_data(as_text=True)
    assert 'No designs match' in body


def test_my_designs_search_matches_original_filename_too(app, client, login, seed):
    from tests.conftest import CUSTOMER_EMAIL
    with app.app_context():
        db.session.add(Design(
            filename='family-reunion-2026.png',
            original_filename='family-reunion-2026.png',
            file_path='uploads/designs/family-reunion-2026.png',
            title=None, is_gallery=False,
            uploaded_by_user_id=seed['customer_id'],
        ))
        db.session.commit()
    login(client, CUSTOMER_EMAIL)
    body = client.get('/account/designs?q=reunion').get_data(as_text=True)
    assert 'Family Reunion 2026' in body


def test_my_designs_still_works_with_no_search(client, login, seed):
    from tests.conftest import CUSTOMER_EMAIL
    login(client, CUSTOMER_EMAIL)
    resp = client.get('/account/designs')
    assert resp.status_code == 200
    assert 'Recreated Art' in resp.get_data(as_text=True)


def test_a_customer_never_sees_another_customers_designs_in_search(app, client, login, seed):
    from tests.conftest import CUSTOMER_EMAIL
    _add_designs(app, seed['other_id'], 3, title_prefix='Not Yours')
    login(client, CUSTOMER_EMAIL)
    body = client.get('/account/designs?q=Not+Yours').get_data(as_text=True)
    # The search box legitimately echoes the query back into its value=
    # attribute - what must never appear is an actual result card.
    assert 'design-card-name">Not Yours' not in body
    assert 'No designs match' in body
