"""Shop colors follow the supplier and the admin Available colors list."""
import json
from types import SimpleNamespace

from models import db, Product, ProductColorVariant
from services import color_availability as CA
from utils.mockups import get_carousel_colors_for_product, get_color_variants_data_for_product


def _names(app, product):
    return {c['color_name'] for c in get_carousel_colors_for_product(product, app)}


def _tee(seed):
    return Product.query.filter_by(style_number='3001').first()


def test_supplier_hidden_color_is_not_shown(app, seed):
    with app.app_context():
        tee = _tee(seed)
        assert {'Black', 'White'} <= _names(app, tee)
        tee.supplier_hidden_colors = json.dumps(['white'])  # matching ignores case and spacing
        db.session.commit()
        assert 'White' not in _names(app, tee)
        assert 'Black' in _names(app, tee)
        assert 'White' not in {c['color_name'] for c in get_color_variants_data_for_product(tee, app)}




def test_customizer_page_drops_hidden_colors(client, app, seed):
    with app.app_context():
        tee = _tee(seed)
        slug = tee.slug
        tee.supplier_hidden_colors = json.dumps(['White'])
        db.session.commit()
    page = client.get(f'/shop/customize/{slug}')
    assert page.status_code == 200
    with app.app_context():
        shown = {c['color_name'] for c in get_color_variants_data_for_product(_tee(seed), app)}
        assert 'White' not in shown and 'Black' in shown


def _fake_supplier(monkeypatch, per_style):
    sent = []
    monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda product, ss_client=None, timeout=30: per_style.get(product.style_number, (None, {})))
    monkeypatch.setattr(CA, 'send_color_summary', lambda summary: sent.append(summary) or True)
    return sent


def test_nightly_check_hides_missing_and_zero_stock_colors(app, seed, monkeypatch):
    with app.app_context():
        sent = _fake_supplier(monkeypatch, {'3001': ('SanMar', {'Black': {'M': 40}, 'White': {'M': 0}, 'Navy': {'M': 9}})})
        result = CA.run_color_check()
        assert json.loads(_tee(seed).supplier_hidden_colors) == ['White']
        assert result['newly_hidden'] == {'3001': ['White']}
        assert len(sent) == 1
        again = CA.run_color_check()
        assert again['newly_hidden'] == {} and len(sent) == 1
        monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda p, ss_client=None, timeout=30: ('SanMar', {'Black': {'M': 4}, 'White': {'M': 5}, 'Navy': {'M': 1}}))
        back = CA.run_color_check()
        assert back['restored'].get('3001') == ['White']
        assert json.loads(_tee(seed).supplier_hidden_colors) == []


def test_nightly_check_keeps_everything_when_supplier_gives_no_answer(app, seed, monkeypatch):
    with app.app_context():
        _fake_supplier(monkeypatch, {})
        result = CA.run_color_check()
        assert result['checked'] == 0 and '3001' in result['unchecked']
        assert not _tee(seed).supplier_hidden_colors


def test_nightly_check_ignores_a_lookup_that_would_empty_the_style(app, seed, monkeypatch):
    with app.app_context():
        _fake_supplier(monkeypatch, {'3001': ('SanMar', {'Pink': {'M': 10}})})
        result = CA.run_color_check()
        assert '3001' in result['unchecked']
        assert not _tee(seed).supplier_hidden_colors


def test_check_never_touches_variants(app, seed, monkeypatch):
    with app.app_context():
        before = ProductColorVariant.query.count()
        _fake_supplier(monkeypatch, {'3001': ('SanMar', {'Black': {'M': 40}})})
        CA.run_color_check()
        assert ProductColorVariant.query.count() == before


def test_summary_sections_list_style_and_colors():
    sections = CA.color_summary_sections({'newly_hidden': {'BC3501YCVC': ['Heather Navy', 'Black Heather']}, 'restored': {}})
    assert len(sections) == 1 and sections[0]['count'] == 2
    assert sections[0]['lines'] == ['BC3501YCVC: Heather Navy, Black Heather']


def test_sanmar_stock_parser_sums_warehouses(monkeypatch):
    from services import sanmar_api
    xml = (b'<S:Envelope xmlns:S="x"><S:Body><r><return><errorOccurred>false</errorOccurred><response><style>PC54</style><skus>'
           b'<sku><color>Black</color><size>M</size><whse><whseID>1</whseID><qty>10</qty></whse><whse><whseID>2</whseID><qty>5</qty></whse></sku>'
           b'<sku><color>Jet Black</color><size>L</size><whse><whseID>1</whseID><qty>0</qty></whse></sku>'
           b'</skus></response></return></r></S:Body></S:Envelope>')

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return xml

    monkeypatch.setattr(sanmar_api, 'urlopen', lambda req, timeout=30: Resp())
    stock = sanmar_api.SanMarAPI().fetch_style_color_stock('PC54')
    assert stock == {'Black': {'M': 15}, 'Jet Black': {'L': 0}}


def test_supplier_choice_sanmar_first_then_ss(monkeypatch):
    from services import inventory_sync
    monkeypatch.setattr(inventory_sync, '_fetch_sanmar', lambda style, timeout=30: {})
    monkeypatch.setattr(inventory_sync, '_fetch_ss', lambda style, brand=None, ss_client=None, timeout=30: {'Red': {'M': 3}})
    supplier, totals = CA.fetch_supplier_colors(SimpleNamespace(style_number='3001', brand='Bella+Canvas'))
    assert supplier == 'S&S' and totals == {'red': 3}
    monkeypatch.setattr(inventory_sync, '_fetch_sanmar', lambda style, timeout=30: {'Red': {'M': 1}})
    supplier, _ = CA.fetch_supplier_colors(SimpleNamespace(style_number='PC54', brand='Port & Company'))
    assert supplier == 'SanMar'




def test_bc3005_names_are_cleaned_without_touching_other_colors(app):
    from scripts.fix_bc3005_color_names import fix_names
    with app.app_context():
        p = Product(style_number='BC3005', name='Jersey V', category='Tee', base_price=20, is_active=True,
                    available_colors=json.dumps(['Black', 'blackheather', 'whiteslub', 'Navy Slub']))
        db.session.add(p)
        db.session.flush()
        variants = [ProductColorVariant(product_id=p.id, color_name=n) for n in ('Black', 'blackheather', 'whiteslub', 'Navy Slub')]
        db.session.add_all(variants)
        db.session.flush()
        assert fix_names(p, variants, apply=False) == [('blackheather', 'Black Heather'), ('whiteslub', 'White Slub')]
        assert variants[1].color_name == 'blackheather'
        fix_names(p, variants, apply=True)
        assert [v.color_name for v in variants] == ['Black', 'Black Heather', 'White Slub', 'Navy Slub']
        assert json.loads(p.available_colors) == ['Black', 'Black Heather', 'White Slub', 'Navy Slub']


def test_stock_for_a_style_comes_from_one_supplier_not_both(monkeypatch):
    from services import inventory_sync
    monkeypatch.setattr(inventory_sync, '_fetch_sanmar', lambda style, timeout=30: {'Black': {'M': 5}})
    monkeypatch.setattr(inventory_sync, '_fetch_ss', lambda *a, **k: {'Black': {'M': 7}, 'Pink': {'M': 9}})
    got = inventory_sync.fetch_combined_inventory(SimpleNamespace(style_number='PC54', brand='Port & Company'))
    assert got == {'Black': {'M': 5}}


def test_sold_out_sizes_are_tracked_and_reported_when_they_change(app, seed, monkeypatch):
    with app.app_context():
        sent = _fake_supplier(monkeypatch, {'3001': ('SanMar', {'Black': {'S': 5, 'M': 0, 'L': 3}, 'White': {'S': 1}})})
        tee = _tee(seed)
        tee.available_sizes = json.dumps(['S', 'M', 'L'])
        db.session.commit()
        first = CA.run_color_check()
        assert first['sizes_out']['3001'] == ['Black M', 'White M', 'White L'] or set(first['sizes_out']['3001']) == {'Black M', 'White M', 'White L'}
        monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda p, ss_client=None, timeout=30: ('SanMar', {'Black': {'S': 5, 'M': 4, 'L': 3}, 'White': {'S': 1}}))
        second = CA.run_color_check()
        assert second['sizes_back']['3001'] == ['Black M']


def test_watchdog_emails_when_nothing_finished_and_stays_quiet_after_success(app, seed, monkeypatch):
    with app.app_context():
        problems = []
        monkeypatch.setattr(CA, 'send_sync_problem', lambda what: problems.append(what) or True)
        assert CA.watchdog()  # nothing has ever run
        assert len(problems) == 1
        CA._record(CA.SYNC_OK_KEY, 'test')
        CA._record(CA.COLOR_OK_KEY, 'test')
        assert CA.watchdog() == [] and len(problems) == 1


def test_live_checkout_check_blocks_a_sold_out_item_but_not_a_supplier_outage(app, seed, monkeypatch):
    with app.app_context():
        tee = _tee(seed)
        cart = [{'product_id': tee.id, 'color': 'Black', 'size': 'M', 'quantity': 3}]
        monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda p, ss_client=None, timeout=8: ('SanMar', {'Black': {'M': 2}}))
        assert 'Only 2' in CA.live_cart_stock_error(cart)
        monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda p, ss_client=None, timeout=8: ('SanMar', {'Black': {'M': 0}}))
        assert 'sold out' in CA.live_cart_stock_error(cart)
        monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda p, ss_client=None, timeout=8: ('SanMar', {'Black': {'M': 9}}))
        assert CA.live_cart_stock_error(cart) is None
        monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda p, ss_client=None, timeout=8: (None, {}))
        assert CA.live_cart_stock_error(cart) is None


def test_live_checkout_check_never_blocks_on_an_unrecognised_color_name(app, seed, monkeypatch):
    with app.app_context():
        tee = _tee(seed)
        cart = [{'product_id': tee.id, 'color': 'Black', 'size': 'M', 'quantity': 1}]
        monkeypatch.setattr(CA, 'fetch_supplier_stock', lambda p, ss_client=None, timeout=8: ('SanMar', {'Jet Black': {'M': 0}}))
        assert CA.live_cart_stock_error(cart) is None
