"""Round 2 audit item 6: the homepage had no product photos, mockups, or
reviews. Adds a real mockup photo Kayleigh supplied; no invented reviews or
testimonials.
"""
import os
import re


def test_homepage_shows_the_product_photo(guest):
    body = guest.get('/').get_data(as_text=True)
    assert 'img/homepage-mockup-flatlay.jpg' in body
    assert 'width="1672"' in body
    assert 'height="941"' in body


def test_the_photo_file_actually_exists():
    path = os.path.join('static', 'img', 'homepage-mockup-flatlay.jpg')
    assert os.path.isfile(path)


def test_homepage_does_not_invent_reviews_or_testimonials(guest):
    body = guest.get('/').get_data(as_text=True).lower()
    assert not re.search(r'\breviews?\b', body)
    assert 'testimonial' not in body
    assert '5 stars' not in body
    assert '★★★★★' not in body
