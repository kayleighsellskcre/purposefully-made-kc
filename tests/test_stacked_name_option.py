"""The organizer can allow or turn off stacked names (one letter per row) for a group order."""
from models import Collection, db


def _setup(app, seed, allow):
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.allow_back_design = True
        c.back_design_type = 'both'
        c.allow_stacked_name = allow
        db.session.commit()


def _customizer(client, seed):
    client.get(f"/c/{seed['collection_slug']}")
    return client.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)


def test_stack_controls_show_when_allowed_and_default_on(app, seed, guest):
    _setup(app, seed, None)                                     # older groups have no value: allowed
    html = _customizer(guest, seed)
    assert 'id="backDesignVerticalToggle"' in html and 'id="backStackToggle"' in html


def test_stack_controls_are_gone_when_the_organizer_turns_them_off(app, seed, guest):
    _setup(app, seed, False)
    html = _customizer(guest, seed)
    assert 'id="backDesignVerticalToggle"' not in html and 'id="backStackToggle"' not in html


def test_edit_page_has_the_switch_and_it_saves(app, seed, admin_client):
    cid = seed['collection_id']
    _setup(app, seed, True)
    page = admin_client.get(f'/admin/collections/{cid}/edit').get_data(as_text=True)
    assert 'name="allow_stacked_name"' in page and 'name="stacked_name_present"' in page
