"""School district stores: District > Level > School > Stores, short links, QR codes, flyers, reports."""
import io
import zipfile
from datetime import date, datetime, timedelta

from models import Collection, District, Order, OrderItem, Organization, OrgSection, Product, User, db
from tests.conftest import ADMIN_EMAIL, CUSTOMER_EMAIL
from utils import districts as DS


def _make(app, seed, live=('Football', 'Volleyball')):
    """Desoto with a high school (Mill Valley) and an elementary (Riverview). Returns ids."""
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district(
            'Desoto USD 232',
            [('Mill Valley High', 'high', ['Football', 'Volleyball', 'Staff'], {'mascot': 'Jaguars', 'primary_color': '#1f4e79'}),
             ('Riverview Elementary', 'elementary', ['Band'], {'mascot': 'Falcons'})],
            deadline='2099-11-15')
        schools = {s.short_slug: s for s in d.schools.all()}
        mill = schools['mill-valley']
        for store in DS.stores_of(mill, include_inactive=True):
            if DS.store_label(store) in ('School Spirit',) + tuple(live):
                store.products.append(tee)
        db.session.commit()
        return {'district': d.id, 'mill': mill.id, 'river': schools['riverview'].id}


# ── structure ──────────────────────────────────────────────────────────────────────────────

def test_a_school_spirit_store_is_made_for_every_school_and_comes_first(app, seed):
    ids = _make(app, seed)
    with app.app_context():
        for key in ('mill', 'river'):
            stores = DS.stores_of(db.session.get(Organization, ids[key]), include_inactive=True)
            assert DS.store_label(stores[0]) == 'School Spirit'
            assert stores[0].store_kind == 'spirit'
        mill = DS.stores_of(db.session.get(Organization, ids['mill']), include_inactive=True)
        assert [DS.store_label(s) for s in mill] == ['School Spirit', 'Football', 'Volleyball', 'Staff']


def test_short_links_are_readable_and_do_not_take_site_words(app, seed):
    ids = _make(app, seed)
    with app.app_context():
        d = db.session.get(District, ids['district'])
        mill = db.session.get(Organization, ids['mill'])
        vb = next(s for s in DS.stores_of(mill) if DS.store_label(s) == 'Volleyball')
        assert d.short_slug == 'desoto'
        assert DS.short_path(vb, mill) == '/desoto/mill-valley/volleyball'
        assert DS.short_display(vb, mill) == 'purposefullymadekc.com/desoto/mill-valley/volleyball'
        assert DS.new_district_short('Admin') != 'admin'
        assert DS.new_district_short('Shop District') != 'shop'


def test_a_rename_never_changes_the_links(app, seed, client, login):
    ids = _make(app, seed)
    login(client, ADMIN_EMAIL)
    resp = client.post(f"/admin/districts/school/{ids['mill']}", data={'action': 'save', 'name': 'Mill Valley Senior High',
                       'level': 'high', 'mascot': 'Jaguars', 'delivery_mode': 'send_home'})
    assert resp.status_code == 302
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        assert mill.name == 'Mill Valley Senior High'
        assert mill.short_slug == 'mill-valley' and mill.school_slug == 'mill-valley-high'
    assert client.get('/desoto/mill-valley/volleyball').status_code == 302


# ── what parents see ───────────────────────────────────────────────────────────────────────

def test_the_district_page_groups_schools_by_level_and_hides_empty_headings(app, seed, guest):
    ids = _make(app, seed)
    html = guest.get('/org/desoto-usd-232').get_data(as_text=True)
    assert 'Find your school' in html
    assert 'High Schools' in html and 'Mill Valley High' in html and 'Jaguars' in html
    assert 'Middle Schools' not in html
    # Riverview has no products yet, so a visitor does not see it
    assert 'Riverview Elementary' not in html
    assert 'Elementary Schools' not in html
    assert 'Order by Nov 15' in html


def test_the_owner_sees_every_school_on_the_district_page(app, seed, client, login):
    _make(app, seed)
    login(client, ADMIN_EMAIL)
    html = client.get('/org/desoto-usd-232').get_data(as_text=True)
    assert 'Riverview Elementary' in html and 'Elementary Schools' in html


def test_the_school_page_leads_with_school_spirit_and_hides_stores_without_products(app, seed, guest):
    ids = _make(app, seed)
    html = guest.get('/org/desoto-usd-232/mill-valley-high').get_data(as_text=True)
    assert 'Wear it for anything.' in html
    assert html.index('School Spirit') < html.index('Football') < html.index('Volleyball')
    assert 'Staff' not in html.split('Sports and activities')[-1].split('</section>')[0]   # Staff has no products yet
    assert 'Home of the Jaguars' in html
    assert 'Desoto USD 232' in html and 'High Schools' in html      # breadcrumbs


def test_staff_store_goes_last_when_it_has_products(app, seed, guest):
    ids = _make(app, seed, live=('Football', 'Volleyball', 'Staff'))
    html = guest.get('/org/desoto-usd-232/mill-valley-high').get_data(as_text=True)
    assert html.rindex('Staff') > html.index('Volleyball')


def test_no_em_dashes_on_the_new_pages(app, seed, guest):
    _make(app, seed)
    for path in ('/org/desoto-usd-232', '/org/desoto-usd-232/mill-valley-high'):
        assert '—' not in guest.get(path).get_data(as_text=True)


def test_a_store_page_links_to_school_spirit_and_shows_breadcrumbs(app, seed, guest):
    ids = _make(app, seed)
    html = guest.get('/desoto/mill-valley/volleyball', follow_redirects=True).get_data(as_text=True)
    assert 'Also see School Spirit' in html
    assert 'Desoto USD 232' in html and 'Mill Valley High' in html
    spirit = guest.get('/desoto/mill-valley/school-spirit', follow_redirects=True).get_data(as_text=True)
    assert 'Also see School Spirit' not in spirit


def test_a_school_organization_url_goes_to_its_district_page(app, seed, guest):
    ids = _make(app, seed)
    with app.app_context():
        slug = db.session.get(Organization, ids['mill']).slug
    resp = guest.get(f'/org/{slug}')
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/org/desoto-usd-232/mill-valley-high')


def test_two_clicks_from_the_district_to_a_school_spirit_store(app, seed, guest):
    _make(app, seed)
    page = guest.get('/org/desoto-usd-232').get_data(as_text=True)
    assert 'href="/org/desoto-usd-232/mill-valley-high"' in page
    school = guest.get('/org/desoto-usd-232/mill-valley-high').get_data(as_text=True)
    assert '/c/' in school and 'School Spirit' in school


# ── existing stores keep working ───────────────────────────────────────────────────────────

def test_plain_organizations_and_their_links_are_untouched(app, seed, guest):
    with app.app_context():
        org = Organization(name='Rainbow Cheetahs', slug='rainbow-cheetahs', is_active=True)
        db.session.add(org)
        db.session.flush()
        db.session.add(OrgSection(organization_id=org.id, collection_id=seed['collection_id'], label='Basketball'))
        db.session.commit()
    assert guest.get('/org/rainbow-cheetahs').status_code == 200
    assert guest.get(f"/c/{seed['collection_slug']}").status_code == 200


def test_unknown_short_links_are_not_found_and_site_pages_still_work(app, seed, guest):
    _make(app, seed)
    assert guest.get('/nothing/at/all').status_code == 404
    assert guest.get('/nothing').status_code == 404
    assert guest.get('/shop/').status_code in (200, 302)
    assert guest.get('/about').status_code == 200


# ── share box: link, QR, flyer, zip ────────────────────────────────────────────────────────

def test_every_level_has_a_qr_png_and_a_one_page_flyer(app, seed, guest):
    _make(app, seed)
    for path in ('/desoto', '/desoto/mill-valley', '/desoto/mill-valley/volleyball'):
        qr = guest.get(path + '/qr.png')
        assert qr.status_code == 200 and qr.data[:8] == b'\x89PNG\r\n\x1a\n'
        flyer = guest.get(path + '/flyer.pdf')
        assert flyer.status_code == 200 and flyer.data[:4] == b'%PDF'
        assert flyer.data.count(b'/Type /Page\n') + flyer.data.count(b'/Type /Page ') >= 1
    assert 'attachment' in guest.get('/desoto/mill-valley/volleyball/qr.png?download=1').headers['Content-Disposition']


def test_the_flyer_names_the_store_link_and_deadline(app, seed):
    ids = _make(app, seed)
    with app.test_request_context():
        mill = db.session.get(Organization, ids['mill'])
        vb = next(s for s in DS.stores_of(mill) if DS.store_label(s) == 'Volleyball')
        text = DS.flyer_pdf(vb, mill)
    assert text[:4] == b'%PDF'
    assert text.count(b'/Type /Page') >= 1
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(text))
    assert len(reader.pages) == 1
    content = reader.pages[0].extract_text()
    assert 'Mill Valley Volleyball' in content
    assert 'purposefullymadekc.com/desoto/mill-valley/volleyball' in content
    assert 'Order by November 15' in content
    assert 'Jaguars' in content


def test_the_share_box_is_on_the_district_school_and_store_pages(app, seed, guest):
    _make(app, seed)
    for path in ('/org/desoto-usd-232', '/org/desoto-usd-232/mill-valley-high', '/desoto/mill-valley/football'):
        html = guest.get(path, follow_redirects=True).get_data(as_text=True)
        assert 'data-share-url=' in html and 'distShareDialog' in html and 'Download QR (PNG)' in html and 'data-flyer-print' in html and 'data-flyer-image' in html


def test_the_qr_zip_is_named_by_store(app, seed, client, login):
    ids = _make(app, seed)
    login(client, ADMIN_EMAIL)
    resp = client.get(f"/admin/districts/school/{ids['mill']}/qr.zip")
    assert resp.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(resp.data)).namelist()
    assert 'Mill Valley Volleyball.png' in names and 'Mill Valley School Spirit.png' in names
    whole = zipfile.ZipFile(io.BytesIO(client.get(f"/admin/districts/{ids['district']}/qr.zip").data)).namelist()
    assert any(n.endswith('Riverview Band.png') for n in whole) and 'Desoto USD 232.png' in whole


def test_a_guest_cannot_use_the_admin_zip(app, seed, guest):
    ids = _make(app, seed)
    assert guest.get(f"/admin/districts/{ids['district']}/qr.zip").status_code in (302, 401, 403)


def test_an_organizer_sees_link_qr_and_flyer_in_my_group_orders(app, seed, client, login):
    ids = _make(app, seed)
    with app.app_context():
        user = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        vb = next(s for s in DS.stores_of(db.session.get(Organization, ids['mill'])) if DS.store_label(s) == 'Volleyball')
        vb.created_by_user_id = user.id
        db.session.commit()
    login(client, CUSTOMER_EMAIL)
    html = client.get('/account/group-orders').get_data(as_text=True)
    assert '/desoto/mill-valley/volleyball/flyer.pdf' in html and 'data-share-url=' in html and 'distShareDialog' in html
    assert client.get('/desoto/mill-valley/volleyball/flyer.pdf').status_code == 200


# ── admin ──────────────────────────────────────────────────────────────────────────────────

def test_one_admin_screen_sets_up_a_whole_district(app, seed, client, login):
    login(client, ADMIN_EMAIL)
    resp = client.post('/admin/districts/new', data={
        'name': 'Olathe Schools', 'deadline': '2099-10-01', 'common_stores': 'Football, Volleyball', 'add_staff': '1',
        'schools_high': 'North High | Wolves\nSouth High', 'schools_middle': 'Central Middle | Bears | Band',
        'schools_elementary': 'Park Elementary'})
    assert resp.status_code == 302
    with app.app_context():
        d = District.query.filter_by(slug='olathe-schools').one()
        schools = {s.name: s for s in d.schools.all()}
        assert len(schools) == 4
        for school in schools.values():
            assert DS.store_label(DS.stores_of(school, True)[0]) == 'School Spirit'
        assert [DS.store_label(s) for s in DS.stores_of(schools['North High'], True)] == ['School Spirit', 'Football', 'Volleyball', 'Staff']
        assert [DS.store_label(s) for s in DS.stores_of(schools['Central Middle'], True)] == ['School Spirit', 'Band', 'Staff']
        assert schools['North High'].mascot == 'Wolves'
        assert all(s.order_deadline is not None for s in DS.stores_of(schools['South High'], True))


def test_the_admin_pages_open(app, seed, client, login):
    ids = _make(app, seed)
    login(client, ADMIN_EMAIL)
    with app.app_context():
        store = DS.stores_of(db.session.get(Organization, ids['mill']))[1]
        store_id = store.id
    for path in ('/admin/districts', '/admin/districts/new', f"/admin/districts/{ids['district']}",
                 f"/admin/districts/school/{ids['mill']}", f'/admin/districts/store/{store_id}/copy',
                 f"/admin/districts/{ids['district']}/report", '/admin/collections'):
        assert client.get(path).status_code == 200, path


def test_district_stores_stay_out_of_the_collections_list(app, seed, client, login):
    _make(app, seed)
    login(client, ADMIN_EMAIL)
    html = client.get('/admin/collections').get_data(as_text=True)
    assert 'Mill Valley Volleyball' not in html and 'Test Elementary Spirit Wear' in html


def test_copy_a_store_to_other_schools(app, seed, client, login):
    ids = _make(app, seed)
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        vb = next(s for s in DS.stores_of(mill) if DS.store_label(s) == 'Volleyball')
        vb.allowed_colors = '["Black"]'
        vb.restrict_options = True
        store_id = vb.id
        db.session.commit()
    login(client, ADMIN_EMAIL)
    resp = client.post(f'/admin/districts/store/{store_id}/copy', data={'school_id': [str(ids['river'])]})
    assert resp.status_code == 302
    with app.app_context():
        river = db.session.get(Organization, ids['river'])
        copy = next(s for s in DS.stores_of(river, True) if DS.store_label(s) == 'Volleyball')
        assert copy.name == 'Riverview Volleyball'
        assert copy.allowed_colors is None and copy.restrict_options is True      # the new school's colors, none chosen yet
        assert len(copy.products) == 1 and copy.short_slug == 'volleyball'
        assert copy.pending_organizer_email == river.pending_organizer_email


def test_apply_a_window_to_every_store_resets_reminders(app, seed):
    ids = _make(app, seed)
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        stores = DS.stores_of(mill, True)
        stores[1].deadline_reminder_sent_at = datetime.utcnow()
        n = DS.push_deadline(mill, '2099-12-01')
        db.session.commit()
        assert n == len(stores)
        assert stores[1].deadline_reminder_sent_at is None and stores[1].order_deadline.month == 12


def test_delivery_follows_the_school_setting(app, seed):
    ids = _make(app, seed)
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        assert all(s.group_kind == 'school' for s in DS.stores_of(mill, True))
        mill.delivery_mode = 'pickup'
        DS.sync_school_delivery(mill)
        assert all(s.group_kind == 'other' and s.shipping_enabled for s in DS.stores_of(mill, True))


# ── reports and filters ────────────────────────────────────────────────────────────────────

def _paid_order(app, seed, store_id, qty=3, number='PMKC-D1'):
    with app.app_context():
        o = Order(order_number=number, email='p@example.com', first_name='Pat', last_name='Parent', subtotal=30.0 * qty,
                  total=30.0 * qty, payment_status='paid', status='paid', payment_method='stripe', collection_id=store_id,
                  paid_at=datetime.utcnow())
        db.session.add(o)
        db.session.flush()
        db.session.add(OrderItem(order_id=o.id, product_id=seed['tee_id'], product_name='Tee', size='M', color='Black',
                                 quantity=qty, unit_price=30.0, subtotal=30.0 * qty, collection_id=store_id))
        db.session.commit()


def test_the_school_report_shows_orders_items_revenue_and_fundraiser_owed(app, seed):
    ids = _make(app, seed)
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        mill.fundraiser_cents = 200
        vb = next(s for s in DS.stores_of(mill) if DS.store_label(s) == 'Volleyball')
        store_id = vb.id
        db.session.commit()
    _paid_order(app, seed, store_id)
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        rep = DS.school_report(mill)
        assert (rep['orders'], rep['items'], rep['revenue']) == (1, 3, 90.0)
        assert rep['owed_cents'] == 600 and rep['balance_cents'] == 600
        mill.fundraiser_paid_cents = 250
        assert DS.school_report(mill)['balance_cents'] == 350
        total = DS.district_report(db.session.get(District, ids['district']))
        assert total['orders'] == 1 and total['owed_cents'] == 600


def test_blanks_and_labels_filter_by_district_level_school_or_store(app, seed, client, login):
    ids = _make(app, seed)
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        vb = next(s for s in DS.stores_of(mill) if DS.store_label(s) == 'Volleyball')
        fb = next(s for s in DS.stores_of(mill) if DS.store_label(s) == 'Football')
        vb_id, fb_id = vb.id, fb.id
    _paid_order(app, seed, vb_id, qty=2, number='PMKC-D2')
    _paid_order(app, seed, fb_id, qty=1, number='PMKC-D3')
    from utils.group_orders import filter_orders_to_collection
    with app.app_context():
        base = Order.query
        d, m = ids['district'], ids['mill']
        assert filter_orders_to_collection(base, f'd:{d}').count() == 2
        assert filter_orders_to_collection(base, f'l:{d}:high').count() == 2
        assert filter_orders_to_collection(base, f'l:{d}:middle').count() == 0
        assert filter_orders_to_collection(base, f's:{m}').count() == 2
        assert filter_orders_to_collection(base, str(vb_id)).count() == 1
        assert DS.blanks_total(db.session.get(District, d)) == {('Tee', 'Black', 'M'): 3}
    login(client, ADMIN_EMAIL)
    pages = ('/admin/production/blank-apparel-list', '/admin/production/master', '/admin/production/transfers',
             '/admin/orders/print-labels', '/admin/production/bulk-sheet', '/admin/production/dtf-batch-sheets',
             '/admin/production/logo-chart')
    for scope in (f'd:{ids["district"]}', f's:{ids["mill"]}', f'l:{ids["district"]}:high', str(vb_id)):
        for url in pages:
            assert client.get(f'{url}?collection={scope}').status_code == 200, (url, scope)
    html = client.get(f'/admin/production/blank-apparel-list?collection=d:{ids["district"]}').get_data(as_text=True)
    assert 'All of Desoto USD 232' in html


# ── tax exempt, only when the school pays ──────────────────────────────────────────────────

def test_a_tax_exempt_school_is_free_of_tax_only_when_it_pays(app, seed):
    ids = _make(app, seed)
    from utils import sales_tax
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        mill.tax_exempt = True
        mill.tax_expires_on = date.today() + timedelta(days=100)
        stores = DS.stores_of(mill, True)
        parent_store, school_store = stores[1], stores[2]
        school_store.payment_mode = 'organizer_pays'
        db.session.commit()
        parent_id, school_id = parent_store.id, school_store.id
    with app.test_request_context():
        from flask import session
        session['collection_id'] = parent_id
        assert sales_tax.school_pays_exempt() is False        # parents are taxed as normal
        session['collection_id'] = school_id
        assert sales_tax.school_pays_exempt() is True
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        mill.tax_expires_on = date.today() - timedelta(days=1)
        db.session.commit()
    with app.test_request_context():
        from flask import session
        session['collection_id'] = school_id
        assert sales_tax.school_pays_exempt() is False        # expired certificate


def test_the_school_can_be_marked_tax_exempt_from_admin(app, seed, client, login):
    ids = _make(app, seed)
    login(client, ADMIN_EMAIL)
    resp = client.post(f"/admin/districts/school/{ids['mill']}", data={
        'action': 'tax', 'tax_exempt': '1', 'tax_cert_number': 'KS-123', 'tax_expires_on': '2099-01-01'})
    assert resp.status_code == 302
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        assert mill.tax_exempt and mill.tax_cert_number == 'KS-123' and DS.school_exempt(mill)


# ── reuse of the existing group order machinery ────────────────────────────────────────────

def test_the_school_organizer_gets_the_existing_reminders_and_autopilot_emails(app, seed):
    ids = _make(app, seed)
    from utils import deadline_reminders as R
    with app.app_context():
        mill = db.session.get(Organization, ids['mill'])
        DS.apply_school_settings(mill, {'organizer_email': 'pto@millvalley.test'})
        for store in DS.stores_of(mill, True):
            store.pending_organizer_email = mill.pending_organizer_email
        db.session.commit()
        vb = next(s for s in DS.stores_of(mill) if DS.store_label(s) == 'Volleyball')
        key, org, label = R._group_key(vb)
        assert key == ('org', mill.id) and label == 'Volleyball'
        assert R._store_contacts(vb, org)[0][0] == 'pto@millvalley.test'


def test_school_stores_have_no_separate_fan_wear_tab(app, seed, guest):
    _make(app, seed)
    html = guest.get('/desoto/mill-valley/football', follow_redirects=True).get_data(as_text=True)
    assert '👕 Fan Wear' not in html and 'School Spirit' in html
