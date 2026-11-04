"""Take a vote: each vote is its own, names and Submit are required, only the maker sees results."""
import io
import re

import pytest
from PIL import Image

from models import User, VotePoll, VoteResponse, db
from tests.conftest import CUSTOMER_EMAIL, _login
from utils import votes as V


def _png(color):
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), color).save(buf, 'PNG')
    buf.seek(0)
    return buf


def _make(client, title='Falcons shirt', n=3):
    data = {'title': title, 'note': 'pick', 'pictures': [(_png((i * 40, 10, 10)), f'd{i}.png') for i in range(n)]}
    resp = client.post('/vote/new', data=data, content_type='multipart/form-data')
    assert resp.status_code == 302, resp.data[:300]
    return resp.headers['Location'].split('/vote/')[1].split('/')[0]


@pytest.fixture()
def maker(app, seed):
    """A signed-in customer on a plain client, so voters on other clients never share its request context."""
    c = app.test_client()
    assert _login(c, CUSTOMER_EMAIL).status_code == 200
    return c


def _poll(app, token):
    """The option ids, read from the page voters see."""
    c = app.test_client()
    if True:
        html = c.get(f'/vote/{token}').get_data(as_text=True)
    return [int(x) for x in re.findall(r'name="pick" value="(\d+)"', html)]


def test_signed_out_cannot_make(app, seed):
    assert app.test_client().get('/vote/new').status_code in (302, 401)


def test_make_needs_name_and_two_pictures(app, maker):
    assert maker.post('/vote/new', data={'title': '', 'pictures': [(_png('red'), 'a.png'), (_png('blue'), 'b.png')]},
                                content_type='multipart/form-data').status_code == 400
    assert maker.post('/vote/new', data={'title': 'x', 'pictures': [(_png('red'), 'a.png')]},
                                content_type='multipart/form-data').status_code == 400
    assert maker.post('/vote/new', data={'title': 'x', 'pictures': [(_png('red'), 'a.txt'), (_png('blue'), 'b.png')]},
                                content_type='multipart/form-data').status_code == 400


def test_vote_needs_name_and_a_pick(app, maker):
    token = _make(maker)
    ids = _poll(app, token)
    voter = app.test_client()
    assert voter.get(f'/vote/{token}').status_code == 200
    assert voter.post(f'/vote/{token}', data={'voter_name': '', 'pick': ids[0]}).status_code == 400
    assert voter.post(f'/vote/{token}', data={'voter_name': 'Sam'}).status_code == 400
    with app.app_context():
        assert VoteResponse.query.count() == 0
    assert voter.post(f'/vote/{token}', data={'voter_name': 'Sam', 'pick': [ids[0], ids[1]]}).status_code == 302
    with app.app_context():
        assert VoteResponse.query.count() == 1


def test_same_name_replaces_and_other_votes_stay_apart(app, maker):
    a, b = _make(maker, 'First'), _make(maker, 'Second')
    ids_a, ids_b = _poll(app, a), _poll(app, b)
    voter = app.test_client()
    voter.post(f'/vote/{a}', data={'voter_name': 'Sam', 'pick': ids_a[0]})
    voter.post(f'/vote/{a}', data={'voter_name': 'sam', 'pick': ids_a[1]})
    # a pick from the other vote is ignored, so it can never cross over
    assert voter.post(f'/vote/{a}', data={'voter_name': 'Pat', 'pick': ids_b[0]}).status_code == 400
    voter.post(f'/vote/{b}', data={'voter_name': 'Sam', 'pick': ids_b[2]})
    with app.app_context():
        pa, pb = V.get_poll(a), V.get_poll(b)
        assert len(pa.responses) == 1 and len(pb.responses) == 1
        assert [r['count'] for r in V.tally(pa)].count(1) == 1
        assert sum(r['count'] for r in V.tally(pb)) == 1


def test_only_the_maker_sees_results(app, maker):
    token = _make(maker)
    assert maker.get(f'/vote/{token}/results').status_code == 200
    assert maker.get(f'/vote/{token}/results.csv').status_code == 200
    assert app.test_client().get(f'/vote/{token}/results').status_code in (302, 401)
    with app.app_context():
        other = User(email='other@test.example', first_name='O', last_name='P')
        other.set_password('Demo-Only-Pass-4471!')
        db.session.add(other)
        db.session.commit()
    c = app.test_client()
    c.post('/auth/login', data={'email': 'other@test.example', 'password': 'Demo-Only-Pass-4471!'})
    assert c.get(f'/vote/{token}/results').status_code == 404


def test_closed_vote_takes_no_more_votes(app, maker):
    token = _make(maker)
    ids = _poll(app, token)
    maker.post(f'/vote/{token}/toggle')
    assert app.test_client().post(f'/vote/{token}', data={'voter_name': 'Sam', 'pick': ids[0]}).status_code == 400


# ── group votes: voters type a name, the owner picks winners, winners appear on the group page ──
def _admin(app):
    from tests.conftest import ADMIN_EMAIL
    c = app.test_client()
    assert _login(c, ADMIN_EMAIL).status_code == 200
    return c


def _group(app):
    from models import Organization
    with app.app_context():
        db.session.add(Organization(name='Mill Valley Cheer', slug='mill-valley-cheer', is_active=True))
        db.session.commit()


def test_group_vote_winners_show_on_the_group_page(app, seed):
    _group(app)
    admin = _admin(app)
    data = {'title': 'Cheer designs', 'org': 'mill-valley-cheer', 'pictures': [(_png((i * 40, 10, 10)), f'd{i}.png') for i in range(4)]}
    resp = admin.post('/vote/new?org=mill-valley-cheer', data=data, content_type='multipart/form-data')
    assert resp.status_code == 302
    token = resp.headers['Location'].split('/vote/')[1].split('/')[0]
    with app.app_context():
        assert VotePoll.query.filter_by(token=token).one().org_id is not None
    ids = _poll(app, token)
    assert len(ids) == 4
    assert 'Mill Valley Cheer' in app.test_client().get(f'/vote/{token}').get_data(as_text=True)
    for name, picks in (('Ann', ids[2:3]), ('Bo', ids[2:4]), ('Cy', ids[3:4])):          # no account, just a name
        c = app.test_client()
        r = c.post(f'/vote/{token}', data={'voter_name': name, 'pick': [str(i) for i in picks]})
        assert r.status_code == 302
    public = app.test_client()
    assert 'Our Favorite Designs' not in public.get('/org/mill-valley-cheer').get_data(as_text=True)
    admin.post(f'/vote/{token}/winners', data={'top': '1'})
    with app.app_context():
        from models import VoteOption
        on = [o.id for o in VoteOption.query.filter_by(on_page=True).all()]
        assert len(on) == 1
    page = public.get('/org/mill-valley-cheer').get_data(as_text=True)
    assert 'Our Favorite Designs' in page and page.count('class="org-fav"') == 1
    admin.post(f'/vote/{token}/winners', data={'on_page': [str(ids[0]), str(ids[1])]})
    assert public.get('/org/mill-valley-cheer').get_data(as_text=True).count('class="org-fav"') == 2


def test_only_the_owner_can_tie_a_vote_to_a_group(app, seed, maker):
    _group(app)
    data = {'title': 'x', 'pictures': [(_png((i * 40, 10, 10)), f'd{i}.png') for i in range(2)]}
    resp = maker.post('/vote/new?org=mill-valley-cheer', data=data, content_type='multipart/form-data')
    token = resp.headers['Location'].split('/vote/')[1].split('/')[0]
    with app.app_context():
        assert VotePoll.query.filter_by(token=token).one().org_id is None
    assert maker.post(f'/vote/{token}/winners', data={'top': '1'}).status_code == 404


def test_a_team_store_vote_shows_winners_on_that_team_page_and_the_edit_page_has_the_button(app, seed):
    from models import Collection
    admin = _admin(app)
    with app.app_context():
        cid = Collection.query.first().id
        slug = Collection.query.first().slug
    edit = admin.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert f'/vote/new?collection={cid}' in edit and 'Start a design vote' in edit
    data = {'title': 'Team designs', 'collection': str(cid), 'pictures': [(_png((i * 40, 10, 10)), f'd{i}.png') for i in range(3)]}
    resp = admin.post(f'/vote/new?collection={cid}', data=data, content_type='multipart/form-data')
    token = resp.headers['Location'].split('/vote/')[1].split('/')[0]
    ids = _poll(app, token)
    app.test_client().post(f'/vote/{token}', data={'voter_name': 'Ann', 'pick': [str(ids[1])]})
    admin.post(f'/vote/{token}/winners', data={'top': '1'})
    r = app.test_client().get(f'/c/{slug}'); page = r.get_data(as_text=True)
    assert 'Our Favorite Designs' in page and page.count('class="org-fav"') == 1
