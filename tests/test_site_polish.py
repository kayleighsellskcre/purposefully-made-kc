"""Privacy and polish: page titles without names or numbers, tidy titles, real deadlines only, classes and family grouping."""
from datetime import datetime, timedelta


def test_store_titles_drop_phone_numbers_and_the_organizers_name():
    from utils.group_orders import store_title

    class Who:
        first_name, last_name = 'Jane', 'Smith'

    class Store:
        def __init__(self, name, card=None):
            self.name, self.card_title, self.created_by = name, card, Who()

    assert store_title(Store('Riverview Elementary STUCO - Jane Smith')) == 'Riverview Elementary STUCO'
    assert store_title(Store('Soccer Moms Club (913) 555-0142')) == 'Soccer Moms Club'
    assert store_title(Store('Soccer Moms Club 9135550142')) == 'Soccer Moms Club'
    assert store_title(Store('Anything', card='Falcons Spirit Wear')) == 'Falcons Spirit Wear'


def test_product_titles_stay_under_sixty_characters():
    from utils.product_names import TITLE_SUFFIX, fit_title
    for name in ('Comfort Colors Garment-Dyed Heavyweight Pocket Long Sleeve T-Shirt', 'Unisex Jersey Short Sleeve Tee', 'Gildan'):
        for prefix in ('', 'Customize '):
            assert len(fit_title(name, prefix) + TITLE_SUFFIX) <= 60
    assert fit_title('Unisex Jersey Short Sleeve Tee', 'Customize ') == 'Unisex Jersey Short Sleeve Tee'    # the whole name wins over the prefix


def test_only_a_real_deadline_is_shown():
    from utils.districts import real_deadline
    assert real_deadline(None) is None
    assert real_deadline(datetime.utcnow() + timedelta(days=20)) is not None
    assert real_deadline(datetime.utcnow() + timedelta(days=800)) is None      # a far-off placeholder


def test_seniors_and_family_are_classes_not_sports():
    from utils import districts as DS
    assert DS.guess_kind('Seniors') == 'family' and DS.guess_kind('Family') == 'family'
    assert DS.guess_kind('Volleyball') == 'sport'
    assert any(k == 'family' and h == 'Classes and family' for k, h, _l in DS.STORE_KINDS)


def test_the_dashboard_card_says_order_received(admin_client):
    html = admin_client.get('/admin/').get_data(as_text=True)
    assert 'Order Received' in html and 'New / Pending' not in html


def test_the_receipt_footer_says_shawnee_and_the_wait_is_said_once(app, seed):
    from flask import render_template
    from models import Order
    with app.app_context(), app.test_request_context():
        order = Order(order_number='PMKC-TEST', email='a@b.co', first_name='Pat', subtotal=10, total=10, tax=0,
                      fulfillment_method='pickup', payment_status='paid')
        html = render_template('email/order_confirmation.html', order=order, items=[], group_name=None)
    assert 'Shawnee, KS' in html and 'Kansas City, MO' not in html
    assert html.count('2 to 3 weeks') == 1


def test_a_ready_email_looks_like_the_receipt(app, seed):
    from flask import render_template
    with app.app_context(), app.test_request_context():
        html = render_template('email/sponsor_update.html', heading='Ready for pickup', paragraphs=['Hi Pat.'],
                               details=[('Order', 'PMKC-1'), ('Pickup', 'Shawnee')], button=None, note=None)
    assert 'PMKC-1' in html and 'Order Number' in html and 'Shawnee, KS' in html and 'Made with purpose, for you.' in html
