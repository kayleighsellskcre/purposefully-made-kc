"""Group stores offer linked art colors the way the design gallery does."""
import json

from models import Collection, Design, db
from utils import group_orders as G


def _family(app, seed):
    """A main design with two linked colors, and the seeded store allowing only the main one."""
    with app.app_context():
        main = Design(filename='cheer-pink.png', file_path='uploads/designs/cheer-pink.png', title='Cheer',
                      variant_label='Pink', is_gallery=True, uploaded_by_user_id=seed['admin_id'])
        db.session.add(main)
        db.session.flush()
        kids = [Design(filename=f'cheer-{c}.png', file_path=f'uploads/designs/cheer-{c}.png', title='Cheer',
                       variant_label=c, is_gallery=True, parent_design_id=main.id, uploaded_by_user_id=seed['admin_id'])
                for c in ('Black', 'White')]
        db.session.add_all(kids)
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allowed_design_ids = json.dumps([main.id, seed['free_design_id']])
        db.session.commit()
        return main.id, [k.id for k in kids]


def test_linked_colors_are_one_card_with_a_color_list(app, seed):
    main_id, kid_ids = _family(app, seed)
    with app.app_context():
        cards = G.load_collection_designs(db.session.get(Collection, seed['collection_id']))
        assert [c['id'] for c in cards] == [main_id, seed['free_design_id']]
        family = cards[0]
        assert family['has_colors'] and family['color_count'] == 3
        assert [v['label'] for v in family['variants']] == ['Pink', 'Black', 'White']
        assert [v['id'] for v in family['variants']] == [main_id] + kid_ids
        assert 'variants' not in cards[1]            # a design with no linked colors is unchanged


def test_picking_a_child_alone_shows_the_whole_family_once(app, seed):
    main_id, kid_ids = _family(app, seed)
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allowed_design_ids = json.dumps([kid_ids[0], main_id])
        db.session.commit()
        cards = G.load_collection_designs(coll)
        assert len(cards) == 1 and cards[0]['id'] == main_id and cards[0]['color_count'] == 3


def test_every_linked_color_can_be_ordered_but_unrelated_art_cannot(app, seed):
    main_id, kid_ids = _family(app, seed)
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        for design_id in [main_id] + kid_ids:
            assert G.design_allowed_for_collection(db.session.get(Design, design_id), coll)
        assert not G.design_allowed_for_collection(db.session.get(Design, seed['fee_4_design_id']), coll)


def test_the_customizer_offers_the_color_choice_in_a_group_store(app, seed, client):
    _family(app, seed)
    client.get(f'/c/{seed["collection_slug"]}')
    html = client.get(f'/shop/customize/{seed["tee_slug"]}?catalog_section=fan').get_data(as_text=True)
    assert 'data-has-colors="1"' in html
    assert 'Black' in html and 'White' in html and 'cheer-Black.png' in html


def _all_ids(app, seed, ids):
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allowed_design_ids = json.dumps(ids)
        db.session.commit()


def test_owner_can_choose_which_color_is_the_main_picture(app, seed, admin_client):
    main_id, kid_ids = _family(app, seed)
    _all_ids(app, seed, [main_id] + kid_ids)
    resp = admin_client.post(f'/admin/collections/{seed["collection_id"]}/designs/{kid_ids[0]}/make-main')
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Design, kid_ids[0]).parent_design_id is None
        assert db.session.get(Design, main_id).parent_design_id == kid_ids[0]
        assert db.session.get(Design, kid_ids[1]).parent_design_id == kid_ids[0]
        cards = G.load_collection_designs(db.session.get(Collection, seed['collection_id']))
        assert cards[0]['id'] == kid_ids[0] and cards[0]['color_count'] == 3


def test_owner_can_delete_one_color_and_the_rest_stay(app, seed, admin_client):
    main_id, kid_ids = _family(app, seed)
    _all_ids(app, seed, [main_id] + kid_ids)
    resp = admin_client.post(f'/admin/collections/{seed["collection_id"]}/designs/{kid_ids[1]}/remove-color')
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Design, kid_ids[1]) is None
        assert db.session.get(Design, kid_ids[0]).parent_design_id == main_id
        assert db.session.get(Design, main_id) is not None
        assert kid_ids[1] not in json.loads(db.session.get(Collection, seed['collection_id']).allowed_design_ids)
    # the main design itself is not deleted through this button
    admin_client.post(f'/admin/collections/{seed["collection_id"]}/designs/{main_id}/remove-color')
    with app.app_context():
        assert db.session.get(Design, main_id) is not None


def test_edit_page_shows_make_main_and_delete_on_colors(app, seed, admin_client):
    main_id, kid_ids = _family(app, seed)
    _all_ids(app, seed, [main_id] + kid_ids)
    html = admin_client.get(f'/admin/collections/{seed["collection_id"]}/edit').get_data(as_text=True)
    assert 'Make main' in html and f'removeColor{kid_ids[0]}' in html


def test_edit_page_lists_colors_even_when_only_the_main_is_on_the_group_list(app, seed, admin_client):
    main_id, kid_ids = _family(app, seed)          # the group's own list holds only the main design
    html = admin_client.get(f'/admin/collections/{seed["collection_id"]}/edit').get_data(as_text=True)
    assert 'Make main' in html and f'removeColor{kid_ids[1]}' in html


def test_organizer_route_picks_the_main_color_and_a_stranger_is_refused(app, seed, client, customer_client):
    main_id, kid_ids = _family(app, seed)
    _all_ids(app, seed, [main_id] + kid_ids)
    url = f'/shop/group-orders/{seed["collection_slug"]}/designs/{kid_ids[0]}/make-main'
    assert customer_client.post(url).status_code == 403
    with app.app_context():
        assert db.session.get(Design, kid_ids[0]).parent_design_id == main_id


def test_organizer_route_works_for_the_owner(app, seed, admin_client):
    main_id, kid_ids = _family(app, seed)
    _all_ids(app, seed, [main_id] + kid_ids)
    resp = admin_client.post(f'/shop/group-orders/{seed["collection_slug"]}/designs/{kid_ids[1]}/make-main')
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Design, kid_ids[1]).parent_design_id is None
        assert db.session.get(Design, main_id).parent_design_id == kid_ids[1]
