"""Round 2 audit item 7: drop "Luxury custom apparel" from the hero and
footer for a lower-key tone; keep "Premium Quality" as the feature heading.
Confirmed with Kayleigh: use the audit's suggested wording.
"""


def test_hero_no_longer_says_luxury_custom_apparel(guest):
    body = guest.get('/').get_data(as_text=True)
    assert 'Luxury custom apparel' not in body
    assert 'Custom apparel, made with intention.' in body


def test_footer_no_longer_says_luxury_custom_apparel(guest):
    body = guest.get('/').get_data(as_text=True)
    assert 'Luxury custom apparel for every occasion' not in body
    assert 'Custom apparel, made with intention, for every occasion' in body


def test_premium_quality_heading_is_unchanged(guest):
    body = guest.get('/').get_data(as_text=True)
    assert 'Premium Quality' in body
