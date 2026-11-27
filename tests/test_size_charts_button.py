"""The Products page button that fills in each style's own size chart."""
from utils.size_charts import build_chart, _odd


def test_button_is_on_the_products_page_and_starts_the_fill(admin_client, monkeypatch):
    page = admin_client.get('/admin/products')
    assert b'Fill in size charts' in page.data
    started = []
    monkeypatch.setattr('utils.size_charts.start_fill_thread', lambda app, force=False: started.append(force))
    resp = admin_client.post('/admin/products/fill-size-charts', follow_redirects=True)
    assert resp.status_code == 200
    assert started == [False]            # never replaces a chart that is already there


def test_guest_cannot_start_it(guest):
    assert guest.post('/admin/products/fill-size-charts').status_code in (302, 401, 403)


def test_chart_is_built_in_size_order_and_odd_ones_are_caught():
    rows = []
    for size, chest, length in (('S', '18', '28'), ('M', '20', '29'), ('L', '22', '30')):
        rows += [{'specName': 'Chest Width', 'sizeName': size, 'value': chest}, {'specName': 'Body Length', 'sizeName': size, 'value': length}]
    chart = build_chart(rows)
    assert list(chart) == ['S', 'M', 'L'] and chart['M']['chest'] == '20'
    assert _odd(chart) == ''
    assert _odd({'S': {'chest': '20', 'length': '28'}, 'M': {'chest': '18', 'length': '29'}}) != ''
