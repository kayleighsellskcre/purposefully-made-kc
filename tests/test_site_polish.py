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
    assert real_deadline(datetime.utcnow() + timedelta(days=340)) is None      # almost a year away reads as a placeholder too
    from utils.districts import is_far_deadline
    assert is_far_deadline(datetime.utcnow() + timedelta(days=340)) and not is_far_deadline(None)


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


def test_a_shop_card_does_not_say_the_brand_twice():
    from utils.product_names import without_brand
    assert without_brand('BELLA+CANVAS Unisex Jersey Short Sleeve Tee', 'Bella+Canvas') == 'Unisex Jersey Short Sleeve Tee'
    assert without_brand('Port & Company Core Tee', 'Port & Company') == 'Core Tee'
    assert without_brand('Unisex Tee', 'Gildan') == 'Unisex Tee'          # no brand in the title: left alone
    assert without_brand('Gildan', 'Gildan') == 'Gildan'                  # never leave an empty title


def test_the_christmas_note_shows_until_the_cutoff_then_goes_away():
    from datetime import date
    from utils.business_info import holiday_note
    assert holiday_note(date(2026, 11, 20)) == 'Christmas orders: place yours by December 1.'
    assert holiday_note(date(2026, 12, 1)) is not None          # the cutoff day itself still counts
    assert holiday_note(date(2026, 12, 2)) is None


def test_group_orders_page_has_two_doors_and_named_payment_buttons(app, seed, guest):
    html = guest.get('/shop/group-orders').get_data(as_text=True)
    assert 'Find your store' in html and 'Start a group order' in html
    assert html.index('id="find"') < html.index('id="start"')                  # finding a store comes first
    for label in ('Everyone pays', 'We cover it all', 'We cover a set amount'):
        assert label in html
    assert 'Start a group order</a>' not in html.split('id="start"')[1]        # no three identical buttons


def test_the_header_has_four_choices_with_menus_and_an_account_icon(app, seed, guest):
    html = guest.get('/').get_data(as_text=True)
    nav = html.split('aria-label="Main"')[1].split('</nav>')[0]
    for top in ('>Shop</a>', '>Group Orders</a>', '>Custom Design</a>', '>About</a>'):
        assert top in nav
    assert '>Schools</a>' not in nav and '>Contact</a>' in nav and '>Design Gallery</a>' in nav     # still one click away, inside the menus
    assert 'Kids &amp; Baby' in nav and 'Company apparel' in nav and 'Find your school or team' in nav
    assert 'Log in or create an account' in html                                                  # a person icon, not a pill
    assert '>Register</a>' not in html.split('class="nav-icons"')[0].split('aria-label="Main"')[1].split('mobile-only')[0]


def test_buttons_follow_one_system_and_leave_the_admin_alone():
    css = open('static/css/main.css', encoding='utf-8').read()
    assert '--btn-rose:' in css and 'body:not(.is-admin) .btn-primary' in css       # one solid primary, not the gradient
    assert 'body:not(.is-admin) .btn-outline' in css and '.btn-link' in css         # one outline, one text link


def test_custom_design_page_asks_for_art_you_have_the_rights_to(guest, seed):
    html = guest.get('/custom-design/').get_data(as_text=True)
    assert 'art you have the rights to' in html and 'See something you love online' not in html
    assert 'Your logo, sketch or idea' in guest.get('/').get_data(as_text=True)


def test_color_swatches_have_names_for_screen_readers():
    import re
    custom = open('templates/shop/customize.html', encoding='utf-8').read()
    swatches = re.findall(r'<button type="button" class="bd-swatch"[^>]*>', custom)
    assert swatches and all('aria-label="' in s for s in swatches)
    coll = open('templates/collection/view.html', encoding='utf-8').read()
    assert 'class="color-swatch" role="img" aria-label="{{ v.color_name }}"' in coll
