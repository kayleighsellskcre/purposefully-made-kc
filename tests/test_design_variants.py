"""Gallery color variants: one main card, multiple colors."""
from models import db, Design
from utils.design_variants import (
    gallery_cards_for_public,
    gallery_mains_query,
    color_options_for,
    ensure_not_nested_parent,
    unpublish_color_variants,
)
from utils.design_categories import (
    design_category_keys,
    gallery_group_for_title,
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


def test_promote_gallery_main_makes_the_chosen_color_the_cover(app, seed):
    from utils.design_variants import promote_gallery_main

    with app.app_context():
        main = _gallery_design(
            title='Falcons', filename='falcons-navy.png',
            variant_label='Navy', folder='sports', sku='SPT-009',
        )
        white = _gallery_design(
            title='Falcons', filename='falcons-white.png',
            file_path='uploads/falcons-white.png',
            parent_design_id=main.id, variant_label='White',
        )
        gold = _gallery_design(
            title='Falcons', filename='falcons-gold.png',
            file_path='uploads/falcons-gold.png',
            parent_design_id=main.id, variant_label='Gold',
        )
        db.session.commit()

        promote_gallery_main(white)
        db.session.commit()

        white = Design.query.get(white.id)
        main = Design.query.get(main.id)
        gold = Design.query.get(gold.id)
        assert white.parent_design_id is None
        assert main.parent_design_id == white.id
        assert gold.parent_design_id == white.id
        assert white.title == 'Falcons'
        assert white.folder == 'sports'
        assert white.sku == 'SPT-009'
        mains = gallery_mains_query(Design).all()
        assert white in mains
        assert main not in mains
        assert gold not in mains


def test_public_design_gallery_page_groups_variants(client, app, seed):
    with app.app_context():
        main = _gallery_design(title='Grouped Logo', filename='g1.png', variant_label='Red')
        _gallery_design(
            title='Grouped Logo', filename='g2.png', file_path='uploads/g2.png',
            parent_design_id=main.id, variant_label='Blue',
        )
        db.session.commit()
        main_id = main.id

    landing = client.get('/shop/designs').get_data(as_text=True)
    assert 'This platform is for custom apparel' in landing
    assert 'legal to print' in landing
    assert 'changed a little' in landing
    assert 'Open a folder to browse' not in landing
    assert 'Curated Collection' not in landing
    assert '\u2014' not in landing
    assert 'Fan Favorites' in landing
    assert 'dg-folder' in landing
    assert 'Grouped Logo' in landing
    assert 'id="dgSearch"' in landing
    assert 'View colors &amp; continue' not in landing
    assert 'gallery-card-overlay' not in landing

    html = client.get('/shop/designs?category=favorites').get_data(as_text=True)
    assert 'Grouped Logo' in html
    assert '2 colors' in html
    assert 'View colors &amp; continue' in html
    assert 'gallery-carousel-prev' in html
    assert 'gallery-carousel-next' in html
    assert 'gallery-carousel-color' in html
    assert 'id="dgSearch"' in html
    assert 'id="dgSort"' in html
    assert 'id="dgLoadMore"' in html
    assert html.count('data-design-id="%s"' % main_id) >= 1


def test_gallery_folder_interior_only_shows_that_folder(client, app, seed):
    with app.app_context():
        _gallery_design(title='School Crest', folder='school')
        _gallery_design(title='Chiefs Helmet', folder='sports')
        db.session.commit()

    sports = client.get('/shop/designs?category=sports').get_data(as_text=True)
    assert 'Chiefs Helmet' in sports
    assert 'School Crest' not in sports
    assert 'All folders' in sports

    landing = client.get('/shop/designs').get_data(as_text=True)
    assert 'Sports' in landing
    assert 'School' in landing
    assert 'View colors &amp; continue' not in landing

    results = client.get('/shop/designs?q=chiefs').get_data(as_text=True)
    assert 'Search results' in results
    assert 'Chiefs Helmet' in results
    assert 'School Crest' not in results


def test_gallery_folder_cards_use_mains_as_covers():
    from utils.design_variants import filter_gallery_cards, gallery_folder_cards

    cards = [
        {
            'id': 1, 'url': '/a.png', 'title': 'Prayer',
            'category_keys': ['faith'], 'category_labels': ['Faith & Inspiration'],
            'group': '', 'variants': [{'label': 'Navy'}],
        },
        {
            'id': 2, 'url': '/b.png', 'title': 'Chiefs Helmet',
            'category_keys': ['sports', 'kc'], 'category_labels': ['Sports', 'Kansas City'],
            'group': 'Kansas City Chiefs', 'variants': [{'label': 'Red'}],
        },
    ]
    folders = gallery_folder_cards(cards)
    assert [folder['key'] for folder in folders] == ['faith', 'sports', 'kc']
    assert folders[0]['covers'][0]['title'] == 'Prayer'
    chiefs = filter_gallery_cards(cards, query='chiefs')
    assert [card['id'] for card in chiefs] == [2]


def test_gallery_category_taxonomy_handles_existing_aliases():
    from utils.design_categories import assigned_gallery_folders, storage_key_for
    from werkzeug.datastructures import MultiDict

    assert design_category_keys('custom_orders') == ['favorites']
    assert design_category_keys('sports', 'kc,school,sports') == [
        'sports', 'kc', 'school',
    ]
    assert gallery_group_for_title('Best Dad — Kansas City Chiefs') == (
        'Kansas City Chiefs'
    )
    assert storage_key_for('favorites') == 'evergreen'
    assert storage_key_for('custom_orders') == 'evergreen'
    assert assigned_gallery_folders(MultiDict([
        ('upload_cats', 'sports'),
        ('upload_cats', 'kc'),
        ('folder', 'custom_orders'),
    ])) == ['sports', 'kc', 'evergreen']


def test_variant_labels_are_unique_within_family(app, seed):
    from utils.design_metadata import unique_variant_label

    with app.app_context():
        main = _gallery_design(title='Crest', variant_label='Forest Green')
        _gallery_design(
            title='Crest',
            filename='crest-green-2.png',
            file_path='uploads/crest-green-2.png',
            parent_design_id=main.id,
            variant_label='Forest Green 2',
        )
        db.session.commit()

        assert unique_variant_label(main, 'Forest Green') == 'Forest Green 3'
        assert unique_variant_label(main, 'Gold') == 'Gold'


def test_generic_camera_filename_is_not_used_as_customer_title():
    from utils.design_metadata import clean_filename_title, is_generic_title

    assert clean_filename_title('IMG_5902.png') == ''
    assert clean_filename_title('best-dad-by-par-green.png') == 'Best Dad By Par Green'
    assert is_generic_title('IMG 5902') is True
    assert is_generic_title('Best Dad by Par') is False

