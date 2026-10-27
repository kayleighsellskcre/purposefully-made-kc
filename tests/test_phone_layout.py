"""Phone fixes: the shirt preview keeps its size while a phone's address bar slides away, an empty group says so,
and the group and district tiles stay even."""
from pathlib import Path

from models import Collection, db


def _customize(app, seed):
    shopper = app.test_client()
    return shopper.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)


def test_the_preview_height_does_not_follow_a_phones_address_bar(app, seed):
    html = _customize(app, seed)
    assert 'dvh' not in html                      # dvh grows and shrinks as the address bar slides away; svh holds still
    assert 'min(56svh, 560px)' in html and 'min(48svh, 420px)' in html
    assert 'if (w === lastCanvasW && h === lastCanvasH) return;' in html


def test_a_group_with_no_logos_says_so_instead_of_showing_nothing(app, seed):
    with app.app_context():
        coll = db.session.get(Collection, seed['collection_id'])
        coll.restrict_options = True
        coll.allowed_design_ids = None
        db.session.commit()
        slug = coll.slug
    shopper = app.test_client()
    shopper.get(f'/c/{slug}')
    html = shopper.get(f"/shop/customize/{seed['tee_slug']}").get_data(as_text=True)
    assert 'No logos have been added to this group yet' in html


def test_phone_rules_keep_group_and_district_tiles_even():
    css = Path('static/css/main.css').read_text(encoding='utf-8')
    for rule in ('.dist-card-art { position: relative; }', '.dist-grid > .dist-card { flex: 0 1 calc(50% - 0.4rem)',
                 '.design-board .design-card-content .price-row { flex-direction: column'):
        assert rule in css
