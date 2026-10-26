"""A school's stores branch into sports, activities, events, teachers and staff, and the school's main logos are shared."""
import io
import json

from models import Collection, Design, Organization, Product, db
from tests.conftest import ADMIN_EMAIL
from utils import districts as DS
from utils.group_orders import allowed_design_ids, showcase_design_ids


def _district(app, seed, stores=('Football', 'Band', "Mrs. Johnson's Class", 'Fall Festival', 'Staff')):
    with app.app_context():
        tee = db.session.get(Product, seed['tee_id'])
        d = DS.set_up_district('Desoto USD 232', [
            ('Riverview Elementary', 'elementary', list(stores), {'mascot': 'Falcons'}),
            ('Mill Valley High', 'high', ['Football'], {})])
        for school in d.schools.all():
            for store in DS.stores_of(school, True):
                store.products.append(tee)
        db.session.commit()
        schools = {s.short_slug: s.id for s in d.schools.all()}
        return d.id, schools['riverview'], schools['mill-valley']


def _logo(app, seed, name):
    with app.app_context():
        d = Design(filename=f'{name}.png', file_path=f'uploads/designs/{name}.png', title=name, uploaded_by_user_id=None)
        db.session.add(d)
        db.session.commit()
        return d.id


def _store(app, school_id, label):
    with app.app_context():
        school = db.session.get(Organization, school_id)
        return next(s for s in DS.stores_of(school, True) if DS.store_label(s) == label).id


def _ids(store, which='allowed'):
    return (allowed_design_ids if which == 'allowed' else showcase_design_ids)(store)


def test_a_store_name_tells_us_what_kind_of_store_it_is():
    cases = {'Football': 'sport', 'Volleyball': 'sport', 'Cross Country': 'sport', 'Band': 'activity', 'Choir': 'activity',
             'Robotics Club': 'activity', 'Student Council': 'activity', 'Fall Festival': 'event', 'Fun Run': 'event',
             "Mrs. Johnson's Class": 'teacher', 'Mr. Lee': 'teacher', '3rd Grade': 'teacher', 'Staff': 'staff'}
    for name, kind in cases.items():
        assert DS.guess_kind(name) == kind, name
    assert DS.parse_store_entry('teacher:Smith') == ('teacher', 'Smith')
    assert DS.parse_store_entry('event:Math Night') == ('event', 'Math Night')
    assert DS.parse_store_entry('sport:Chess') == ('sport', 'Chess')        # you can always choose yourself
    assert DS.parse_store_entry('Note: nothing') == (DS.guess_kind('Note: nothing'), 'Note: nothing')


def test_stores_are_named_so_flyers_and_cards_read_naturally(app, seed):
    did, riverview, _ = _district(app, seed)
    with app.app_context():
        names = {DS.store_label(s): s.name for s in DS.stores_of(db.session.get(Organization, riverview), True)}
        assert names['Football'] == 'Riverview Football'
        assert names["Mrs. Johnson's Class"] == "Mrs. Johnson's Class at Riverview"
        assert names['Fall Festival'] == 'Fall Festival at Riverview'
        kinds = {DS.store_label(s): s.store_kind for s in DS.stores_of(db.session.get(Organization, riverview), True)}
        assert kinds == {'School Spirit': 'spirit', 'Football': 'sport', 'Band': 'activity',
                         "Mrs. Johnson's Class": 'teacher', 'Fall Festival': 'event', 'Staff': 'staff'}


def test_the_school_page_branches_into_sections_in_a_fixed_order(app, seed, guest):
    _district(app, seed)
    html = guest.get('/org/desoto-usd-232/riverview-elementary').get_data(as_text=True)
    order = ['School Spirit', 'Sports', 'Activities and clubs', 'Events', 'Teachers and classrooms', 'Staff']
    positions = [html.index(f'>{name}<') if f'>{name}<' in html else html.index(name) for name in order]
    assert positions == sorted(positions)
    assert "Mrs. Johnson&#39;s Class" in html or "Mrs. Johnson's Class" in html
    assert 'Sports and activities' not in html


def test_a_section_with_no_live_stores_is_not_shown(app, seed, guest):
    _district(app, seed, stores=('Football',))
    html = guest.get('/org/desoto-usd-232/riverview-elementary').get_data(as_text=True)
    assert '>Sports<' in html
    for gone in ('Activities and clubs', 'Events', 'Teachers and classrooms', '>Staff<'):
        assert gone not in html, gone


def test_the_owner_can_add_any_kind_of_store_from_the_district_screen(app, seed, client, login):
    did, riverview, _ = _district(app, seed, stores=('Football',))
    login(client, ADMIN_EMAIL)
    for label, kind, expected in (('Mr. Lee', '', 'teacher'), ('Math Night', '', 'event'), ('Chess', 'activity', 'activity'),
                                  ('Pep Rally', 'event', 'event')):
        client.post(f'/admin/districts/{did}', data={'action': 'add_store', 'school_id': riverview, 'label': label, 'kind': kind})
        with app.app_context():
            school = db.session.get(Organization, riverview)
            made = next(s for s in DS.stores_of(school, True) if DS.store_label(s) == label)
            assert made.store_kind == expected, label
    html = client.get(f'/admin/districts/{did}').get_data(as_text=True)
    assert 'Teacher or classroom' in html and 'name="kind"' in html


def test_the_setup_screen_accepts_a_type_before_a_store_name(app, seed, client, login):
    login(client, ADMIN_EMAIL)
    client.post('/admin/districts/new', data={
        'name': 'Olathe Schools', 'schools_elementary': 'Park Elementary | Bears | Soccer, teacher:Mrs. Lee, event:Fall Festival, sport:Chess'})
    with app.app_context():
        school = Organization.query.filter_by(short_slug='park').one()
        kinds = {DS.store_label(s): s.store_kind for s in DS.stores_of(school, True)}
        assert kinds == {'School Spirit': 'spirit', 'Soccer': 'sport', 'Mrs. Lee': 'teacher', 'Fall Festival': 'event', 'Chess': 'sport'}


def test_school_logos_are_shared_by_every_store_of_the_school(app, seed):
    did, riverview, mill = _district(app, seed)
    a, b = _logo(app, seed, 'falcon-head'), _logo(app, seed, 'falcon-wordmark')
    with app.app_context():
        school = db.session.get(Organization, riverview)
        n = DS.set_school_logos(school, [a, b])
        db.session.commit()
        assert n == 6
        for store in DS.stores_of(school, True):
            assert _ids(store)[:2] == [a, b] and _ids(store, 'showcase')[:2] == [a, b]
        other = DS.stores_of(db.session.get(Organization, mill), True)[0]
        assert a not in _ids(other)                          # another school is untouched


def test_a_store_keeps_its_own_extra_logo_next_to_the_school_logos(app, seed):
    did, riverview, _ = _district(app, seed)
    a, own = _logo(app, seed, 'school-mark'), _logo(app, seed, 'football-special')
    band = _store(app, riverview, 'Band')
    with app.app_context():
        school = db.session.get(Organization, riverview)
        store = db.session.get(Collection, _store(app, riverview, 'Football'))
        store.allowed_design_ids = json.dumps([own])
        DS.set_school_logos(school, [a])
        assert _ids(store) == [a, own]                       # the school's logo first, then the store's own
        DS.set_school_logos(school, [])                      # remove the school logo: the store's own stays
        assert _ids(store) == [own] and school.school_logo_ids is None
        assert db.session.get(Collection, band).allowed_design_ids is None


def test_a_new_store_starts_with_the_school_logos(app, seed):
    did, riverview, _ = _district(app, seed, stores=('Football',))
    a = _logo(app, seed, 'school-mark')
    with app.app_context():
        school = db.session.get(Organization, riverview)
        DS.set_school_logos(school, [a])
        for label in ("Mrs. Lee's Class", 'Book Fair'):
            new = DS.add_store(school, label)
            assert _ids(new) == [a] and _ids(new, 'showcase') == [a]


def test_copying_a_store_brings_its_extras_but_uses_the_new_schools_logos(app, seed):
    did, riverview, mill = _district(app, seed)
    r_logo, m_logo, extra = _logo(app, seed, 'riverview'), _logo(app, seed, 'mill'), _logo(app, seed, 'football-art')
    with app.app_context():
        r, m = db.session.get(Organization, riverview), db.session.get(Organization, mill)
        DS.set_school_logos(r, [r_logo])
        DS.set_school_logos(m, [m_logo])
        football = db.session.get(Collection, _store(app, riverview, 'Football'))
        football.allowed_design_ids = json.dumps([r_logo, extra])
        football.showcase_design_ids = json.dumps([r_logo, extra])
        DS.copy_store_to_schools(football, [mill])
        db.session.commit()
        copy = db.session.get(Collection, _store(app, mill, 'Football'))
        assert _ids(copy) == [m_logo, extra]                # Mill Valley's logo, plus the football art; no Riverview logo
        assert _ids(copy, 'showcase') == [m_logo, extra]


def test_an_activity_or_teacher_store_copies_with_its_own_kind(app, seed):
    did, riverview, mill = _district(app, seed)
    with app.app_context():
        band = db.session.get(Collection, _store(app, riverview, 'Band'))
        DS.copy_store_to_schools(band, [mill])
        db.session.commit()
        assert db.session.get(Collection, _store(app, mill, 'Band')).store_kind == 'activity'


def test_the_owner_uploads_main_logos_on_the_school_page(app, seed, client, login, monkeypatch):
    did, riverview, _ = _district(app, seed)
    made = []

    def fake_save(file, user_id):
        d = Design(filename=file.filename, file_path=f'uploads/designs/{file.filename}', title=file.filename, uploaded_by_user_id=None)
        db.session.add(d)
        db.session.flush()
        made.append(d.id)
        return d

    monkeypatch.setattr('routes.admin._save_collection_design', fake_save)
    login(client, ADMIN_EMAIL)
    page = client.get(f'/admin/districts/school/{riverview}').get_data(as_text=True)
    assert 'Main logos' in page and 'name="logos"' in page and 'multiple' in page
    resp = client.post(f'/admin/districts/school/{riverview}', data={
        'action': 'logos', 'logos': [(io.BytesIO(b'x'), 'head.png'), (io.BytesIO(b'y'), 'word.png')]},
        content_type='multipart/form-data')
    assert resp.status_code == 302
    with app.app_context():
        school = db.session.get(Organization, riverview)
        assert DS.school_logo_id_list(school) == made and len(made) == 2
        assert all(_ids(s)[:2] == made for s in DS.stores_of(school, True))
    page = client.get(f'/admin/districts/school/{riverview}').get_data(as_text=True)
    assert page.count('name="keep_logo"') == 2 and 'head.png' in page
    # untick one: it leaves every store
    client.post(f'/admin/districts/school/{riverview}', data={'action': 'logos', 'keep_logo': [str(made[1])]})
    with app.app_context():
        school = db.session.get(Organization, riverview)
        assert DS.school_logo_id_list(school) == [made[1]]
        assert all(made[0] not in _ids(s) for s in DS.stores_of(school, True))


def test_a_main_logo_stands_in_when_the_school_has_no_display_logo(app, seed, guest):
    did, riverview, _ = _district(app, seed)
    a = _logo(app, seed, 'falcon-head')
    with app.app_context():
        DS.set_school_logos(db.session.get(Organization, riverview), [a])
        db.session.commit()
    html = guest.get('/org/desoto-usd-232/riverview-elementary').get_data(as_text=True)
    assert 'class="dist-logo"' in html and 'falcon-head.png' in html


def test_the_crawl_still_finds_every_link_with_the_new_sections(app, seed, guest):
    from tests.test_group_order_crawl import _crawl
    _district(app, seed)
    problems, n = _crawl(guest, app, ['/org/desoto-usd-232', '/org/desoto-usd-232/riverview-elementary'], 'visitor')
    assert n > 5 and not problems, problems


def test_the_district_page_card_uses_a_main_logo_when_there_is_no_display_logo(app, seed, guest):
    did, riverview, _ = _district(app, seed)
    a = _logo(app, seed, 'falcon-head')
    with app.app_context():
        DS.set_school_logos(db.session.get(Organization, riverview), [a])
        db.session.commit()
    html = guest.get('/org/desoto-usd-232').get_data(as_text=True)
    card = html.split('data-school="Riverview Elementary"')[1].split('</a>')[0]
    assert 'falcon-head.png' in card


def test_every_text_style_box_in_the_admin_forms_is_styled_alike():
    css = open('static/css/main.css', encoding='utf-8').read()
    rule = css[css.index('.bk-picker select, .bk-picker input'):].split('{')[0]
    for kind in ('text', 'number', 'date', 'email'):
        assert f'.bk-form input[type="{kind}"]' in rule, kind
