"""The flyer: one page, the school's logos and a few shirts when they load, and always the QR, link and deadline."""
import io

from pypdf import PdfReader

from models import Collection, Organization, Product, db
from utils import districts as DS
from utils import flyer as FL


def _png(color):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGBA', (200, 200), color).save(out, format='PNG')
    return out.getvalue()


def _setup(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Volleyball'], {})])
        for school in d.schools.all():
            for store in DS.stores_of(school, True):
                store.products.append(tee)
        db.session.commit()
        school = d.schools.first()
        store = next(s for s in DS.stores_of(school, True) if DS.store_label(s) == 'Volleyball')
        return d.id, school.id, store.id


def _objects(app, ids):
    did, sid, cid = ids
    from models import District
    return db.session.get(District, did), db.session.get(Organization, sid), db.session.get(Collection, cid)


def _pages_and_images(data):
    reader = PdfReader(io.BytesIO(data))
    images = sum(len(p.images) for p in reader.pages)
    return len(reader.pages), images, ' '.join(p.extract_text() for p in reader.pages)


def _fake_pictures(monkeypatch, logos=2, shirts=2):
    monkeypatch.setattr(FL, '_store_logo_urls', lambda s, sc: [f'/x/logo{i}.png' for i in range(logos)])
    monkeypatch.setattr(FL, '_shirt_picks', lambda products, store=None, limit=8: [(f'/x/s{i}.png', ('Tee', 'Hoodie', 'Tank')[i % 3]) for i in range(shirts)])
    monkeypatch.setattr(FL, 'load_image', lambda url: _png('#%06x' % (hash(url) % 0xFFFFFF)))


def test_every_style_places_the_pictures_on_one_page_with_a_small_qr(app, seed, monkeypatch):
    ids = _setup(app, seed)
    _fake_pictures(monkeypatch, logos=2, shirts=4)
    with app.app_context():
        district, school, store = _objects(app, ids)
        for style in ('collage', 'showcase', 'bold'):
            pages, images, text = _pages_and_images(DS.flyer_pdf(store, school, style))
            assert pages == 1, style
            assert images >= 7, style                       # two logos, four shirts, the QR code
            assert 'SCAN TO ORDER' in text
            assert ('PURPOSEFULLY MADE KC' in text.upper()) == (style == 'bold')     # the others carry the PM wordmark picture
            assert ('PICK YOUR STYLE' in text) == (style != 'collage')
        text = _pages_and_images(DS.flyer_pdf(store, school, 'showcase'))[2]
        assert 'TEE' in text and 'HOODIE' in text


def test_the_collage_adapts_to_any_number_of_pictures(app, seed, monkeypatch):
    ids = _setup(app, seed)
    with app.app_context():
        district, school, store = _objects(app, ids)
        for logos, shirts in ((1, 0), (0, 3), (1, 1), (2, 3), (4, 8), (3, 12)):
            _fake_pictures(monkeypatch, logos=logos, shirts=shirts)
            pages, images, _text = _pages_and_images(DS.flyer_pdf(store, school, 'collage'))
            assert pages == 1 and images >= 1 + min(9, logos + shirts) - 1


def test_an_unknown_style_falls_back_to_the_collage(app, seed, guest):
    ids = _setup(app, seed)
    assert FL.normalize_style('nonsense') == 'collage' and FL.normalize_style('BOLD') == 'bold'
    with app.app_context():
        slug = db.session.get(Collection, ids[2]).slug
    for style in ('collage', 'showcase', 'bold', 'nonsense'):
        resp = guest.get(f'/c/{slug}/flyer.pdf?style={style}')
        assert resp.status_code == 200 and resp.data[:4] == b'%PDF'


def test_pictures_stored_on_this_server_load_inside_worker_threads(app):
    with app.app_context():
        urls = ['/static/img/logo.png']
        assert set(FL.load_images(urls)) == set(urls)


def test_pictures_that_fail_to_load_are_left_out_and_the_flyer_still_prints(app, seed, monkeypatch):
    ids = _setup(app, seed)
    with app.app_context():
        district, school, store = _objects(app, ids)
        monkeypatch.setattr(FL, '_store_logo_urls', lambda s, sc: ['/x/logo1.png'])
        monkeypatch.setattr(FL, '_shirt_picks', lambda products, store=None, limit=4: [('/x/s1.png', 'Tee')])
        monkeypatch.setattr(FL, 'load_image', lambda url: None)
        for obj, sc in ((store, school), (school, None), (district, None)):
            pages, images, text = _pages_and_images(DS.flyer_pdf(obj, sc))
            assert pages == 1 and images == 1  # only the QR code
            assert 'PICK YOUR STYLE' not in text and 'SCAN TO ORDER' in text


def test_a_missing_or_broken_picture_address_is_none_not_an_error(app):
    with app.app_context():
        assert FL.load_image('') is None
        assert FL.load_image('/static/does-not-exist.png') is None
        assert FL.load_image('not a url') is None


def test_every_level_makes_a_real_flyer_without_any_monkeypatching(app, seed):
    ids = _setup(app, seed)
    with app.app_context():
        district, school, store = _objects(app, ids)
        for obj, sc in ((store, school), (school, None), (district, None)):
            pages, images, text = _pages_and_images(DS.flyer_pdf(obj, sc))
            assert pages == 1 and images >= 1


def test_the_flyer_can_be_saved_as_an_image(app, seed, guest):
    ids = _setup(app, seed)
    with app.app_context():
        slug = db.session.get(Collection, ids[2]).slug
    resp = guest.get(f'/c/{slug}/flyer.png?style=bold&download=1')
    if resp.status_code == 302:                      # image renderer not installed here: it hands over the PDF instead
        assert '/flyer.pdf' in resp.headers['Location']
        return
    assert resp.status_code == 200 and resp.data[:4] == b'\x89PNG' and 'attachment' in resp.headers['Content-Disposition']
    from PIL import Image
    assert Image.open(io.BytesIO(resp.data)).size[0] > 1500


def test_group_logo_goes_on_the_shirt_photo_and_a_bad_picture_is_left_as_it_was(app):
    shirt, logo = _png('#3366aa'), _png('#ffffff')
    placed = FL.with_chest_logo(shirt, logo)
    assert placed != shirt and placed[:4] == b'\x89PNG'
    assert FL.with_chest_logo(b'not an image', logo) == b'not an image'


def test_every_district_level_has_an_image_flyer_too(app, seed, guest):
    ids = _setup(app, seed)
    with app.app_context():
        district, school, store = _objects(app, ids)
        paths = [f'/{district.short_slug}/flyer.png', f'/{district.short_slug}/{school.short_slug}/flyer.png']
    for path in paths:
        resp = guest.get(path)
        assert resp.status_code in (200, 302), path
