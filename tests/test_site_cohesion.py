"""Shared look: the menu marks the current page, the logo tucks in on scroll, headers match."""
import re


def _link(html, label):
    return re.search(r'<a [^>]*>\s*' + re.escape(label) + r'\s*</a>', html).group(0)


def test_menu_marks_the_page_you_are_on(guest):
    about = guest.get('/about').get_data(as_text=True)
    assert 'aria-current="page"' in _link(about, 'About')
    assert 'aria-current' not in _link(about, 'Contact')
    groups = guest.get('/shop/group-orders').get_data(as_text=True)
    assert 'nav-link--current' in _link(groups, 'Group Orders')
    company = guest.get('/shop/company-apparel').get_data(as_text=True)
    assert 'nav-link--current' in _link(company, 'Group Orders')       # part of the group-order area
    shop = guest.get('/shop/').get_data(as_text=True)
    assert 'nav-link--current' in _link(shop, 'Shop') and 'aria-current' not in _link(shop, 'Group Orders')


def test_the_logo_keeps_one_size_while_scrolling(guest):
    html = guest.get('/about').get_data(as_text=True)
    assert 'header-scroll.js' not in html                      # nothing shrinks the badge on scroll any more
    css = open('static/css/main.css', encoding='utf-8').read()
    assert '.navbar.is-scrolled .logo-image' not in css


def test_company_apparel_uses_the_standard_page_header(guest):
    html = guest.get('/shop/company-apparel').get_data(as_text=True)
    assert 'class="page-header"' in html and 'class="eyebrow"' in html and '<h1>Company Apparel</h1>' in html


def test_group_store_pages_share_one_header_without_ornaments(guest, seed):
    store = guest.get(f'/c/{seed["collection_slug"]}').get_data(as_text=True)
    assert 'class="team-orn"' not in store and 'class="page-header' in store
