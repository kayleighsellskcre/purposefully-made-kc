"""Phase A quick fixes: Kansas City times, repeat customers, weekly growth sync, sitemap, wording."""
import threading
from datetime import datetime, timedelta

from models import Collection, GrowthMetric, Order, OrderItem, User, db


def _in_db(app, fn):
    out = {}

    def run():
        with app.app_context():
            try:
                out['value'] = fn()
            except Exception as exc:          # pragma: no cover
                out['error'] = exc
    t = threading.Thread(target=run)
    t.start()
    t.join()
    if 'error' in out:
        raise out['error']
    return out.get('value')


def _order(number, **kw):
    o = Order(order_number=number, email=kw.pop('email', 'amy@example.com'), subtotal=10.0, total=kw.pop('total', 10.0),
              status=kw.pop('status', 'paid'), payment_status=kw.pop('payment_status', 'paid'), **kw)
    db.session.add(o)
    db.session.flush()
    return o


# ---- A6: Kansas City time ----

def test_order_page_shows_paid_time_in_kansas_city(admin_client, app, seed):
    def make():
        o = _order('PMKC-TZ1', paid_at=datetime(2026, 10, 23, 21, 33))          # 9:33 PM UTC is 4:33 PM in Kansas City
        db.session.commit()
        return o.id
    oid = _in_db(app, make)
    html = admin_client.get(f'/admin/orders/{oid}').get_data(as_text=True)
    assert '4:33 PM' in html and '9:33 PM' not in html


def test_completed_orders_group_by_kansas_city_month(admin_client, app, seed):
    def make():
        _order('PMKC-TZ2', status='completed', updated_at=datetime(2026, 11, 1, 3, 30))   # still Oct 31 at 10:30 PM in Kansas City
        db.session.commit()
    _in_db(app, make)
    html = admin_client.get('/admin/orders/completed').get_data(as_text=True)
    assert 'October 2026' in html and 'November 2026' not in html


# ---- A7: compact admin header ----

def test_admin_pages_use_the_compact_header(admin_client, seed):
    assert '<body class="is-admin">' in admin_client.get('/admin/').get_data(as_text=True)


def test_public_pages_keep_the_normal_header(guest, seed):
    assert 'is-admin' not in guest.get('/about').get_data(as_text=True).split('<body')[1].split('>')[0]


# ---- A8: weekly growth numbers, weeks run Monday to Sunday in Kansas City ----

def test_growth_week_boundary_is_kansas_city_midnight(app, seed):
    def go():
        # Sunday Oct 25, 9 PM in Kansas City is Monday Oct 26, 2 AM UTC: still last week
        o = _order('PMKC-WK1', paid_at=datetime(2026, 10, 26, 2, 0))
        db.session.add(OrderItem(order_id=o.id, product_id=seed['tee_id'], product_name='Tee', style_number='3001', size='M',
                                 color='Black', quantity=3, unit_price=10, subtotal=30))
        db.session.commit()
        from services.growth_sync import sync_weekly_metrics
        last_week, _ = sync_weekly_metrics(datetime(2026, 10, 19))
        this_week, _ = sync_weekly_metrics(datetime(2026, 10, 26))
        return last_week.units_sold, this_week.units_sold
    assert _in_db(app, go) == (3, 0)


def test_the_growth_job_exists_and_runs(app, seed):
    import scheduler

    def go():
        scheduler.growth_sync_job(app)
        return GrowthMetric.query.count()
    assert _in_db(app, go) >= 1


# ---- A9: repeat customers by email ----

def test_repeat_customers_match_guest_and_account_orders_by_email(admin_client, app, seed):
    def make():
        user = User.query.filter_by(email='customer-test@example.com').first()
        _order('PMKC-R1', email='Casey.Customer@Example.com', user_id=None)
        _order('PMKC-R2', email='casey.customer@example.com', user_id=user.id)
        _order('PMKC-R3', email='once@example.com')
        _order('PMKC-R4', email='cancelled@example.com')
        _order('PMKC-R5', email='cancelled@example.com', status='cancelled')
        db.session.commit()
    _in_db(app, make)
    html = admin_client.get('/admin/operations/customers').get_data(as_text=True)
    assert 'casey.customer@example.com' in html
    assert 'once@example.com' not in html and 'cancelled@example.com' not in html


# ---- A2, A3, A4, A10, A11 ----

def test_ai_examples_have_no_trademarked_team_names():
    src = open('templates/custom_request/ai_design.html', encoding='utf-8').read()
    assert 'Chiefs' not in src and 'Jayhawk' not in src
    assert 'Fierce tiger mascot' in src and 'Football helmet with sunflowers' in src


def test_sitemap_lists_customizer_pages_and_only_open_stores(guest, app, seed):
    def make():
        db.session.add(Collection(name='Open Store', slug='open-store', is_active=True, show_in_directory=True))
        db.session.add(Collection(name='Soccer Closed', slug='soccer-closed', is_active=True, show_in_directory=True,
                                  order_deadline=datetime.utcnow() - timedelta(days=30)))
        db.session.commit()
    _in_db(app, make)
    xml = guest.get('/sitemap.xml').get_data(as_text=True)
    assert '/shop/customize/' in xml and '/shop/product/' not in xml
    assert '/c/open-store' in xml and 'soccer-closed' not in xml


def test_grade_is_a_dropdown_and_footer_has_kind_words():
    src = open('templates/checkout/index.html', encoding='utf-8').read()
    assert '<select id="child_grade"' in src and 'Pre-K' in src and 'Staff' in src and '12th' in src
    assert "e.g. 3rd or Kindergarten" not in src


def test_signed_in_header_can_shorten_the_account_label(client, login):
    from tests.conftest import CUSTOMER_EMAIL
    login(client, CUSTOMER_EMAIL)
    html = client.get('/shop/').get_data(as_text=True)
    assert '<span class="nav-account-my">My </span>Account' in html
    css = open('static/css/main.css', encoding='utf-8').read()
    assert '.nav-account-my, .nav-account-chev { display: none; }' in css
