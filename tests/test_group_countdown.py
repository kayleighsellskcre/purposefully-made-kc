"""Group store countdown: "Closes in 3 days" on the store page and on store cards."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from models import Collection, Organization, OrgSection, db
from utils.group_orders import closing_countdown, parse_order_deadline

CHICAGO = ZoneInfo('America/Chicago')


def _today():
    return datetime.now(CHICAGO).date()


def _deadline_in(app, seed, days, **fields):
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.order_deadline = parse_order_deadline((_today() + timedelta(days=days)).strftime('%Y-%m-%d'))
        c.is_active = True
        for key, value in fields.items():
            setattr(c, key, value)
        db.session.commit()


def test_the_countdown_wording(app, seed):
    for days, text in ((0, 'Last day to order'), (1, 'Closes tomorrow'), (3, 'Closes in 3 days'), (14, 'Closes in 14 days')):
        _deadline_in(app, seed, days)
        with app.app_context():
            assert closing_countdown(db.session.get(Collection, seed['collection_id'])) == text


def test_no_countdown_when_far_off_closed_not_open_or_no_deadline(app, seed):
    with app.app_context():
        assert closing_countdown(None) == ''
    _deadline_in(app, seed, 15)
    with app.app_context():
        assert closing_countdown(db.session.get(Collection, seed['collection_id'])) == ''
    _deadline_in(app, seed, -1)
    with app.app_context():
        assert closing_countdown(db.session.get(Collection, seed['collection_id'])) == ''
    _deadline_in(app, seed, 3, order_opens_at=datetime.utcnow() + timedelta(days=2))
    with app.app_context():
        assert closing_countdown(db.session.get(Collection, seed['collection_id'])) == ''
    _deadline_in(app, seed, 3, order_deadline=None)
    with app.app_context():
        assert closing_countdown(db.session.get(Collection, seed['collection_id'])) == ''


def test_the_store_page_shows_the_countdown(app, seed, guest):
    _deadline_in(app, seed, 3)
    html = guest.get(f"/c/{seed['collection_slug']}").get_data(as_text=True)
    assert 'Closes in 3 days' in html


def test_the_store_page_shows_nothing_when_the_deadline_is_far_off(app, seed, guest):
    _deadline_in(app, seed, 30)
    html = guest.get(f"/c/{seed['collection_slug']}").get_data(as_text=True)
    assert 'class="closes-pill"' not in html


def test_the_directory_and_organization_cards_show_the_countdown(app, seed, guest):
    _deadline_in(app, seed, 2, show_in_directory=True)
    assert 'Closes in 2 days' in guest.get('/shop/group-orders').get_data(as_text=True)
    with app.app_context():
        org = Organization(name='Rainbow Cheetahs', slug='rainbow-cheetahs', is_active=True)
        db.session.add(org)
        db.session.flush()
        db.session.add(OrgSection(organization_id=org.id, collection_id=seed['collection_id'], label='Basketball'))
        db.session.commit()
    assert 'Closes in 2 days' in guest.get('/org/rainbow-cheetahs').get_data(as_text=True)


def test_school_cards_show_the_countdown(app, seed, guest):
    from models import Product
    from utils import districts as DS
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Football'], {})])
        for school in d.schools.all():
            for store in DS.stores_of(school, True):
                store.products.append(tee)
                store.order_deadline = parse_order_deadline((_today() + timedelta(days=4)).strftime('%Y-%m-%d'))
        db.session.commit()
    assert guest.get('/org/desoto-usd-232').get_data(as_text=True).count('Closes in 4 days') == 1
    assert 'Closes in 4 days' in guest.get('/org/desoto-usd-232/mill-valley-high').get_data(as_text=True)
