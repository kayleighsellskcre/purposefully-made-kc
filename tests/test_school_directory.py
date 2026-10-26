"""The public Schools page: families find a district without a link, and a district can stay link-only."""
from models import District, db
from utils import districts as DS


def _two_districts(app):
    with app.app_context():
        a = DS.set_up_district('Desoto USD 232', [('Mill Valley High', 'high', ['Volleyball'], {})])
        b = DS.set_up_district('Private Academy', [('Oak Hall', 'elementary', [], {})])
        b.listed = False
        db.session.commit()


def test_the_schools_page_lists_listed_districts_only(app, seed, guest):
    _two_districts(app)
    html = guest.get('/school-districts').get_data(as_text=True)
    assert 'Desoto USD 232' in html and '/org/desoto-usd-232' in html
    assert 'Private Academy' not in html


def test_a_link_only_district_still_opens_by_its_link(app, seed, guest):
    _two_districts(app)
    with app.app_context():
        slug = District.query.filter_by(name='Private Academy').one().slug
    assert guest.get(f'/org/{slug}').status_code == 200


def test_the_menu_footer_and_group_orders_page_point_to_it(app, seed, guest):
    for path in ('/', '/group-orders'):
        html = guest.get(path).get_data(as_text=True)
        assert 'href="/school-districts"' in html
    assert '>Schools</a>' in guest.get('/').get_data(as_text=True)


def test_the_menu_keeps_schools_lit_on_the_district_and_school_pages(app, seed, guest):
    _two_districts(app)
    for path in ('/org/desoto-usd-232', '/org/desoto-usd-232/mill-valley-high'):
        html = guest.get(path).get_data(as_text=True)
        assert 'nav-link--current" aria-current="page">Schools</a>' in html, path
        assert 'nav-link--current" aria-current="page">Group Orders</a>' not in html
