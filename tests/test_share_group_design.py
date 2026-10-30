from utils.shared_designs import clean_line


def test_group_store_design_can_be_shared_without_the_store():
    line = {'product_id': 3, 'color': 'Heather Charity Pink', 'design_url': '/static/uploads/x.png', 'collection_id': 46,
            'placement': 'Center Chest', 'quantity': 4, 'size': 'M'}
    out, reason = clean_line(line)
    assert reason is None
    assert 'collection_id' not in out and 'size' not in out
    assert out['quantity'] == 1 and out['color'] == 'Heather Charity Pink'


def test_uniform_line_can_be_shared_without_the_name_and_number():
    line = {'product_id': 3, 'design_id': 1, 'uniform_kit': 'home', 'catalog_section': 'uniform', 'collection_id': 46,
            'back_design_url': '/static/uploads/jordan26.png', 'back_design_meta': {'name': 'JORDAN', 'number': '26'}}
    out, reason = clean_line(line)
    assert reason is None and 'back_design_url' not in out and 'uniform_kit' not in out and 'collection_id' not in out


def test_an_uploaded_back_image_is_kept_when_shared():
    line = {'product_id': 3, 'design_id': 1, 'back_design_url': '/static/uploads/back.png'}
    assert clean_line(line)[0]['back_design_url'] == '/static/uploads/back.png'
