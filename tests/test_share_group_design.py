from utils.shared_designs import clean_line


def test_group_store_design_can_be_shared_without_the_store():
    line = {'product_id': 3, 'color': 'Heather Charity Pink', 'design_url': '/static/uploads/x.png', 'collection_id': 46,
            'placement': 'Center Chest', 'quantity': 4, 'size': 'M'}
    out, reason = clean_line(line)
    assert reason is None
    assert 'collection_id' not in out and 'size' not in out
    assert out['quantity'] == 1 and out['color'] == 'Heather Charity Pink'


def test_catalog_and_kit_lines_still_not_shared():
    assert clean_line({'product_id': 3, 'design_id': 1, 'uniform_kit': True})[0] is None
