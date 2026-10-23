"""Orders opens on the board, with the filters, search and buttons the list had."""
from datetime import datetime, timedelta

from models import db, Order
from tests.test_orders_list_parity import _order


def _make(app, seed):
    with app.app_context():
        _order(seed, first_name='Retailer', order_type='retail', due_date=datetime.utcnow() + timedelta(days=9))
        _order(seed, first_name='Wholesaler', order_type='wholesale', due_date=datetime.utcnow() + timedelta(days=2))
        _order(seed, first_name='Nodue', order_type='retail')


def test_bare_orders_link_opens_the_board(admin_client):
    resp = admin_client.get('/admin/orders')
    assert resp.status_code == 302 and '/admin/operations/workflow' in resp.headers['Location']
    # A stage in the link keeps the list, so filtered links still work.
    assert admin_client.get('/admin/orders?stage=all').status_code == 200


def test_navigation_orders_step_goes_to_the_board(admin_client):
    html = admin_client.get('/admin/operations/workflow').get_data(as_text=True)
    assert 'href="/admin/operations/workflow"' in html          # the "1. Orders" step


def test_board_has_the_buttons_filters_and_search_the_list_had(admin_client, app, seed):
    _make(app, seed)
    html = admin_client.get('/admin/operations/workflow').get_data(as_text=True)
    for text in ('List view', 'Order blanks', 'Press sheets', 'Print labels', 'Create invoice', 'All Completed',
                 'Retail', 'Wholesale', 'Event', 'Oldest first', 'Newest', 'Due date', 'id="wfSearch"'):
        assert text in html, text
    assert 'Retailer' in html and 'Wholesaler' in html


def test_board_filters_by_type_and_sorts_by_due_date(admin_client, app, seed):
    _make(app, seed)
    wholesale = admin_client.get('/admin/operations/workflow?order_type=wholesale').get_data(as_text=True)
    assert 'Wholesaler' in wholesale and 'Retailer' not in wholesale
    retail = admin_client.get('/admin/operations/workflow?order_type=retail').get_data(as_text=True)
    assert 'Retailer' in retail and 'Wholesaler' not in retail and 'Nodue' in retail   # no type counts as retail
    due = admin_client.get('/admin/operations/workflow?sort=due').get_data(as_text=True)
    assert due.index('Wholesaler') < due.index('Retailer') < due.index('Nodue')
