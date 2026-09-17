"""DTF transfer cost config helpers."""
import json
from pathlib import Path

import pytest

from utils import order_costs


@pytest.fixture
def costs_tmpdir(tmp_path, monkeypatch):
    path = tmp_path / 'costs.json'
    monkeypatch.setattr(order_costs, '_COSTS_PATH', path)
    return path


def test_get_dtf_costs_creates_defaults(costs_tmpdir):
    data = order_costs.get_dtf_costs()
    assert data['dtf_per_sq_in'] == 0.05
    assert data['dtf_gang_sheet_per_foot'] == 11.5
    assert data['dtf_vendor'] == 'JiffyShirts.com'
    assert data['dtf_notes'] == ''
    assert costs_tmpdir.is_file()


def test_save_and_reload_dtf_costs(costs_tmpdir):
    saved = order_costs.save_dtf_costs({
        'dtf_per_sq_in': '0.07',
        'dtf_gang_sheet_per_foot': '12.25',
        'dtf_vendor': 'Example Vendor',
        'dtf_notes': 'free shipping over $29',
    })
    assert saved['dtf_per_sq_in'] == 0.07
    assert saved['dtf_gang_sheet_per_foot'] == 12.25
    reloaded = order_costs.get_dtf_costs()
    assert reloaded['dtf_vendor'] == 'Example Vendor'
    assert reloaded['dtf_notes'] == 'free shipping over $29'
    raw = json.loads(costs_tmpdir.read_text(encoding='utf-8'))
    assert raw['dtf_per_sq_in'] == 0.07


def test_dtf_shopping_list_print_type_is_large(admin_client):
    resp = admin_client.get('/admin/production/dtf-batch-sheets')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    print_css = body.split('@media print')[-1]
    assert '.dtf-cards {\n        display: flex !important;\n        flex-direction: column !important;' in print_css.replace('\r\n', '\n')
    assert 'font-size: 16pt' in print_css
    assert 'font-size: 14pt' in print_css
    assert 'font-size: 8.5pt' not in print_css


def test_inventory_routes_require_admin(client):
    assert client.get('/admin/inventory').status_code in (302, 401, 403)
    assert client.post('/admin/inventory/save-costs').status_code in (302, 400, 401, 403)
