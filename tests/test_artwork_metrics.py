"""Visible-width ratios for gallery logos, used to size the first mockup paint."""
import io

from PIL import Image

from services.artwork_metrics import clear_cache, measure_design, peek_cached, visible_width_ratio


def _png_with_ink_width(canvas_w, ink_w, ink_left):
    img = Image.new('RGBA', (canvas_w, 80), (0, 0, 0, 0))
    for x in range(ink_left, ink_left + ink_w):
        for y in range(10, 70):
            img.putpixel((x, y), (20, 20, 20, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def test_visible_width_ratio_ignores_transparent_padding():
    data = _png_with_ink_width(200, 100, 50)
    ratio = visible_width_ratio(data)
    assert 0.45 <= ratio <= 0.55


def test_visible_width_ratio_full_bleed_is_one():
    data = _png_with_ink_width(80, 80, 0)
    assert visible_width_ratio(data) == 1.0


def test_artwork_fits_api_returns_gallery_ratio(client, seed):
    resp = client.get(f"/api/artwork-fits?ids={seed['free_design_id']}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['ok'] is True
    assert str(seed['free_design_id']) in payload['fits']
    ratio = payload['fits'][str(seed['free_design_id'])]
    assert 0.2 <= ratio <= 1.0


def test_artwork_fits_api_hides_someone_elses_design(client, seed):
    resp = client.get(f"/api/artwork-fits?ids={seed['fee_4_design_id']}")
    assert resp.status_code == 200
    assert resp.get_json()['fits'] == {}


def test_measure_artwork_fits_stamps_a_preset_card(app, seed):
    from routes.shop import _measure_artwork_fits
    with app.app_context():
        cards = [{'id': seed['free_design_id'], 'url': '/x', 'title': 'Logo'}]
        _measure_artwork_fits(cards, app)
        assert 0.2 <= cards[0]['artwork_fit'] <= 1.0


def test_measure_designs_accepts_the_current_app_proxy(app, seed):
    """Passing Flask's current_app into a threaded batch used to 500 the
    customizer with 'Working outside of application context'."""
    from flask import current_app
    from models import Design
    from services.artwork_metrics import clear_cache, measure_designs

    with app.app_context():
        designs = [
            Design.query.get(seed['free_design_id']),
            Design.query.get(seed['fee_4_design_id']),
        ]
        clear_cache()
        fits = measure_designs(designs, current_app)
        assert str(seed['free_design_id']) in fits
        assert str(seed['fee_4_design_id']) in fits


def test_artwork_fits_api_measures_a_batch(client, seed):
    ids = f"{seed['free_design_id']},{seed['fee_4_design_id']}"
    resp = client.get(f'/api/artwork-fits?ids={ids}')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['ok'] is True
    assert str(seed['free_design_id']) in payload['fits']
    assert str(seed['fee_4_design_id']) not in payload['fits']


def test_measure_design_is_cached(app, seed):
    from models import Design
    with app.app_context():
        design = Design.query.get(seed['free_design_id'])
        clear_cache()
        assert peek_cached(design) is None
        first = measure_design(design, app)
        second = measure_design(design, app)
        assert first == second
        assert 0.2 <= first <= 1.0
        assert peek_cached(design) == first
