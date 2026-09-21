"""Round 2 audit item 3: the privacy policy rewrite.

The old copy was dated February 2026 and never mentioned children's
information in group orders, uploaded artwork, the payment providers, or the
hosting/storage providers, and it claimed cookies were used "to understand
how visitors use our site" even though no analytics code exists.
"""


def test_privacy_page_has_no_leftover_confirm_placeholders(guest):
    body = guest.get('/privacy').get_data(as_text=True)
    assert '[CONFIRM' not in body


def test_privacy_page_names_the_real_payment_providers(guest):
    body = guest.get('/privacy').get_data(as_text=True)
    assert 'Stripe' in body
    assert 'PayPal' in body


def test_privacy_page_names_the_real_infrastructure_providers(guest):
    body = guest.get('/privacy').get_data(as_text=True)
    assert 'Cloudflare' in body
    assert 'Brevo' in body
    assert 'OpenAI' in body


def test_privacy_page_covers_childrens_group_order_data(guest):
    body = guest.get('/privacy').get_data(as_text=True).lower()
    assert 'child' in body
    assert 'grade' in body or 'teacher' in body


def test_privacy_page_does_not_falsely_claim_analytics_cookies(guest):
    body = guest.get('/privacy').get_data(as_text=True).lower()
    assert 'understand how visitors use our site' not in body
    assert 'do not use advertising or analytics cookies' in body


def test_privacy_page_is_no_longer_dated_february(guest):
    body = guest.get('/privacy').get_data(as_text=True)
    assert 'February 2026' not in body
