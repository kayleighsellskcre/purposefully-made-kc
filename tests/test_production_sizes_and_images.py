"""Production Master + DTF list: back picture width AND height, little size letters, save-all images."""
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from models import Order, OrderItem, Product, db
from utils.back_logo_size import back_logo_dims
from utils.dtf_orders import build_dtf_shopping_list
from utils.size_codes import breakdown, size_code

BACK_FILE = Path('static/uploads/designs/zz_test_back_wide.png')


@pytest.fixture()
def back_picture():
    BACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGBA', (400, 200), (30, 60, 120, 255)).save(BACK_FILE)
    yield 'uploads/designs/zz_test_back_wide.png'
    BACK_FILE.unlink(missing_ok=True)


def _order(app, seed, number, items):
    with app.app_context():
        order = Order(order_number=number, email='x@example.com', first_name='Pat', last_name='Lee', subtotal=30, total=30,
                      status='paid', payment_status='paid', production_stage='order_received')
        db.session.add(order)
        db.session.flush()
        for extra in items:
            fields = dict(order_id=order.id, product_id=seed['tee_id'], product_name='Tee', style_number='3001',
                          size='M', color='Black', quantity=1, unit_price=30, subtotal=30, placement='center_chest')
            fields.update(extra)
            db.session.add(OrderItem(**fields))
        db.session.commit()
        return order.id


class _P:                      # a stand-in product for the size-letter rules
    def __init__(self, age):
        self.age_group, self.category, self.name = age, '', 'Tee'


def test_size_letters():
    assert size_code('M', _P('youth')) == 'YM' and size_code('XL', _P('youth')) == 'YXL' and size_code('S', _P('youth')) == 'YS'
    assert size_code('M', _P('adult')) == 'AM' and size_code('2XL', _P('adult')) == 'A2XL' and size_code('XXL', _P('adult')) == 'A2XL'
    assert size_code('Youth L') == 'YL' and size_code('3XL') == 'A3XL' and size_code('XS') == 'AXS' and size_code('4XL') == 'A4XL'
    assert breakdown({'AL': 1, 'YM': 2, 'A2XL': 1}) == 'YM ×2 · AL ×1 · A2XL ×1'


def test_a_back_picture_gets_a_real_width_and_height_and_remembers_its_shape(app, seed, back_picture):
    oid = _order(app, seed, 'SZ-1', [dict(back_design_file_name=back_picture)])
    with app.app_context():
        item = OrderItem.query.filter_by(order_id=oid).one()
        dims = back_logo_dims(item)
        assert dims['known'] and dims['height'] == pytest.approx(dims['width'] / 2, rel=0.01)
        assert dims['width_display'] and dims['height_display']
        assert json.loads(OrderItem.query.filter_by(order_id=oid).one().back_design_meta)['aspect_w'] == 400   # read once, then remembered


def test_an_unreadable_back_picture_never_breaks_the_page(app, seed):
    oid = _order(app, seed, 'SZ-2', [dict(back_design_file_name='uploads/designs/does-not-exist.png')])
    with app.app_context():
        dims = back_logo_dims(OrderItem.query.filter_by(order_id=oid).one())
        assert dims['width'] and dims['height'] is None and dims['known'] is False


def test_the_dtf_list_shows_back_height_and_the_sizes_ordered(app, seed, back_picture):
    ids = [_order(app, seed, 'SZ-3', [dict(back_design_file_name=back_picture, size='M', quantity=2)]),
           _order(app, seed, 'SZ-4', [dict(back_design_file_name=back_picture, size='M', quantity=1)])]
    with app.app_context():
        data = build_dtf_shopping_list(Order.query.filter(Order.id.in_(ids)).all())
        back = next(r for r in data['logos'] if r['placement'] == 'Center Back')
        assert back['height'] and back['height_display'] != 'see file' and back['quantity'] == 3
        assert back['sizes_text'] == 'AM ×3' and back['size_tag'] == 'AM'
        assert '[AM ×3]' in data['logo_copy']
        assert all('sizes' in r for r in data['csv_rows'])


def test_the_dtf_list_page_and_downloads_still_work(app, seed, admin_client, back_picture):
    _order(app, seed, 'SZ-5', [dict(back_design_file_name=back_picture)])
    page = admin_client.get('/admin/production/dtf-batch-sheets').get_data(as_text=True)
    assert 'dtf-size-tag' in page and 'Sizes:' in page
    assert admin_client.get('/admin/production/dtf-batch-sheets?format=csv').status_code == 200
    assert admin_client.get('/admin/production/dtf-batch-sheets?format=xlsx').status_code == 200


def test_the_production_master_shows_size_letters_and_back_dimensions(app, seed, admin_client, back_picture):
    _order(app, seed, 'SZ-6', [dict(back_design_file_name=back_picture, size='L')])
    page = admin_client.get('/admin/production/master?stage=order_received').get_data(as_text=True)
    assert 'class="size-tag"' in page and 'Print size:' in page and '″ W ×' in page and '″ H' in page
    assert 'Name ″ × ″' not in page                               # no more empty name/number lines on a picture back
    assert 'id="saveAll"' in page and 'Download all as a ZIP' in page and 'data-files=' in page


def test_save_all_zip_has_every_picture_named_by_size(app, seed, admin_client, back_picture):
    _order(app, seed, 'SZ-7', [dict(back_design_file_name=back_picture, size='XL', quantity=2),
                               dict(back_design_file_name=back_picture, size='S')])
    r = admin_client.get('/admin/production/master/images.zip?stage=order_received')
    assert r.status_code == 200 and r.mimetype == 'application/zip'
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert len(names) == 2
    assert any(n.startswith('AXL_') and 'in_' in n and '_x2_' in n and n.endswith('.png') for n in names)
    assert any(n.startswith('AS_') for n in names)


def test_save_all_with_nothing_to_save_says_so_and_only_admins_can_use_it(app, seed, admin_client):
    r = admin_client.get('/admin/production/master/images.zip?stage=order_received', follow_redirects=True)
    assert 'no print pictures' in r.get_data(as_text=True).lower()
    assert app.test_client().get('/admin/production/master/images.zip').status_code in (302, 401, 403)


def test_every_saved_print_file_is_named_by_shirt_size_print_size_and_quantity(app, seed):
    from utils.order_artwork import download_filename
    oid = _order(app, seed, 'SZ-NAME', [dict(size='L', quantity=3, design_id=seed['free_design_id']),
                                         dict(size='M', quantity=1, product_id=seed['youth_id'], design_id=seed['free_design_id'])])
    with app.app_context():
        order = db.session.get(Order, oid)
        adult, youth = order.items[0], order.items[1]
        name = download_filename(order, adult, 'front')
        assert name.startswith('AL_') and 'in_' in name and '_x3_' in name and 'SZ-NAME' in name and name.endswith('.png')
        assert download_filename(order, youth, 'front').startswith('YM_')
        assert download_filename(order, adult, 'front', 'AM+AL_9x9in_Falcons_x6_weekly.png') == 'AM_AL_9x9in_Falcons_x6_weekly.png'   # a name the page chose


def test_the_logo_cards_show_the_sized_file_name_and_a_save_button(app, seed, admin_client):
    _order(app, seed, 'SZ-CARD', [dict(size='L', quantity=2, design_id=seed['free_design_id']),
                                  dict(size='XL', quantity=1, design_id=seed['free_design_id'])])
    page = admin_client.get('/admin/production/master?stage=order_received').get_data(as_text=True)
    assert 'Saved as' in page and 'Save this file' in page
    assert 'AL' in page.split('Saved as')[1][:200] or 'AXL' in page.split('Saved as')[1][:200]


def test_the_label_words_are_read_from_the_sized_file_name():
    from utils.order_artwork import label_from_filename
    assert label_from_filename('AM_AL_9x9in_Falcons_x6_weekly.png') == 'AM AL   9 x 9 in   x6'
    assert label_from_filename('YM_8.5x7in_back-MIA_x1_PMKC-1001.png') == 'YM   8.5 x 7 in   x1'
    assert label_from_filename('whatever.png') == ''


def test_the_size_label_is_written_into_the_saved_picture(app):
    from utils.order_artwork import labeled_png
    art = Image.new('RGBA', (600, 400), (30, 60, 120, 255))
    out = io.BytesIO()
    art.save(out, format='PNG', dpi=(300, 300))
    labeled = Image.open(io.BytesIO(labeled_png(out.getvalue(), 'YM_8x7in_Falcons_x4_PMKC-1.png'))).convert('RGBA')
    assert labeled.width == 600 and labeled.height > 400                                   # a thin strip was added under the artwork
    assert labeled.crop((0, 0, 600, 400)).getchannel('A').getextrema() == (255, 255)       # the artwork itself is untouched
    strip = labeled.crop((0, 400, 600, labeled.height))
    assert strip.getchannel('A').getbbox()                                                  # there is writing in the strip
    assert labeled_png(out.getvalue(), 'no-size-in-this-name.png') == out.getvalue()        # no size words, nothing added
    assert labeled_png(b'not a picture', 'YM_8x7in_x_x1.png') == b'not a picture'          # an unreadable picture is left alone


def test_a_saved_back_picture_carries_its_label_and_plain_gives_the_original(app, seed, admin_client, back_picture):
    oid = _order(app, seed, 'SZ-LBL', [dict(back_design_file_name=back_picture, size='M', quantity=2, product_id=seed['youth_id'])])
    with app.app_context():
        item_id = OrderItem.query.filter_by(order_id=oid).one().id
    labeled = admin_client.get(f'/admin/orders/{oid}/items/{item_id}/save/back')
    plain = admin_client.get(f'/admin/orders/{oid}/items/{item_id}/save/back?plain=1')
    assert labeled.status_code == plain.status_code == 200
    first, second = Image.open(io.BytesIO(labeled.data)), Image.open(io.BytesIO(plain.data))
    assert second.size == (400, 200) and first.height > second.height and first.width == second.width
    assert 'YM_' in labeled.headers['Content-Disposition']


def test_the_same_back_picture_at_the_same_size_is_one_card_ordered_once(app, seed, admin_client, back_picture):
    _order(app, seed, 'SZ-SAME1', [dict(back_design_file_name=back_picture, size='M', quantity=1, product_id=seed['youth_id'])])
    _order(app, seed, 'SZ-SAME2', [dict(back_design_file_name=back_picture, size='M', quantity=1, product_id=seed['youth_id'])])
    _order(app, seed, 'SZ-SAME3', [dict(back_design_file_name=back_picture, size='L', quantity=1, product_id=seed['youth_id'])])
    page = admin_client.get('/admin/production/master?stage=order_received').get_data(as_text=True)
    assert page.count('Back design: zz test back wide') == 2            # YM once (for both orders) and YL once
    assert 'YM_' in page and '_x2_weekly' in page                       # the YM file says x2
    zipped = admin_client.get('/admin/production/master/images.zip?stage=order_received')
    names = zipfile.ZipFile(io.BytesIO(zipped.data)).namelist()
    assert len(names) == 2 and any(n.startswith('YM_') and '_x2_' in n for n in names)


def test_the_pictures_on_the_cards_are_the_labeled_files_so_saving_one_keeps_its_details(app, seed, admin_client, back_picture):
    _order(app, seed, 'SZ-PIC', [dict(back_design_file_name=back_picture, size='M', quantity=2, product_id=seed['youth_id'])])
    page = admin_client.get('/admin/production/master?stage=order_received').get_data(as_text=True)
    src = page.split('<img src="')[-1].split('"')[0] if '/save/back' in page else ''
    marker = '/save/back?'
    assert marker in page and 'inline=1' in page.split(marker)[1][:300]       # the card's picture comes from the labeled file
    from PIL import Image as _Image
    url = page.split('<img src="')[[i for i, part in enumerate(page.split('<img src="')) if marker in part.split('"')[0]][0]].split('"')[0].replace('&amp;', '&')
    shown = admin_client.get(url)
    assert shown.status_code == 200 and _Image.open(io.BytesIO(shown.data)).height > 200       # taller than the 200px art: the label is in it
