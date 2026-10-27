"""On the group order edit page, several uploads of one layout can be linked as colors of one main design."""
import json

from models import Collection, Design, db
from utils import group_orders as G


def _uploads(app, seed, count=3):
    """The seeded store allowing several separately uploaded colors of one layout."""
    with app.app_context():
        designs = [Design(filename=f'cheer-{i}.png', file_path=f'uploads/designs/cheer-{i}.png', title=f'Cheer {i}',
                          is_gallery=True, uploaded_by_user_id=seed['admin_id']) for i in range(count)]
        db.session.add_all(designs)
        db.session.flush()
        coll = db.session.get(Collection, seed['collection_id'])
        coll.allowed_design_ids = json.dumps([d.id for d in designs])
        db.session.commit()
        return [d.id for d in designs]


def _link(client, seed, ids):
    return client.post(f"/admin/collections/{seed['collection_id']}/designs/link-colors",
                       data={'design_ids': [str(i) for i in ids]}, follow_redirects=True)


def test_linking_makes_the_first_the_main_design_and_the_rest_its_colors(app, seed, admin_client):
    ids = _uploads(app, seed)
    resp = _link(admin_client, seed, ids)
    assert resp.status_code == 200 and b'Linked 2 colors' in resp.data
    with app.app_context():
        main, a, b = (db.session.get(Design, i) for i in ids)
        assert main.parent_design_id is None and main.variant_label
        assert a.parent_design_id == main.id and b.parent_design_id == main.id
        assert len({main.variant_label, a.variant_label, b.variant_label}) == 3
        cards = G.load_collection_designs(db.session.get(Collection, seed['collection_id']))
        assert len(cards) == 1 and cards[0]['id'] == main.id and cards[0]['color_count'] == 3


def test_the_edit_page_lists_colors_under_their_main_design_and_can_unlink_one(app, seed, admin_client):
    ids = _uploads(app, seed)
    _link(admin_client, seed, ids)
    html = admin_client.get(f"/admin/collections/{seed['collection_id']}/edit").get_data(as_text=True)
    assert html.count('name="allowed_designs"') == 1 and '+ 2 more colors' in html
    assert f'id="unlinkDesign{ids[1]}"' in html
    admin_client.post(f"/admin/collections/{seed['collection_id']}/designs/{ids[1]}/unlink", follow_redirects=True)
    with app.app_context():
        assert db.session.get(Design, ids[1]).parent_design_id is None
        assert ids[1] in G.allowed_design_ids(db.session.get(Collection, seed['collection_id']))
    html = admin_client.get(f"/admin/collections/{seed['collection_id']}/edit").get_data(as_text=True)
    assert html.count('name="allowed_designs"') == 2 and '+ 1 more color' in html


def test_one_ticked_design_or_a_design_outside_the_store_changes_nothing(app, seed, admin_client):
    ids = _uploads(app, seed, 2)
    resp = _link(admin_client, seed, ids[:1])
    assert b'Tick two or more' in resp.data
    resp = _link(admin_client, seed, [ids[0], seed['fee_4_design_id']])
    assert b'Tick two or more' in resp.data
    with app.app_context():
        assert all(db.session.get(Design, i).parent_design_id is None for i in ids)


def test_only_an_admin_can_link(app, seed, customer_client):
    ids = _uploads(app, seed)
    resp = customer_client.post(f"/admin/collections/{seed['collection_id']}/designs/link-colors",
                                data={'design_ids': [str(i) for i in ids]})
    assert resp.status_code in (302, 401, 403)
    with app.app_context():
        assert all(db.session.get(Design, i).parent_design_id is None for i in ids)
