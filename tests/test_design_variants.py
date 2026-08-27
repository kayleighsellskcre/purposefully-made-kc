"""Gallery color variants: one main card, multiple colors."""
from models import db, Design
from utils.design_variants import (
    gallery_cards_for_public,
    gallery_mains_query,
    color_options_for,
    ensure_not_nested_parent,
    unpublish_color_variants,
)


def _gallery_design(**kwargs):
    d = Design(
        filename=kwargs.get('filename', 'logo.png'),
        original_filename=kwargs.get('original_filename', 'logo.png'),
        file_path=kwargs.get('file_path', 'uploads/logo.png'),
        title=kwargs.get('title', 'Team Logo'),
        is_gallery=True,
        design_fee=0,
    )
    for key, val in kwargs.items():
        if hasattr(d, key):
            setattr(d, key, val)
    db.session.add(d)
    db.session.flush()
    return d


def test_public_gallery_shows_one_card_for_color_family(app, seed):
    with app.app_context():
        main = _gallery_design(title='Falcons', filename='falcons-navy.png', variant_label='Navy')
        child = _gallery_design(
            title='Falcons',
            filename='falcons-white.png',
            file_path='uploads/falcons-white.png',
            parent_design_id=main.id,
            variant_label='White',
        )
        db.session.commit()

        mains = gallery_mains_query(Design).all()
        assert main in mains
        assert child not in mains

        cards = gallery_cards_for_public(Design)
        falcons = [c for c in cards if c['id'] == main.id]
        assert len(falcons) == 1
        card = falcons[0]
        assert card['has_colors'] is True
        assert card['color_count'] == 2
        labels = [v['label'] for v in card['variants']]
        assert 'Navy' in labels
        assert 'White' in labels
        ids = {v['id'] for v in card['variants']}
        assert main.id in ids
        assert child.id in ids


def test_ensure_not_nested_parent_walks_to_root(app, seed):
    with app.app_context():
        root = _gallery_design(title='Root', filename='root.png')
        mid = _gallery_design(
            title='Root', filename='mid.png', file_path='uploads/mid.png',
            parent_design_id=root.id, variant_label='Mid',
        )
        db.session.commit()
        assert ensure_not_nested_parent(mid).id == root.id
        assert ensure_not_nested_parent(root).id == root.id


def test_unpublish_color_variants_with_main(app, seed):
    with app.app_context():
        main = _gallery_design(title='Crest', filename='crest.png')
        child = _gallery_design(
            title='Crest', filename='crest2.png', file_path='uploads/crest2.png',
            parent_design_id=main.id, variant_label='Gold',
        )
        db.session.commit()
        main.is_gallery = False
        unpublish_color_variants(main)
        db.session.commit()
        child = Design.query.get(child.id)
        assert child.is_gallery is False


def test_color_options_for_orders_main_then_children(app, seed):
    with app.app_context():
        main = _gallery_design(title='Mark', filename='mark.png', variant_label='Black')
        b = _gallery_design(
            title='Mark', filename='mark-b.png', file_path='uploads/mark-b.png',
            parent_design_id=main.id, variant_label='Blue',
        )
        a = _gallery_design(
            title='Mark', filename='mark-a.png', file_path='uploads/mark-a.png',
            parent_design_id=main.id, variant_label='Amber',
        )
        db.session.commit()
        opts = color_options_for(main)
        assert [o.id for o in opts] == [main.id, a.id, b.id]


def test_public_design_gallery_page_groups_variants(client, app, seed):
    with app.app_context():
        main = _gallery_design(title='Grouped Logo', filename='g1.png', variant_label='Red')
        _gallery_design(
            title='Grouped Logo', filename='g2.png', file_path='uploads/g2.png',
            parent_design_id=main.id, variant_label='Blue',
        )
        db.session.commit()
        main_id = main.id

    html = client.get('/shop/designs').get_data(as_text=True)
    assert 'Grouped Logo' in html
    assert '2 colors' in html
    assert 'Choose Color' in html
    assert html.count('data-design-id="%s"' % main_id) >= 1
