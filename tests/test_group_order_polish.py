"""Group order polish: one Share for every store, My Group Orders grouped, no repeated notices, no em dashes."""
import re

from models import Collection, Organization, OrgSection, User, db
from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL
from utils import districts as DS
from tests.test_group_order_crawl import _scenario


def test_every_store_has_a_share_link_qr_and_flyer_not_only_district_stores(app, seed, guest):
    slug = seed['collection_slug']
    qr = guest.get(f'/c/{slug}/qr.png')
    assert qr.status_code == 200 and qr.data[:4] == b'\x89PNG'
    assert 'attachment' in guest.get(f'/c/{slug}/qr.png?download=1').headers['Content-Disposition']
    flyer = guest.get(f'/c/{slug}/flyer.pdf')
    assert flyer.status_code == 200 and flyer.data[:4] == b'%PDF'
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(flyer.data))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert 'Test Elementary Spirit Wear' in text and f'/c/{slug}' in text
    assert guest.get('/c/not-a-store/flyer.pdf').status_code == 404


def test_a_turned_off_store_has_no_public_flyer(app, seed, guest):
    with app.app_context():
        db.session.get(Collection, seed['collection_id']).is_active = False
        db.session.commit()
    assert guest.get(f"/c/{seed['collection_slug']}/flyer.pdf").status_code == 404


def test_my_group_orders_groups_stores_by_school_and_organization(app, seed, client, login):
    _scenario(app, seed)
    login(client, CUSTOMER_EMAIL)
    html = client.get('/account/group-orders').get_data(as_text=True)
    assert html.count('<details class="mgo-group"') == 3          # Mill Valley, Riverview, Rainbow Cheetahs
    for name in ('Mill Valley High', 'Riverview Elementary', 'Rainbow Cheetahs'):
        assert f'<span class="mgo-group-name">{name}</span>' in html
    assert 'School &middot; 4 stores' in html and 'Organization &middot; 2 stores' in html
    # single stores sit outside the groups, so a person with a few stores just sees a short list
    assert html.index('Coach Pays Tees') < html.index('<details class="mgo-group"')


def test_each_store_has_view_edit_orders_and_one_share_button(app, seed, client, login):
    _scenario(app, seed)
    login(client, CUSTOMER_EMAIL)
    html = client.get('/account/group-orders').get_data(as_text=True)
    with app.app_context():
        mine = Collection.query.filter_by(created_by_user_id=User.query.filter_by(email=CUSTOMER_EMAIL).first().id).count()
    assert html.count('class="dist-share-btn"') == mine           # one Share per store, never two
    assert html.count('btn-sm">Orders</a>') == mine and html.count('btn-sm">Edit</a>') == mine and html.count('View Store</a>') == mine
    assert 'Link, QR and flyer' not in html
    assert html.count('id="distShareDialog"') == 1


def test_the_store_page_says_the_deadline_once_and_has_no_hard_coded_mascot_text(app, seed, guest):
    with app.app_context():
        from utils.group_orders import parse_order_deadline
        c = db.session.get(Collection, seed['collection_id'])
        c.order_deadline = parse_order_deadline('2099-11-15')
        db.session.commit()
    html = guest.get(f"/c/{seed['collection_slug']}").get_data(as_text=True)
    assert html.count('November 15, 2099') == 1
    assert 'Falcon pride' not in html and 'Place your order by then' not in html


def test_no_em_dashes_in_group_order_pages(app, seed, client, login):
    _scenario(app, seed)
    login(client, ADMIN_EMAIL)
    pages = ['/shop/group-orders', '/shop/group-orders/create', '/shop/company-apparel', '/org/rainbow-cheetahs',
             '/org/rainbow-cheetahs/manage', '/c/rc-basketball', '/c/rc-basketball/share', '/c/acme-crew',
             '/c/coach-pays', '/account/group-orders', '/admin/collections', '/track',
             f"/shop/group-orders/{seed['collection_slug']}/edit", '/org/create']
    for path in pages:
        resp = client.get(path)
        assert resp.status_code == 200, path
        visible = re.sub(r'<(script|style)\b.*?</\1>|<!--.*?-->', '', resp.get_data(as_text=True), flags=re.S)
        text = re.sub(r'<[^>]+>', ' ', visible)
        assert '—' not in text, f'{path} has an em dash'
        assert '&mdash;' not in visible, f'{path} has an em dash'


def test_the_option_cards_line_up_and_company_apparel_is_a_note_under_them(client, seed):
    html = client.get('/shop/group-orders').get_data(as_text=True)
    assert html.count('class="go-option"') == 3
    assert 'class="go-option-note"' in html and 'See Company Apparel' in html
    assert 'go-option-link' not in html


def _unbalanced(html):
    """Tags that open and close in the wrong numbers, which is what throws a page layout out of its column."""
    from html.parser import HTMLParser

    class Counter(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = {}
        def handle_starttag(self, tag, attrs):
            if tag in ('div', 'section', 'details', 'ul', 'ol', 'table', 'form', 'nav', 'main'):
                self.depth[tag] = self.depth.get(tag, 0) + 1
        def handle_endtag(self, tag):
            if tag in self.depth:
                self.depth[tag] -= 1

    c = Counter()
    c.feed(re.sub(r'<(script|style)\b.*?</\1>|<!--.*?-->', '', html, flags=re.S))
    return {tag: n for tag, n in c.depth.items() if n}


def test_group_order_pages_have_balanced_markup(app, seed, client, login):
    _scenario(app, seed)
    login(client, ADMIN_EMAIL)
    pages = ['/shop/group-orders', '/shop/group-orders/create', '/shop/company-apparel', '/org/rainbow-cheetahs',
             '/org/rainbow-cheetahs/manage', '/c/rc-basketball', '/c/rc-basketball/share', '/c/acme-crew',
             '/c/coach-pays', '/account/group-orders', '/track', '/org/crawl-usd-1',
             '/org/crawl-usd-1/mill-valley-high', f"/shop/group-orders/{seed['collection_slug']}/edit"]
    for path in pages:
        assert _unbalanced(client.get(path).get_data(as_text=True)) == {}, path


def test_a_store_logo_strip_loads_its_first_images_right_away_and_has_a_failure_fallback(app, seed, guest):
    import json
    from models import Design
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        ids = []
        for n in range(8):
            d = Design(filename=f'logo{n}.png', file_path=f'uploads/designs/logo{n}.png', title=f'Logo {n}', is_gallery=True,
                       uploaded_by_user_id=seed['admin_id'])
            db.session.add(d)
            db.session.flush()
            ids.append(d.id)
        c.allowed_design_ids = json.dumps(ids)
        c.showcase_design_ids = json.dumps(ids)
        db.session.commit()
    html = guest.get(f"/c/{seed['collection_slug']}").get_data(as_text=True)
    loads = re.findall(r'<div class="group-order-showcase-item">\s*<img[^>]*loading="(\w+)"', html)
    assert loads == ['eager'] * 6 + ['lazy'] * 2
    assert 'js/image-fallback.js' in html
    js = open('static/js/image-fallback.js', encoding='utf-8').read()
    assert 'group-order-showcase-item' in js and 'logo-monogram.png' in js
    import os
    assert os.path.exists('static/img/logo-monogram.png')


def test_the_phone_layout_keeps_the_logo_strip_to_one_row(client):
    css = open('static/css/main.css', encoding='utf-8').read()
    block = css[css.index('/* Group store header: the logo strip'):]
    assert 'overflow-x: auto' in block and 'max-height: 160px' in block and '.page-header .group-order-showcase' in block
