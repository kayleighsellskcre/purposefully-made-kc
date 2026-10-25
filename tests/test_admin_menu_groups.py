"""The admin menu: short groups, one entry per job, related pages as tabs."""
import re

from tests.conftest import ADMIN_EMAIL

REPORTS = '/admin/operations/reports'


def _menu(html):
    """{group title: [item labels]} from the admin menu."""
    out = {}
    for m in re.finditer(r'<button type="button" class="ops-dropdown-btn".*?>\s*(.*?)\s*<svg.*?</button>\s*<div class="ops-dropdown-menu" role="menu">(.*?)</div>\s*</div>', html, re.S):
        title = re.sub(r'\s+', ' ', m.group(1)).replace('&amp;', '&').strip()
        labels = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', a)).replace('&amp;', '&').strip()
                  for a in re.findall(r'<a [^>]*role="menuitem"[^>]*>(.*?)</a>', m.group(2), re.S)]
        out[title] = labels
    return out


def test_the_money_tax_and_shop_groups_are_short_and_plainly_named(client, login):
    login(client, ADMIN_EMAIL)
    menu = _menu(client.get(REPORTS).get_data(as_text=True))
    assert 'Business & Operations' not in menu
    assert menu['Money'] == ['Profit & Loss', 'Expenses', 'Invoices', 'Who owes you', 'Payouts']
    assert menu['Tax & Year-End'] == ['Sales tax', 'Mileage', 'Year-end inventory count', 'CPA package']
    assert menu['Stock & Shop'] == ['Inventory', 'Vendors', 'Customers', 'Reviews', 'Growth', 'AI studio use', 'Site settings']
    assert all(len(items) <= 7 for items in menu.values()) or 'Storefront & Content' in menu


def test_no_page_is_listed_twice_and_the_overlapping_ones_are_gone_from_the_menu(client, login):
    login(client, ADMIN_EMAIL)
    html = client.get(REPORTS).get_data(as_text=True)
    labels = [x for items in _menu(html).values() for x in items]
    assert len(labels) == len(set(labels))
    for gone in ('Financial', 'Ledger', 'Payout check', 'Tax-exempt customers', 'Running low', 'Monthly bills', 'Equipment'):
        assert gone not in labels, gone                 # they are tabs on the page they belong to


def test_every_menu_link_opens(client, login):
    login(client, ADMIN_EMAIL)
    html = client.get(REPORTS).get_data(as_text=True)
    hrefs = set(re.findall(r'<a href="(/admin/[^"]*)" class="ops-drop-item', html))
    assert len(hrefs) > 20
    for href in sorted(hrefs):
        assert client.get(href).status_code == 200, href


def test_related_pages_show_the_same_tabs_with_the_current_one_marked(client, login):
    login(client, ADMIN_EMAIL)
    families = {
        REPORTS: ['Profit & Loss', 'Expenses', 'Monthly bills', 'Equipment', 'Every entry'],
        '/admin/operations/ledger': ['Profit & Loss', 'Expenses', 'Monthly bills', 'Equipment', 'Every entry'],
        '/admin/operations/payouts': ['Payouts', 'Month-by-month check'],
        '/admin/operations/sales-tax': ['Sales tax', 'Tax-exempt customers'],
        '/admin/operations/low-stock': ['Inventory', 'Running low'],
    }
    for path, tabs in families.items():
        html = client.get(path).get_data(as_text=True)
        found = [re.sub(r'<[^>]+>', '', t).replace('&amp;', '&') for t in re.findall(r'<a [^>]*class="ops-tab[^"]*"[^>]*>(.*?)</a>', html)]
        assert found == tabs, (path, found)
        assert html.count('aria-current="page"') >= 1 and html.count('ops-tab-on') >= 1


def test_pages_with_no_relatives_have_no_tab_strip(client, login):
    login(client, ADMIN_EMAIL)
    for path in ('/admin/operations/mileage', '/admin/operations/cpa-package', '/admin/operations/receivables'):
        resp = client.get(path)
        if resp.status_code == 200:
            assert 'class="ops-tabs' not in resp.get_data(as_text=True), path


def test_the_older_financial_page_is_still_reachable_from_reports(client, login):
    login(client, ADMIN_EMAIL)
    assert 'Financial Buckets' in client.get(REPORTS).get_data(as_text=True)
    href = re.search(r'<a href="([^"]+)">Open Financial Buckets', client.get(REPORTS).get_data(as_text=True)).group(1)
    assert client.get(href).status_code == 200


def test_packaging_guide_lives_under_daily_operations(client, login):
    login(client, ADMIN_EMAIL)
    menu = _menu(client.get(REPORTS).get_data(as_text=True))
    assert 'Packaging guide' in menu['Daily Operations']
