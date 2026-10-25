"""FAQ, size guide, footer, menu and header search."""
import json

from models import Product, db


def test_faq_page_has_the_groups_and_real_policies(guest):
    resp = guest.get('/faq')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    for text in ('Ordering', 'Timing and shipping', 'Returns and fixes', 'Sizing and care',
                 'Group and company orders', 'flat $11', '7 days', 'id="shipping"', 'id="returns"'):
        assert text in html, text
    assert '—' not in html.split('<main')[1].split('</main>')[0]          # no em dashes in site copy


def test_size_guide_shows_saved_charts_by_brand(guest, app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        tee.size_chart = json.dumps({'S': {'chest': 18, 'length': 28}, 'M': {'chest': 20, 'length': 29}})
        db.session.commit()
    html = guest.get('/size-guide').get_data(as_text=True)
    assert 'Bella+Canvas' in html and '18"' in html and '29"' in html and 'Style 3001' in html


def test_size_guide_without_charts_still_helps(guest):
    html = guest.get('/size-guide').get_data(as_text=True)
    assert 'Size Guide' in html and 'send us a message' in html


def test_footer_and_menu_changes(guest):
    html = guest.get('/about').get_data(as_text=True)
    for text in ('footer-col-title">Help<', 'Size Guide', 'Shipping &amp; Returns', 'instagram.com/purposefullymadekc',
                 'facebook.com/purposefullymadekc', 'purposefullymadekc@gmail.com', 'class="footer-quote"',
                 'Custom Design', 'Company Apparel', 'id="siteSearchToggle"'):
        assert text in html, text
    assert 'tiktok' not in html.lower() and '>Have Us Recreate</a>' not in html
    assert 'nav-dropdown-menu' not in html               # Group Orders is one plain link, no pull-down


def test_header_search_finds_shirts(guest):
    found = guest.get('/api/site-search?q=jersey').get_json()
    assert [p['name'] for p in found['products']] == ['Unisex Jersey Short Sleeve Tee'] or \
        any('Jersey' in p['name'] for p in found['products'])
    assert set(found) == {'products', 'designs'}
    assert guest.get('/api/site-search?q=j').get_json() == {'products': [], 'designs': []}


def test_new_pages_are_in_the_sitemap(guest):
    xml = guest.get('/sitemap.xml').get_data(as_text=True)
    assert '/faq' in xml and '/size-guide' in xml


def test_smart_titles_fix_acronyms_and_small_words():
    from utils.titles import smart_title
    assert smart_title('Kc Heart Of The Midwest') == 'KC Heart of the Midwest'
    assert smart_title('KC HEART OF THE MIDWEST') == 'KC Heart of the Midwest'
    assert smart_title('go chiefs: the game day') == 'Go Chiefs: The Game Day'
    assert smart_title('pto mom') == 'PTO Mom'
