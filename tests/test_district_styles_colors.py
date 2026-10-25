"""District styles (set once) and school shirt colors (with a per-store override)."""
import json

from models import Collection, District, Organization, Product, db
from tests.conftest import ADMIN_EMAIL
from utils import districts as DS
from utils.group_orders import allowed_colors_for_product, parse_allowed_colors_by_brand


def _district(app, seed):
    """Two high schools with Football and Cheer; styles = the tee (comes in Black and White)."""
    with app.app_context():
        d = DS.set_up_district('Desoto USD 232', [
            ('Mill Valley High', 'high', ['Football', 'Cheer'], {}),
            ('Desoto High', 'high', ['Football'], {})])
        DS.set_district_styles(d, [seed['tee_id']])
        db.session.commit()
        schools = {s.short_slug: s.id for s in d.schools.all()}
        return d.id, schools['mill-valley'], schools['desoto']


def _store(app, school_id, label):
    with app.app_context():
        school = db.session.get(Organization, school_id)
        return next(s for s in DS.stores_of(school, True) if DS.store_label(s) == label).id


def _colors(store):
    return {c for names in parse_allowed_colors_by_brand(store.allowed_colors).values() for c in names}


def test_district_styles_reach_every_store_that_follows_them(app, seed):
    did, mill, _ = _district(app, seed)
    with app.app_context():
        d = db.session.get(District, did)
        for school in d.schools.all():
            for store in DS.stores_of(school, True):
                assert [p.id for p in store.products] == [seed['tee_id']]


def test_a_store_changed_by_hand_keeps_its_own_styles(app, seed):
    did, mill, _ = _district(app, seed)
    cheer = _store(app, mill, 'Cheer')
    football = _store(app, mill, 'Football')
    with app.app_context():
        db.session.get(Collection, cheer).products = [db.session.get(Product, seed['hoodie_id'])]
        d = db.session.get(District, did)
        DS.set_district_styles(d, [seed['tee_id'], seed['youth_id']])
        db.session.commit()
        assert [p.id for p in db.session.get(Collection, cheer).products] == [seed['hoodie_id']]
        assert {p.id for p in db.session.get(Collection, football).products} == {seed['tee_id'], seed['youth_id']}


def test_new_stores_start_with_district_styles_and_school_colors(app, seed):
    did, mill, _ = _district(app, seed)
    with app.app_context():
        school = db.session.get(Organization, mill)
        DS.set_school_colors(school, ['Black'])
        band = DS.add_store(school, 'Band')
        assert [p.id for p in band.products] == [seed['tee_id']]
        assert _colors(band) == {'Black'} and band.colors_custom is False


def test_the_color_grid_lists_the_colors_the_styles_come_in(app, seed):
    did, _, _ = _district(app, seed)
    with app.app_context():
        names = [c['name'] for c in DS.available_colors(db.session.get(District, did))]
        assert names == ['Black', 'White']


def test_each_school_has_its_own_colors_and_stores_follow(app, seed):
    did, mill, desoto = _district(app, seed)
    with app.app_context():
        DS.set_school_colors(db.session.get(Organization, mill), ['Black', 'White', 'Navy'])   # Navy: no style has it
        DS.set_school_colors(db.session.get(Organization, desoto), ['White'])
        db.session.commit()
        assert DS.school_color_names(db.session.get(Organization, mill)) == ['Black', 'White']
        for label in ('School Spirit', 'Football', 'Cheer'):
            assert _colors(db.session.get(Collection, _store(app, mill, label))) == {'Black', 'White'}
        assert _colors(db.session.get(Collection, _store(app, desoto, 'Football'))) == {'White'}


def test_one_store_can_have_its_own_colors_and_go_back(app, seed):
    did, mill, _ = _district(app, seed)
    with app.app_context():
        school = db.session.get(Organization, mill)
        DS.set_school_colors(school, ['Black'])
        cheer = db.session.get(Collection, _store(app, mill, 'Cheer'))
        DS.set_store_colors(cheer, ['Black', 'White'])
        assert cheer.colors_custom and _colors(cheer) == {'Black', 'White'}
        assert DS.colors_source(cheer, school) == 'custom for this store (2)'
        assert DS.colors_source(db.session.get(Collection, _store(app, mill, 'Football')), school) == 'from Mill Valley High (1)'
        DS.set_school_colors(school, ['White'])                      # the school changes; Cheer keeps its own
        assert _colors(cheer) == {'Black', 'White'}
        assert _colors(db.session.get(Collection, _store(app, mill, 'Football'))) == {'White'}
        DS.reset_store_colors(cheer)
        assert not cheer.colors_custom and _colors(cheer) == {'White'}


def test_the_allowed_colors_hide_a_color_the_style_does_not_have(app, seed):
    did, mill, _ = _district(app, seed)
    with app.app_context():
        school = db.session.get(Organization, mill)
        DS.set_school_colors(school, ['Black'])
        store = db.session.get(Collection, _store(app, mill, 'Football'))
        assert allowed_colors_for_product(db.session.get(Product, seed['tee_id']), store) == {'Black'}


def test_copying_a_store_keeps_the_styles_but_uses_the_new_schools_colors(app, seed):
    did, mill, desoto = _district(app, seed)
    cheer_id = _store(app, mill, 'Cheer')
    with app.app_context():
        DS.set_school_colors(db.session.get(Organization, mill), ['Black'])
        DS.set_school_colors(db.session.get(Organization, desoto), ['White'])
        cheer = db.session.get(Collection, cheer_id)
        DS.set_store_colors(cheer, ['Black', 'White'])
        cheer.products = [db.session.get(Product, seed['hoodie_id'])]
        DS.copy_store_to_schools(cheer, [desoto])
        db.session.commit()
        copy = db.session.get(Collection, _store(app, desoto, 'Cheer'))
        assert [p.id for p in copy.products] == [seed['hoodie_id']]
        assert _colors(copy) == {'White'} and copy.colors_custom is False


def test_the_district_screen_has_the_style_list_and_a_school_by_color_grid(app, seed, client, login):
    did, mill, desoto = _district(app, seed)
    login(client, ADMIN_EMAIL)
    html = client.get(f'/admin/districts/{did}').get_data(as_text=True)
    assert 'Styles for the whole district' in html and 'Unisex Jersey Short Sleeve Tee' in html
    assert f'name="c_{mill}"' in html and f'name="c_{desoto}"' in html
    assert 'data-label="black"' in html and 'data-label="white"' in html
    assert 'from Mill Valley High' in html


def test_saving_the_grid_and_the_styles_from_admin(app, seed, client, login):
    did, mill, desoto = _district(app, seed)
    login(client, ADMIN_EMAIL)
    client.post(f'/admin/districts/{did}', data={'action': 'colors', f'c_{mill}': ['Black', 'White'], f'c_{desoto}': ['White']})
    with app.app_context():
        assert DS.school_color_names(db.session.get(Organization, mill)) == ['Black', 'White']
        assert DS.school_color_names(db.session.get(Organization, desoto)) == ['White']
    client.post(f'/admin/districts/{did}', data={'action': 'styles', 'style': [str(seed['youth_id'])]})
    with app.app_context():
        d = db.session.get(District, did)
        assert DS.district_style_ids(d) == [seed['youth_id']]
        store = db.session.get(Collection, _store(app, mill, 'Football'))
        assert [p.id for p in store.products] == [seed['youth_id']]


def test_the_store_colors_page_saves_and_goes_back(app, seed, client, login):
    did, mill, _ = _district(app, seed)
    store_id = _store(app, mill, 'Cheer')
    login(client, ADMIN_EMAIL)
    assert 'Go back to school colors' not in client.get(f'/admin/districts/store/{store_id}/colors').get_data(as_text=True)
    client.post(f'/admin/districts/store/{store_id}/colors', data={'color': ['White']})
    page = client.get(f'/admin/districts/store/{store_id}/colors').get_data(as_text=True)
    assert 'custom for this store (1)' in page and 'Go back to school colors' in page
    client.post(f'/admin/districts/store/{store_id}/colors', data={'action': 'reset'})
    with app.app_context():
        assert db.session.get(Collection, store_id).colors_custom is False


def test_parents_see_only_the_allowed_colors_on_the_store_page(app, seed, guest):
    did, mill, _ = _district(app, seed)
    with app.app_context():
        DS.set_school_colors(db.session.get(Organization, mill), ['Black'])
        db.session.commit()
    html = guest.get('/desoto/mill-valley/football', follow_redirects=True).get_data(as_text=True)
    assert 'class="color-swatch" title="Black"' in html or 'title="Black"' in html
    assert 'title="White"' not in html and 'data-color="White"' not in html
