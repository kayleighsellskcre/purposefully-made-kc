"""A sponsor-covered store keeps its own place on the school page and says how it works."""
from models import Collection, Product, db
from utils import districts as DS


def _school_with_a_sponsored_store(app, seed):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district('Desoto USD 232', [('Riverview Elementary', 'elementary', ['Spirit Squad', 'Staff'], {'mascot': 'Falcons'})])
        school = d.schools.first()
        for store in DS.stores_of(school, True):
            store.products.append(tee)
        sponsored = next(s for s in DS.stores_of(school, True) if DS.store_label(s) == 'Staff')
        sponsored.payment_mode = 'company_sponsored'
        sponsored.sponsor_items_per_person = 2
        sponsored.sponsor_budget_per_person = 25.0
        sponsored.sponsor_message = 'Riverview PTO is covering staff shirts!'
        db.session.commit()
        return d.slug, school.school_slug, sponsored.slug


def test_the_school_page_lists_a_sponsored_store_apart_from_everyday_stores(app, seed, guest):
    district, school, store = _school_with_a_sponsored_store(app, seed)
    html = guest.get(f'/org/{district}/{school}').get_data(as_text=True)
    assert 'Sponsored orders' in html and 'Everyday spirit wear is separate' in html
    assert html.index('Sponsored orders') < html.index('Spirit Squad')           # its own block, before the team lists
    assert html.count(f'href="/c/{store}"') == 1                                 # listed once, not again under a category


def test_the_sponsored_store_explains_what_the_sponsor_covers_what_you_pay_and_when_the_organizer_is_billed(app, seed, guest):
    _district, _school, slug = _school_with_a_sponsored_store(app, seed)
    html = guest.get(f'/c/{slug}').get_data(as_text=True)
    assert 'Riverview PTO is covering staff shirts!' in html
    assert '2 items each, up to $25.00 per item' in html
    assert 'You pay for' in html and 'Anything extra' in html
    assert 'Shipping is not offered for this order' in html                       # a send-home school store does not ship
    with app.app_context():
        db.session.query(Collection).filter_by(slug=slug).update({'shipping_enabled': True})
        db.session.commit()
    assert 'shipping is yours to pay' in guest.get(f'/c/{slug}').get_data(as_text=True)
    assert 'Sales tax on covered items' in html and 'When the organizer is billed' in html
    assert 'printed after that bill is paid' in html


def test_a_school_with_no_sponsored_store_shows_no_sponsored_block(app, seed, guest):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Volleyball'], {})])
        for store in DS.stores_of(d.schools.first(), True):
            store.products.append(tee)
        db.session.commit()
        district, school = d.slug, d.schools.first().school_slug
    html = guest.get(f'/org/{district}/{school}').get_data(as_text=True)
    assert 'Sponsored orders' not in html
