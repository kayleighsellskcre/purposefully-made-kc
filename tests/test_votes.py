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
