"""Admin Style checkup: lists the styles missing something the other styles have."""
from models import Product, db
from tests.test_proofs import _in_db


def test_checkup_page_lists_gaps_and_is_linked_from_products(app, seed, admin_client):
    page = admin_client.get('/admin/products').get_data(as_text=True)
    assert 'Style checkup' in page and '/admin/products/checkup' in page
    resp = admin_client.get('/admin/products/checkup')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Style checkup' in html and 'Size chart' in html           # the seed styles have no chart, so the gap is listed


def test_a_complete_style_is_not_listed(app, seed, admin_client):
    def complete():
        p = db.session.get(Product, seed['tee_id'])
        p.size_chart = '{"M": {"chest": "20", "length": "28"}}'
        p.description = 'A soft everyday tee made for printing, with a clean crew neck.'
        p.fabric_summary = '100% cotton'
        p.fit_guide = 'True to size'
        p.softness_rating = 3
        p.wholesale_cost = 6.0
        for v in p.color_variants:
            v.front_image_url = v.front_image_url or '/static/img/logo.png'
            v.back_image_url = '/static/img/logo.png'
        db.session.commit()
    _in_db(app, complete)
    html = admin_client.get('/admin/products/checkup').get_data(as_text=True)
    assert 'Unisex Jersey Short Sleeve Tee' not in html
    assert 'Heavy Blend Hooded Sweatshirt' in html


def test_guest_cannot_open_it(guest):
    assert guest.get('/admin/products/checkup').status_code in (302, 401, 403)
