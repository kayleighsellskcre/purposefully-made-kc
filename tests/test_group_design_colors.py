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
