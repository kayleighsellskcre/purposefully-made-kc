"""Round 2 audit item 2: homepage and the Group Orders page must list the
same public stores.

The homepage used to also require an empty created_by_user_id, meant to hide
customer self-service stores, but every store made through the normal create
flow (including ones an admin makes) gets a creator recorded, so it silently
dropped admin-made stores from the homepage while they stayed on the Group
Orders directory.
"""
from models import db, Collection


def test_an_admin_made_public_store_appears_on_both_pages(client, seed):
    """The seeded collection has created_by_user_id set (an admin made it),
    is_active and show_in_directory True: it should show up in both places.
    """
    home = client.get('/')
    assert seed['collection_slug'] in home.get_data(as_text=True)

    directory = client.get('/shop/group-orders')
    assert seed['collection_slug'] in directory.get_data(as_text=True)


def test_password_protected_stores_are_off_the_homepage_but_in_the_directory(app, client, seed):
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.is_password_protected = True
        db.session.commit()

    home = client.get('/')
    assert seed['collection_slug'] not in home.get_data(as_text=True)

    directory = client.get('/shop/group-orders')
    assert seed['collection_slug'] in directory.get_data(as_text=True)


def test_a_store_past_its_deadline_is_off_the_homepage(app, client, seed):
    from datetime import datetime, timedelta
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.order_deadline = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

    home = client.get('/')
    assert seed['collection_slug'] not in home.get_data(as_text=True)
