"""Customer-facing fixes from the October 26 storefront audit."""
from datetime import datetime

from models import Design, db


def test_artwork_is_private_and_sharing_is_an_unchecked_choice(app, seed, customer_client):
    html = customer_client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'Your artwork stays private' in html
    assert 'id="shareInGallery"' in html and 'id="shareInGallery" checked' not in html
    assert "append('share_in_gallery', 'true')" in html


def test_the_legal_pages_agree_on_artwork_and_on_the_date(app, guest):
    terms = guest.get('/terms').get_data(as_text=True)
    privacy = guest.get('/privacy').get_data(as_text=True)
    assert 'Last updated: October 26, 2026' in terms and 'Last updated: October 26, 2026' in privacy
    assert 'Your artwork stays private' in terms and 'id="artwork"' in terms
    assert 'private and are stored only so we can print your order' in privacy


def test_the_faq_names_all_four_sponsor_choices(app, guest):
    html = guest.get('/faq').get_data(as_text=True)
    assert 'How can a sponsor pay for a group order?' in html and 'a dollar amount per person' in html


def test_kind_words_is_linked_only_when_there_are_reviews(app, guest, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, '_has_reviews', lambda: False)
    assert 'Kind Words</a></li>' not in guest.get('/faq').get_data(as_text=True)
    monkeypatch.setattr(app_module, '_has_reviews', lambda: True)
    assert 'Kind Words</a></li>' in guest.get('/faq').get_data(as_text=True)


def test_about_page_links_only_to_gallery_collections_that_have_designs(app, seed, guest):
    html = guest.get('/about').get_data(as_text=True)
    for key in ('school-spirit', 'holidays-seasons', 'music-entertainment', 'sports-game-day'):
        assert f'collection={key}' not in html       # the test gallery is empty, so no link leads to an empty page
    assert 'Just Because' in html


def test_pickup_is_explained_on_the_product_page(app, seed, guest):
    html = guest.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'free local pickup in Shawnee, Kansas' in html and 'exact address and times' in html


def test_school_deadlines_show_the_year(app, seed, guest):
    from utils import districts as DS
    with app.app_context():
        d = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Band'], {})])
        d.order_deadline = datetime(2027, 10, 25)
        db.session.commit()
    html = guest.get('/org/desoto-usd-232/mill-valley-high').get_data(as_text=True)
    assert 'Order by October 25, 2027' in html
