"""Customer status emails, the review request, the review form, approval and the owner's photo."""
import io
import threading
from datetime import datetime, timedelta

import pytest

from models import Collection, Order, Review, SystemSettings, db
from utils import customer_emails


def _in_db(app, fn):
    """Run fn() against the database on its own thread (the test clients keep a request context open)."""
    out = {}

    def run():
        with app.app_context():
            try:
                out['value'] = fn()
            except Exception as exc:          # pragma: no cover
                out['error'] = exc
    t = threading.Thread(target=run)
    t.start()
    t.join()
    if 'error' in out:
        raise out['error']
    return out.get('value')


@pytest.fixture()
def sent(monkeypatch):
    """Capture emails instead of sending them."""
    box = []

    def fake(to, subject, heading, paragraphs, **kw):
        box.append({'to': to, 'subject': subject, 'heading': heading, 'text': ' '.join(paragraphs),
                    'details': dict(kw.get('details') or []), 'button': kw.get('button')})
        return True
    monkeypatch.setattr(customer_emails, '_send', fake)
    return box


def _order(**kw):
    n = Order.query.count() + 1
    o = Order(order_number=f'PMKC-T{n}', email='amy@example.com', first_name='Amy', last_name='Kline',
              subtotal=30.0, total=30.0, fulfillment_method='pickup', status='ready', **kw)
    db.session.add(o)
    db.session.commit()
    return o.id


# ---- status emails ----

def test_pickup_email_uses_the_address_from_settings(app, seed, sent):
    def go():
        from utils.site_settings import set_setting
        set_setting('pickup_address', '12 Main St, Kansas City, KS')
        set_setting('pickup_notes', 'Porch pickup, text when you arrive')
        oid = _order()
        assert customer_emails.notify_stage_change(oid, 'packaged_ready') is True
    _in_db(app, go)
    mail = sent[0]
    assert mail['subject'] == 'Your order is ready for pickup'
    assert mail['details']['Pickup address'] == '12 Main St, Kansas City, KS'
    assert 'Porch pickup' in mail['details']['Pickup details']


def test_pickup_email_falls_back_to_the_shop_address(app, seed, sent):
    _in_db(app, lambda: customer_emails.notify_stage_change(_order(), 'packaged_ready'))
    assert sent[0]['details']['Pickup address'] == '4632 Woodstock Street, Shawnee, KS 66218'


def test_send_home_email_names_the_child_and_teacher(app, seed, sent):
    _in_db(app, lambda: customer_emails.notify_stage_change(
        _order(send_home_with_child=True, child_name='Maya', teacher_name='Ms. Lee', child_grade='3rd'), 'packaged_ready'))
    mail = sent[0]
    assert 'Maya' in mail['subject'] and 'Ms. Lee' in mail['text']
    assert mail['details']['Given to'] == 'Ms. Lee' and mail['details']['Grade'] == '3rd'


def test_group_pickup_spot_beats_the_shop_address(app, seed, sent):
    def go():
        from utils.site_settings import set_setting
        set_setting('pickup_address', 'Shop address')
        coll = Collection(name='Team', slug='team-x', pickup_address='Gym lobby, 5 School Rd', is_active=True)
        db.session.add(coll)
        db.session.commit()
        customer_emails.notify_stage_change(_order(collection_id=coll.id), 'packaged_ready')
    _in_db(app, go)
    assert sent[0]['details']['Pickup address'] == 'Gym lobby, 5 School Rd'


def test_shipped_email_has_tracking_and_shipping_orders_wait_for_it(app, seed, sent):
    def go():
        oid = _order(tracking_number='9400111', carrier='USPS')
        o = db.session.get(Order, oid)
        o.fulfillment_method = 'shipping'
        o.status = 'shipped'
        db.session.commit()
        assert customer_emails.notify_stage_change(oid, 'packaged_ready') is False      # nothing at "ready"
        assert customer_emails.notify_stage_change(oid, 'shipped') is True
    _in_db(app, go)
    assert len(sent) == 1 and sent[0]['subject'] == 'Your order is on its way'
    assert sent[0]['details']['Tracking'] == 'USPS 9400111'


def test_each_email_goes_out_once(app, seed, sent):
    def go():
        oid = _order()
        assert customer_emails.notify_stage_change(oid, 'packaged_ready') is True
        assert customer_emails.notify_stage_change(oid, 'packaged_ready') is False
    _in_db(app, go)
    assert len(sent) == 1


def test_picked_up_cancelled_and_switched_off_send_nothing(app, seed, sent):
    def go():
        from utils.site_settings import set_setting
        a = _order()
        db.session.get(Order, a).status = 'picked_up'
        db.session.commit()
        assert customer_emails.notify_stage_change(a, 'picked_up') is False
        b = _order()
        db.session.get(Order, b).status = 'cancelled'
        db.session.commit()
        assert customer_emails.notify_stage_change(b, 'packaged_ready') is False
        set_setting('customer_status_emails', '0')
        assert customer_emails.notify_stage_change(_order(), 'packaged_ready') is False
    _in_db(app, go)
    assert sent == []


def test_finishing_an_order_starts_the_review_clock(app, seed):
    def go():
        from utils.production_stages import apply_stage
        oid = _order()
        o = db.session.get(Order, oid)
        assert o.completed_at is None
        apply_stage(o, 'completed')
        db.session.commit()
        return db.session.get(Order, oid).completed_at is not None
    assert _in_db(app, go)


# ---- the 15 day review request ----

def test_review_request_goes_out_after_fifteen_days_only_once(app, seed, sent):
    def go():
        old = _order()
        recent = _order()
        never = _order()
        db.session.get(Order, old).completed_at = datetime.utcnow() - timedelta(days=16)
        db.session.get(Order, old).status = 'picked_up'
        db.session.get(Order, recent).completed_at = datetime.utcnow() - timedelta(days=10)
        db.session.get(Order, recent).status = 'picked_up'
        db.session.get(Order, never).status = 'picked_up'      # finished before this feature: no completion time
        db.session.commit()
        first = customer_emails.send_due_review_requests()
        second = customer_emails.send_due_review_requests()
        token = db.session.get(Order, old).review_token
        return first, second, token
    first, second, token = _in_db(app, go)
    assert (first, second) == (1, 0)
    mail = sent[0]
    assert 'photos of you wearing your items' in mail['text']
    assert mail['button']['url'].endswith(f'/review/{token}') and len(token) >= 16


# ---- the review form ----

@pytest.fixture()
def fake_storage(monkeypatch):
    import utils.cloud_storage as cs
    monkeypatch.setattr(cs, 'store_upload', lambda f, sub, prefix: f'https://cdn.example/{sub}/{f.filename}')


def _token(app):
    def go():
        oid = _order()
        o = db.session.get(Order, oid)
        o.review_token = 'tok_' + 'x' * 24
        db.session.commit()
        return o.review_token
    return _in_db(app, go)


def test_review_form_page_and_unknown_link(guest, app, seed):
    token = _token(app)
    html = guest.get(f'/review/{token}').get_data(as_text=True)
    assert 'How Did It Turn Out?' in html and 'take photos of you wearing your items' in html
    assert 'value="Amy K."' in html and 'type="file"' in html
    assert guest.get('/review/does-not-exist-at-all-1234').status_code == 404


def test_a_review_needs_words_or_a_photo(guest, app, seed):
    token = _token(app)
    resp = guest.post(f'/review/{token}', data={'name': 'Amy K.', 'body': ''})
    assert resp.status_code == 200 and 'Share a few words' in resp.get_data(as_text=True)
    assert _in_db(app, lambda: Review.query.count()) == 0


def test_review_with_words_and_photos_waits_for_approval(guest, app, seed, fake_storage):
    token = _token(app)
    resp = guest.post(f'/review/{token}', data={
        'name': 'Amy K.', 'body': 'We love them!', 'photos_ok': '1',
        'photos': [(io.BytesIO(b'\x89PNG fake'), 'me.png'), (io.BytesIO(b'notanimage'), 'doc.pdf')],
    }, content_type='multipart/form-data')
    assert resp.status_code == 302 and resp.headers['Location'].endswith(f'/review/{token}/thanks')
    row = _in_db(app, lambda: (lambda r: (r.status, r.photo_urls(), r.photos_ok, r.body))(Review.query.first()))
    assert row == ('pending', ['https://cdn.example/reviews/me.png'], True, 'We love them!')
    # a second visit does not allow a second review
    assert 'already have your review' in guest.get(f'/review/{token}').get_data(as_text=True)
    assert 'Thank You' in guest.get(f'/review/{token}/thanks').get_data(as_text=True)


def test_photo_stays_private_without_permission(guest, app, seed, fake_storage):
    token = _token(app)
    guest.post(f'/review/{token}', data={'name': 'Amy K.', 'body': 'Great', 'photos': [(io.BytesIO(b'img'), 'a.png')]},
               content_type='multipart/form-data')
    assert _in_db(app, lambda: Review.query.first().photos_ok) is False


# ---- approval and the homepage ----

def test_only_approved_reviews_reach_the_homepage(admin_client, app, seed):
    def make():
        for name, status, ok in (('Pending Pam', 'pending', False), ('Approved Ann', 'approved', True),
                                 ('Hidden Hal', 'hidden', True)):
            db.session.add(Review(name=name, body=f'Words from {name}', status=status, photos_ok=ok,
                                  photos='["https://cdn.example/p.png"]'))
        db.session.commit()
    _in_db(app, make)
    home = admin_client.get('/').get_data(as_text=True)
    assert 'Words from Approved Ann' in home and 'https://cdn.example/p.png' in home
    assert 'Pending Pam' not in home and 'Hidden Hal' not in home


def test_admin_can_approve_hide_and_delete(admin_client, app, seed):
    rid = _in_db(app, lambda: (lambda r: (db.session.add(r), db.session.commit(), r.id)[2])(Review(name='Amy K.', body='Hi', status='pending')))
    page = admin_client.get('/admin/operations/reviews').get_data(as_text=True)
    assert 'Amy K.' in page and '1 waiting for you' in page
    admin_client.post('/admin/operations/reviews', data={'review_id': rid, 'action': 'approve'})
    assert _in_db(app, lambda: db.session.get(Review, rid).status) == 'approved'
    admin_client.post('/admin/operations/reviews', data={'review_id': rid, 'action': 'hide'})
    assert _in_db(app, lambda: db.session.get(Review, rid).status) == 'hidden'
    admin_client.post('/admin/operations/reviews', data={'review_id': rid, 'action': 'delete'})
    assert _in_db(app, lambda: db.session.get(Review, rid)) is None


def test_reviews_admin_page_is_closed_to_guests(guest, seed):
    assert guest.get('/admin/operations/reviews').status_code in (302, 401, 403, 404)


# ---- the owner's photo, note and emails switch ----

def test_owner_photo_and_note_upload_show_on_about(admin_client, app, seed, monkeypatch):
    import utils.cloud_storage as cs
    monkeypatch.setattr(cs, 'store_upload', lambda f, sub, prefix: f'https://cdn.example/{sub}/{f.filename}')
    resp = admin_client.post('/admin/operations/site-settings', data={
        'section': 'owner', 'owner_name': 'Kayleigh', 'owner_note': 'I make every one by hand.',
        'owner_photo': (io.BytesIO(b'jpgbytes'), 'me.jpg')}, content_type='multipart/form-data')
    assert resp.status_code == 302
    about = admin_client.get('/about').get_data(as_text=True)
    assert 'https://cdn.example/site/me.jpg' in about and 'I make every one by hand.' in about
    contact = admin_client.get('/contact').get_data(as_text=True)
    assert 'https://cdn.example/site/me.jpg' in contact
    bad = admin_client.post('/admin/operations/site-settings', data={
        'section': 'owner', 'owner_photo': (io.BytesIO(b'x'), 'notes.txt')}, content_type='multipart/form-data')
    assert bad.status_code == 302


def test_email_settings_save(admin_client, app, seed):
    admin_client.post('/admin/operations/site-settings', data={
        'section': 'emails', 'pickup_address': '9 Oak Ave', 'pickup_notes': 'After 4pm'})      # box unchecked = off
    def read():
        from utils.site_settings import get_flag, get_setting
        return get_flag('customer_status_emails', True), get_setting('pickup_address')
    assert _in_db(app, read) == (False, '9 Oak Ave')
    page = admin_client.get('/admin/operations/site-settings').get_data(as_text=True)
    assert 'value="9 Oak Ave"' in page


# ---- the Kind Words page ----

def _seed_reviews(app):
    def make():
        db.session.add(Review(name='Amy K.', body='Loved them', status='approved', photos_ok=True,
                              photos='["https://cdn.example/a.png", "https://cdn.example/b.png"]'))
        db.session.add(Review(name='Private Pat', body='Nice', status='approved', photos_ok=False,
                              photos='["https://cdn.example/secret.png"]'))
        db.session.add(Review(name='Words Wes', body='Just words here', status='approved'))
        db.session.add(Review(name='Waiting Wren', body='Not yet', status='pending'))
        db.session.add(Review(name='Hidden Hal', body='Gone', status='hidden'))
        db.session.commit()
    _in_db(app, make)
    from utils import reviews_public
    reviews_public.clear_cache()


def test_kind_words_page_shows_approved_reviews_and_permitted_photos(guest, app, seed):
    _seed_reviews(app)
    html = guest.get('/reviews').get_data(as_text=True)
    assert 'Made for You, Worn with Love' in html
    assert 'Loved them' in html and 'Just words here' in html and 'Nice' in html
    assert html.count('class="kw-tile kw-photo"') == 2                 # Amy's two photos
    assert 'https://cdn.example/a.png' in html and 'https://cdn.example/b.png' in html
    assert 'secret.png' not in html                                    # no permission: the words only
    assert 'Waiting Wren' not in html and 'Hidden Hal' not in html
    assert 'data-filter="photo"' in html and 'data-filter="quote"' in html


def test_kind_words_page_does_not_exist_until_there_are_three_reviews(guest, app, seed):
    from utils import reviews_public
    reviews_public.clear_cache()
    assert guest.get('/reviews').status_code == 404                      # nothing yet
    def two():
        db.session.add(Review(name='Amy K.', body='Loved them', status='approved'))
        db.session.add(Review(name='Wes', body='Just words', status='approved'))
        db.session.commit()
    _in_db(app, two)
    reviews_public.clear_cache()
    assert guest.get('/reviews').status_code == 404                      # two is still not enough
    assert 'Kind Words</a>' not in guest.get('/about').get_data(as_text=True)
    _in_db(app, lambda: (db.session.add(Review(name='Pat', body='Nice', status='approved')), db.session.commit()))
    reviews_public.clear_cache()
    assert guest.get('/reviews').status_code == 200                      # the third one opens it
    assert 'Kind Words</a>' in guest.get('/about').get_data(as_text=True)


def test_footer_and_sitemap_link_appear_only_with_reviews(guest, app, seed):
    from utils import reviews_public
    reviews_public.clear_cache()
    assert 'Kind Words</a>' not in guest.get('/about').get_data(as_text=True)    # no reviews yet: no empty page to visit
    assert '/reviews' not in guest.get('/sitemap.xml').get_data(as_text=True)
    _seed_reviews(app)
    assert 'Kind Words</a>' in guest.get('/about').get_data(as_text=True)
    assert '/reviews' in guest.get('/sitemap.xml').get_data(as_text=True)
    assert 'Read more kind words' in guest.get('/').get_data(as_text=True)
