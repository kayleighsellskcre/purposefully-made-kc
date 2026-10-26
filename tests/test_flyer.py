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


def test_pictures_that_load_are_placed_and_the_flyer_stays_one_page(app, seed, monkeypatch):
    ids = _setup(app, seed)
    with app.app_context():
        district, school, store = _objects(app, ids)
        monkeypatch.setattr(FL, '_store_logo_urls', lambda s, sc: ['/x/logo1.png', '/x/logo2.png'])
        monkeypatch.setattr(FL, '_shirt_picks', lambda products, store=None, limit=4: [('/x/s1.png', 'Tee'), ('/x/s2.png', 'Hoodie')])
        monkeypatch.setattr(FL, 'load_image', lambda url: _png('#%06x' % (hash(url) % 0xFFFFFF)))
        pages, images, text = _pages_and_images(DS.flyer_pdf(store, school))
    assert pages == 1
    assert images >= 5  # two logos, two shirts, the QR code
    assert 'PICK YOUR STYLE' in text and 'TEE' in text and 'HOODIE' in text
    assert 'SCAN TO ORDER' in text


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
