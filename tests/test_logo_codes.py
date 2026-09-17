"""Group-order logo codes: 1, 1a, 1b for the presser chart."""
import json

from models import db, Collection, Design, Order, OrderItem
from utils.logo_codes import letter_suffix, logo_code_map, logo_families
from utils.production_stages import apply_stage


def _design(**kwargs):
    d = Design(
        filename=kwargs.get('filename', 'logo.png'),
        original_filename=kwargs.get('original_filename', 'logo.png'),
        file_path=kwargs.get('file_path', 'uploads/logo.png'),
        title=kwargs.get('title', 'Falcons'),
        is_gallery=True,
        design_fee=0,
    )
    for key, val in kwargs.items():
        if hasattr(d, key):
            setattr(d, key, val)
    db.session.add(d)
    db.session.flush()
    return d


def _collection(name='Riverview Falcons', slug='riverview-falcons-codes', design_ids=None):
    coll = Collection(
        name=name,
        slug=slug,
        allowed_design_ids=json.dumps(design_ids or []),
    )
    db.session.add(coll)
    db.session.flush()
    return coll


def test_letter_suffix_uses_a_then_aa():
    assert letter_suffix(0) == 'a'
    assert letter_suffix(1) == 'b'
    assert letter_suffix(25) == 'z'
    assert letter_suffix(26) == 'aa'


def test_main_logo_is_1_and_colors_are_lettered(app, seed):
    with app.app_context():
        main = _design(title='Falcons Crest', filename='crest.png', variant_label='Navy')
        white = _design(
            title='Falcons Crest', filename='crest-white.png',
            file_path='uploads/crest-white.png',
            parent_design_id=main.id, variant_label='White',
        )
        red = _design(
            title='Falcons Crest', filename='crest-red.png',
            file_path='uploads/crest-red.png',
            parent_design_id=main.id, variant_label='Red',
        )
        wordmark = _design(title='Falcons Wordmark', filename='word.png')
        coll = _collection(design_ids=[main.id, white.id, red.id, wordmark.id])
        db.session.commit()

        families = logo_families(Collection.query.get(coll.id))
        codes = logo_code_map(families)

        assert [f['number'] for f in families] == [1, 2]
        assert codes[main.id] == '1'
        assert codes[white.id] == '1a'
        assert codes[red.id] == '1b'
        assert codes[wordmark.id] == '2'
        assert families[0]['variants'][0]['label'] == 'Navy'
        assert [v['code'] for v in families[0]['variants']] == ['1', '1a', '1b']


def test_color_child_listed_first_still_keeps_parent_as_1(app, seed):
    with app.app_context():
        main = _design(title='Script', filename='script.png')
        alt = _design(
            title='Script', filename='script-alt.png',
            file_path='uploads/script-alt.png',
            parent_design_id=main.id, variant_label='Warmwhite',
        )
        coll = _collection(slug='child-first', design_ids=[alt.id, main.id])
        db.session.commit()
        codes = logo_code_map(logo_families(Collection.query.get(coll.id)))
        assert codes[main.id] == '1'
        assert codes[alt.id] == '1a'


def test_logo_chart_page_shows_codes(admin_client, app, seed):
    with app.app_context():
        main = _design(title='Outline Red Script', filename='outline.png', variant_label='Warmwhite')
        swapped = _design(
            title='Navy Swapped', filename='swapped.png',
            file_path='uploads/swapped.png',
            parent_design_id=main.id, variant_label='Navy swapped',
        )
        coll = _collection(slug='chart-page', design_ids=[main.id, swapped.id])
        db.session.commit()
        cid = coll.id

    resp = admin_client.get(f'/admin/production/logo-chart?collection={cid}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '1a' in body
    assert 'Navy swapped' in body
    assert 'Riverview Falcons' in body
    print_css = body.split('@media print')[-1]
    assert 'grid-template-columns: 1fr 1fr' in print_css
    assert 'height: 2.05in' in print_css


def test_group_order_admin_pages_link_to_logo_chart(admin_client, app, seed):
    cid = seed['collection_id']
    listing = admin_client.get('/admin/collections').get_data(as_text=True)
    assert 'Logo chart' in listing
    assert f'/admin/production/logo-chart?collection={cid}' in listing

    edit = admin_client.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert 'Logo chart' in edit
    assert f'/admin/production/logo-chart?collection={cid}' in edit
    with app.app_context():
        main = _design(title='Warmwhite Outline Red Script', filename='ww.png', variant_label='Warmwhite')
        alt = _design(
            title='Red Navy Swapped', filename='swap.png',
            file_path='uploads/swap.png',
            parent_design_id=main.id, variant_label='Navy swapped',
        )
        coll = _collection(slug='press-codes', design_ids=[main.id, alt.id])
        order = Order(
            order_number='PM-LOGO-1',
            email='maya@example.com',
            first_name='Maya',
            last_name='Parent',
            subtotal=30.0,
            total=30.0,
            payment_status='paid',
            collection_id=coll.id,
        )
        apply_stage(order, 'ready_to_press')
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=seed['tee_id'],
            product_name='Unisex Jersey Short Sleeve Tee',
            style_number='3001',
            size='M',
            color='Navy',
            quantity=1,
            unit_price=30.0,
            subtotal=30.0,
            design_id=alt.id,
            transfer_production=json.dumps({
                'front': {
                    'design_name': 'Red Navy Swapped',
                    'placement': 'center_chest',
                    'placement_label': 'Center Chest',
                    'width_display': '8.50',
                    'height_display': '6.27',
                    'age_group': 'adult',
                }
            }),
        ))
        db.session.commit()

    resp = admin_client.get('/admin/production/transfers?stage=ready_to_press')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '1a' in body
    assert 'xfer-logo-code' in body
