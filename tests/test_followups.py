"""Size guide reference charts, recreate turnaround, ready-weeks wording, tracking emails, contact photos."""
import io
import json
import threading

from models import Order, Product, db
from utils import customer_emails, ready_date


def _in_db(app, fn):
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


# ---- size guide ----

def test_size_guide_has_a_chart_and_fit_note_for_every_brand(guest, seed):
    html = guest.get('/size-guide').get_data(as_text=True)
    for text in ('District', 'Very Important Tee', 'Style DT6000', 'Independent Trading Co.', 'Style SS4500',
                 'MV Sport', 'Pro-Weave Crewneck Sweatshirt', 'Style 496',
                 'runs slightly slimmer', 'A generous, roomy fleece', 'full athletic fit',
                 '21 1/2"', '32 1/2"', 'Published measurements for our most popular'):
        assert text in html, text


def test_a_saved_chart_replaces_the_reference_chart(guest, app, seed):
    def go():
        db.session.add(Product(style_number='DT104', name='District Perfect Weight Tee', brand='District', category='Tee',
                               age_group='adult', base_price=20.0, is_active=True, available_sizes='["S"]',
                               available_colors='["Black"]', size_chart=json.dumps({'S': {'chest': 19, 'length': 28}})))
        db.session.commit()
    _in_db(app, go)
    html = guest.get('/size-guide').get_data(as_text=True)
    assert 'Style DT104' in html and 'Style DT6000' not in html


# ---- recreate turnaround and wording ----

def test_recreate_turnaround_is_one_to_two_business_days(guest, seed):
    assert 'Ready in 1 to 2 business days.' in guest.get('/custom-design/').get_data(as_text=True)
    faq = guest.get('/faq').get_data(as_text=True)
    assert 'Can you recreate my logo' in faq and 'within 1 to 2 business days' in faq


def test_weeks_phrase_follows_the_business_days_setting(app, seed):
    def go():
        out = []
        for days in (15, 10, 5, 25):
            ready_date.save_business_days(days)
            out.append(ready_date.weeks_phrase())
        ready_date.save_business_days(15)
        return out
    assert _in_db(app, go) == ['2 to 3 weeks', '1 to 2 weeks', 'about a week', '4 to 5 weeks']


def test_home_strip_uses_the_setting(guest, app, seed):
    _in_db(app, lambda: ready_date.save_business_days(10))
    try:
        assert 'Ready in 1 to 2 weeks' in guest.get('/').get_data(as_text=True)
    finally:
        _in_db(app, lambda: ready_date.save_business_days(15))


# ---- tracking ----

def test_tracking_link_per_carrier():
    assert customer_emails.tracking_url('USPS', '9400 1118') == 'https://tools.usps.com/go/TrackConfirmAction?tLabels=94001118'
    assert 'ups.com' in customer_emails.tracking_url('UPS', '1Z999')
    assert 'fedex.com' in customer_emails.tracking_url('FedEx', '7777')
    assert customer_emails.tracking_url('Other', '123') is None


def test_saving_tracking_emails_the_customer_once(admin_client, app, seed, monkeypatch):
    box = []
    monkeypatch.setattr(customer_emails, '_send', lambda to, subject, heading, paragraphs, **kw: box.append((to, subject, kw)) or True)

    def make():
        o = Order(order_number='PMKC-TRK1', email='amy@example.com', first_name='Amy', subtotal=10, total=10,
                  fulfillment_method='shipping', status='shipped')
        db.session.add(o)
        db.session.commit()
        return o.id
    oid = _in_db(app, make)
    page = admin_client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert 'Save and email tracking' in page
    admin_client.post(f'/admin/orders/{oid}/tracking', data={'carrier': 'USPS', 'tracking_number': '9400111'})
    admin_client.post(f'/admin/orders/{oid}/tracking', data={'carrier': 'USPS', 'tracking_number': '9400111'})   # unchanged
    assert len(box) == 1 and box[0][0] == 'amy@example.com' and box[0][1] == 'Tracking for your order'
    assert box[0][2]['button']['url'].endswith('9400111')
    admin_client.post(f'/admin/orders/{oid}/tracking', data={'carrier': 'UPS', 'tracking_number': '1Z999'})       # changed
    assert len(box) == 2
    assert _in_db(app, lambda: (db.session.get(Order, oid).carrier, db.session.get(Order, oid).tracking_number)) == ('UPS', '1Z999')


# ---- contact form photos ----

def test_contact_form_accepts_photos(guest, monkeypatch):
    import utils.admin_notifications as notes
    import utils.cloud_storage as cs
    seen = {}
    monkeypatch.setattr(cs, 'store_upload', lambda f, sub, prefix: f'https://cdn.example/{sub}/{f.filename}')
    monkeypatch.setattr(notes, 'notify_contact_message', lambda name, email, subject, message: seen.update(message=message))
    page = guest.get('/contact').get_data(as_text=True)
    assert 'enctype="multipart/form-data"' in page and 'name="photos"' in page
    resp = guest.post('/contact', data={'name': 'Amy', 'email': 'amy@example.com', 'subject': 'Custom design',
                                        'message': 'Like this one', 'photos': [(io.BytesIO(b'img'), 'idea.png')]},
                      content_type='multipart/form-data')
    assert resp.status_code == 302
    assert 'Like this one' in seen['message'] and 'https://cdn.example/contact/idea.png' in seen['message']


# ---- size boxes and footer ----

def test_empty_size_boxes_hide_the_zero_and_filled_ones_turn_solid():
    css = open('static/css/main.css', encoding='utf-8').read()
    assert '.size-card:not(.has-qty) .qty-val { display: none; }' in css
    assert '.size-card:not(.has-qty) .qty-dec' in css
    assert '.size-card.has-qty .size-label' in css and 'color: #fff' in css.split('.size-card.has-qty .size-label')[1][:200]


def test_footer_says_shawnee_kansas(guest, seed):
    html = guest.get('/about').get_data(as_text=True)
    footer = html.split('class="footer-contact"')[1].split('</p>')[0]
    assert 'Shawnee, Kansas' in footer and 'Kansas City' not in footer
