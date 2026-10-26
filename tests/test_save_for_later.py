"""Save for later: a cart item is set aside with everything about it, and comes back with one tap."""
import json
from datetime import datetime, timedelta

from models import Collection, Design, Product, SavedCartItem, User, db
from tests.conftest import CUSTOMER_EMAIL, OTHER_EMAIL, PASSWORD
from utils.cart_store import _read_user_cart, _write_user_cart


def _line(seed, **extra):
    line = {'product_id': seed['tee_id'], 'size': 'M', 'color': 'Black', 'quantity': 2, 'unit_price': 99.0,
            'design_id': seed['free_design_id'], 'design_url': '/static/uploads/designs/gallery-logo.png',
            'placement': 'center_chest', 'is_blank': False, 'proof_front_url': '/static/proof.png',
            'back_design_url': None, 'back_design_kind': 'personalization',
            'back_design_meta': {'name': 'SMITH', 'number': '12'}, 'collection_id': None,
            'catalog_section': None, 'uniform_kit': None}
    line.update(extra)
    return line


def _set_cart(app, email, lines):
    with app.app_context():
        _write_user_cart(User.query.filter_by(email=email).first(), lines)


def _cart(app, email):
    with app.app_context():
        return _read_user_cart(User.query.filter_by(email=email).first())


def _saved(app, email=CUSTOMER_EMAIL):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        return [(r.token, r.line) for r in SavedCartItem.query.filter_by(user_id=user.id).all()]


def _signed_in(app, email=CUSTOMER_EMAIL):
    c = app.test_client()
    c.post('/auth/login', data={'email': email, 'password': PASSWORD})
    return c


def test_saving_takes_the_item_out_of_the_cart_and_keeps_every_detail(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed), _line(seed, size='L', design_id=None, design_url=None)])
    shopper = _signed_in(app)
    resp = shopper.post('/cart/save-for-later/0')
    assert resp.status_code == 200 and resp.get_json()['success'] and resp.get_json()['saved_count'] == 1
    assert [l['size'] for l in _cart(app, CUSTOMER_EMAIL)] == ['L']
    (token, line), = _saved(app)
    assert line['design_id'] == seed['free_design_id'] and line['placement'] == 'center_chest'
    assert line['back_design_meta'] == {'name': 'SMITH', 'number': '12'} and line['quantity'] == 2
    assert line['proof_front_url'] == '/static/proof.png'


def test_the_cart_page_has_the_button_and_the_saved_section(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed), _line(seed, size='XL')])
    shopper = _signed_in(app)
    page = shopper.get('/cart/').get_data(as_text=True)
    assert page.count('data-save-for-later=') == 2 and 'Save for later' in page
    assert 'Saved for later' not in page.split('id="savedForLater"')[0] or 'id="savedForLater"' not in page
    shopper.post('/cart/save-for-later/0')
    page = shopper.get('/cart/').get_data(as_text=True)
    assert 'id="savedForLater"' in page and 'Saved for later <span class="saved-count">(1)</span>' in page
    assert 'Back: SMITH 12' in page and 'With your artwork' in page and 'data-saved-move=' in page
    assert page.count('data-save-for-later=') == 1


def test_an_empty_cart_still_shows_what_was_saved(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    page = shopper.get('/cart/').get_data(as_text=True)
    assert 'Your cart is empty' in page and 'id="savedForLater"' in page


def test_moving_it_back_restores_the_line_at_todays_price(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed, unit_price=1.0)])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    (token, _line_saved), = _saved(app)
    with app.app_context():
        db.session.get(Product, seed['tee_id']).base_price = 41.0
        db.session.commit()
    resp = shopper.post(f'/cart/saved/{token}/move')
    assert resp.status_code == 200 and resp.get_json()['saved_count'] == 0
    (back,) = _cart(app, CUSTOMER_EMAIL)
    assert back['size'] == 'M' and back['quantity'] == 2 and back['back_design_meta']['name'] == 'SMITH'
    assert back['design_id'] == seed['free_design_id'] and back['unit_price'] != 1.0 and back['unit_price'] > 0
    assert _saved(app) == []


def test_moving_back_an_item_already_in_the_cart_adds_to_its_quantity(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])           # the same thing was added again meanwhile
    (token, _l), = _saved(app)
    shopper = _signed_in(app)
    shopper.post(f'/cart/saved/{token}/move')
    (only,) = _cart(app, CUSTOMER_EMAIL)
    assert only['quantity'] == 4


def test_an_item_that_can_no_longer_be_ordered_stays_saved_with_the_reason(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    (token, _l), = _saved(app)
    with app.app_context():
        db.session.get(Product, seed['tee_id']).is_active = False
        db.session.commit()
    resp = shopper.post(f'/cart/saved/{token}/move')
    assert resp.status_code == 400 and 'we no longer carry this style' in resp.get_json()['message']
    assert len(_saved(app)) == 1 and _cart(app, CUSTOMER_EMAIL) == []


def test_an_item_from_a_closed_group_store_cannot_come_back(app, seed):
    with app.app_context():
        store = db.session.get(Collection, seed['collection_id'])
        store.order_deadline = datetime.utcnow() - timedelta(days=2)
        db.session.commit()
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed, collection_id=seed['collection_id'])])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    (token, _l), = _saved(app)
    resp = shopper.post(f'/cart/saved/{token}/move')
    assert resp.status_code == 400 and 'has closed' in resp.get_json()['message']


def test_a_group_item_pushes_out_another_groups_items_with_a_note(app, seed):
    with app.app_context():
        other = Collection(name='Other Group', slug='other-group', is_active=True)
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed, collection_id=seed['collection_id'])])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed, collection_id=other_id, size='S')])
    (token, _l), = _saved(app)
    shopper = _signed_in(app)
    resp = shopper.post(f'/cart/saved/{token}/move')
    assert resp.status_code == 200 and 'one group at a time' in (resp.get_json()['note'] or '')
    assert [l['collection_id'] for l in _cart(app, CUSTOMER_EMAIL)] == [seed['collection_id']]


def test_remove_forgets_a_saved_item(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    (token, _l), = _saved(app)
    assert shopper.post(f'/cart/saved/{token}/remove').get_json()['saved_count'] == 0
    assert _saved(app) == []


def test_nobody_can_move_or_remove_someone_elses_saved_item(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    mine = _signed_in(app)
    mine.post('/cart/save-for-later/0')
    (token, _l), = _saved(app)
    other = _signed_in(app, OTHER_EMAIL)
    assert other.post(f'/cart/saved/{token}/move').status_code == 400
    other.post(f'/cart/saved/{token}/remove')
    assert len(_saved(app)) == 1 and _cart(app, OTHER_EMAIL) == []


def test_a_bad_position_is_refused_politely(app, seed):
    shopper = _signed_in(app)
    resp = shopper.post('/cart/save-for-later/7')
    assert resp.status_code == 400 and 'no longer in your cart' in resp.get_json()['message']


def test_saved_items_follow_the_account_to_another_device(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    _signed_in(app).post('/cart/save-for-later/0')
    phone = _signed_in(app)
    assert 'id="savedForLater"' in phone.get('/cart/').get_data(as_text=True)


def test_a_guest_can_save_and_the_item_moves_to_their_account_at_sign_in(app, seed):
    guest = app.test_client()
    with guest.session_transaction() as sess:
        sess['cart'] = [_line(seed)]
    resp = guest.post('/cart/save-for-later/0')
    assert resp.status_code == 200 and resp.get_json()['saved_count'] == 1
    assert 'id="savedForLater"' in guest.get('/cart/').get_data(as_text=True)
    guest.post('/auth/login', data={'email': CUSTOMER_EMAIL, 'password': PASSWORD})
    (token, line), = _saved(app)
    assert line['size'] == 'M' and line['back_design_meta']['name'] == 'SMITH'
    assert 'id="savedForLater"' in guest.get('/cart/').get_data(as_text=True)


def test_a_guest_can_move_a_saved_item_back_without_an_account(app, seed):
    guest = app.test_client()
    with guest.session_transaction() as sess:
        sess['cart'] = [_line(seed)]
    guest.post('/cart/save-for-later/0')
    with guest.session_transaction() as sess:
        token = sess['saved_for_later'][0]['token']
    resp = guest.post(f'/cart/saved/{token}/move')
    assert resp.status_code == 200
    with guest.session_transaction() as sess:
        assert [l['size'] for l in sess['cart']] == ['M'] and sess['saved_for_later'] == []


def test_favorites_shows_saved_items_too(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    shopper.post('/cart/save-for-later/0')
    page = shopper.get('/favorites').get_data(as_text=True)
    assert 'id="savedForLater"' in page and 'js/saved-for-later.js' in page


def test_no_more_than_fifty_can_be_saved(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    with app.app_context():
        user = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        for n in range(50):
            db.session.add(SavedCartItem(user_id=user.id, token=f't{n}', product_id=seed['tee_id'], line=_line(seed)))
        db.session.commit()
    resp = _signed_in(app).post('/cart/save-for-later/0')
    assert resp.status_code == 400 and '50' in resp.get_json()['message']
    assert len(_cart(app, CUSTOMER_EMAIL)) == 1


def test_the_buttons_have_their_own_labels_for_screen_readers(app, seed):
    _set_cart(app, CUSTOMER_EMAIL, [_line(seed)])
    shopper = _signed_in(app)
    page = shopper.get('/cart/').get_data(as_text=True)
    assert 'aria-label="Save ' in page and ', Black, size M for later"' in page
    shopper.post('/cart/save-for-later/0')
    page = shopper.get('/cart/').get_data(as_text=True)
    assert 'back to your cart"' in page and 'from saved items"' in page
