"""Walk the whole group order area like a person would: open each page, follow every link, check every form.

Nothing here knows about a specific page. It starts from the group order front doors (as a visitor, a customer who runs
a group, and the owner), follows every link on the pages it finds, and fails if any link goes nowhere, any form posts to
an address that does not exist, or any in-page anchor points at nothing.
"""
import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urlparse

import pytest

from models import Collection, Organization, OrgSection, Product, User, db
from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL
from utils import districts as DS

SKIP_PREFIXES = ('/static/', '/uploads/', '/auth/logout', '/csp-report', '/cart/clear', '/leave')
SKIP_SUBSTRINGS = ('.pdf', '.zip', '.csv', '.xlsx', '.png')       # downloads are checked by their own tests
MAX_PAGES = 400


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.forms, self.ids, self.anchors = [], [], set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            self.ids.add(a['id'])
        if a.get('name') and tag == 'a':
            self.ids.add(a['name'])
        if tag == 'a' and a.get('href'):
            href = a['href'].strip()
            if href.startswith('#') and len(href) > 1:
                self.anchors.append(href[1:])
            else:
                self.links.append(href)
        if tag == 'form':
            self.forms.append(((a.get('method') or 'get').lower(), (a.get('action') or '').strip()))


def _internal(href):
    if not href or href.startswith(('mailto:', 'tel:', 'sms:', 'javascript:', '#', 'data:')):
        return None
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return None if parsed.netloc not in ('localhost', 'localhost:5000', 'localhost') else parsed.path
    return urldefrag(href)[0] or None


def _scenario(app, seed):
    """A district, a multi-team organization, a store where the organizer pays, and a company sponsored store."""
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        admin = User.query.filter_by(email=ADMIN_EMAIL).first()
        customer = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        d = DS.set_up_district('Crawl USD 1', [
            ('Mill Valley High', 'high', ['Football', 'Volleyball', 'Staff'], {'mascot': 'Jaguars'}),
            ('Riverview Elementary', 'elementary', ['Band'], {'mascot': 'Falcons'})], deadline='2099-11-15')
        DS.set_district_styles(d, [tee.id])
        for school in d.schools.all():
            for store in DS.stores_of(school, True):
                store.products.append(tee) if tee not in store.products else None
                store.created_by_user_id = customer.id
        org = Organization(name='Rainbow Cheetahs', slug='rainbow-cheetahs', is_active=True, created_by_user_id=customer.id)
        db.session.add(org)
        db.session.flush()
        for i, label in enumerate(('Basketball', 'Soccer')):
            store = Collection(name=f'{label}: Rainbow Cheetahs', slug=f'rc-{label.lower()}', is_active=True,
                               created_by_user_id=customer.id, show_in_directory=True)
            store.products.append(tee)
            db.session.add(store)
            db.session.flush()
            db.session.add(OrgSection(organization_id=org.id, collection_id=store.id, label=label, sort_order=i))
        roster = Collection(name='Coach Pays Tees', slug='coach-pays', is_active=True, payment_mode='organizer_pays',
                            created_by_user_id=customer.id, show_in_directory=True)
        roster.products.append(tee)
        company = Collection(name='Acme Crew', slug='acme-crew', is_active=True, payment_mode='company_sponsored',
                             created_by_user_id=customer.id, sponsor_items_per_person=1, show_in_directory=True)
        company.products.append(tee)
        mine = db.session.get(Collection, seed['collection_id'])
        mine.created_by_user_id = customer.id
        db.session.add_all([roster, company])
        db.session.commit()


def _crawl(client, app, starts, who):
    problems, seen, queue = [], set(), list(starts)
    rules = app.url_map.bind('localhost')
    while queue and len(seen) < MAX_PAGES:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        resp = client.get(path, follow_redirects=False)
        hops = 0
        while resp.status_code in (301, 302, 303, 307, 308) and hops < 5:
            loc = resp.headers.get('Location', '')
            nxt = _internal(loc) or loc
            if not nxt.startswith('/'):
                break                                                   # sent to another site (a payment page, say)
            resp = client.get(nxt, follow_redirects=False)
            hops += 1
        if resp.status_code != 200:
            problems.append(f'[{who}] {path} -> {resp.status_code}')
            continue
        if 'text/html' not in (resp.content_type or ''):
            continue
        page = _Page()
        page.feed(resp.get_data(as_text=True))
        for anchor in page.anchors:
            if anchor not in page.ids:
                problems.append(f'[{who}] {path}: the link #{anchor} points at nothing on the page')
        for method, action in page.forms:
            target = _internal(action) if action else path
            if target is None:
                continue
            try:
                rules.match(urlparse(target).path, method='POST' if method == 'post' else 'GET')
            except Exception:
                problems.append(f'[{who}] {path}: a {method.upper()} form goes to {action}, which does not exist')
        for href in page.links:
            target = _internal(href)
            if not target or target.startswith(SKIP_PREFIXES) or any(s in target for s in SKIP_SUBSTRINGS):
                continue
            if target.startswith(('/admin/sync', '/admin/import', '/admin/sanmar', '/admin/ssactivewear', '/admin/widen')):
                continue
            if target not in seen:
                queue.append(target)
    import os
    if os.environ.get('CRAWL_DEBUG'):
        print('VISITED', who, len(seen))
        for x in sorted(seen):
            print('   ', x)
    return problems, len(seen)


def test_a_visitor_can_follow_every_group_order_link(app, seed, guest):
    _scenario(app, seed)
    problems, n = _crawl(guest, app, ['/shop/group-orders', '/shop/company-apparel', '/org/rainbow-cheetahs',
                                      '/org/crawl-usd-1', '/org/crawl-usd-1/mill-valley-high',
                                      f"/c/{seed['collection_slug']}", '/c/coach-pays', '/c/acme-crew'], 'visitor')
    assert n > 15
    assert not problems, '\n'.join(problems)


def test_a_group_organizer_can_follow_every_link_in_their_account(app, seed, client, login):
    _scenario(app, seed)
    login(client, CUSTOMER_EMAIL)
    starts = ['/account/group-orders', '/shop/group-orders/create', f"/c/{seed['collection_slug']}/share",
              '/c/coach-pays/share', '/c/acme-crew/share', '/org/rainbow-cheetahs/manage', '/shop/group-orders',
              f"/shop/group-orders/{seed['collection_slug']}/edit", '/shop/group-orders/coach-pays/edit',
              '/shop/group-orders/acme-crew/edit', '/c/acme-crew/manage-sponsored']
    problems, n = _crawl(client, app, starts, 'organizer')
    assert n > 15
    assert not problems, '\n'.join(problems)


def test_the_owner_can_follow_every_group_order_link_in_admin(app, seed, client, login):
    _scenario(app, seed)
    login(client, ADMIN_EMAIL)
    with app.app_context():
        district = db.session.query(Organization).filter(Organization.district_id.isnot(None)).first().district_id
        store = Collection.query.filter_by(slug='rc-basketball').first().id
    starts = ['/admin/collections', f'/admin/collections/{store}/edit', '/admin/organizations', '/admin/districts',
              f'/admin/districts/{district}', f'/admin/districts/{district}/report', '/admin/collections/add',
              '/admin/production/blank-apparel-list']
    problems, n = _crawl(client, app, starts, 'owner')
    assert n > 15
    assert not problems, '\n'.join(problems)
