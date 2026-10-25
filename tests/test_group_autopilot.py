"""Group orders on autopilot: weekly progress, two days left, and the closed summary."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from models import Collection, Order, OrderItem, db
from tests.conftest import CUSTOMER_EMAIL
from utils import group_autopilot as G
from utils.group_orders import parse_order_deadline

CHICAGO = ZoneInfo('America/Chicago')


def _today():
    return datetime.now(CHICAGO).date()


def _prepare(app, coll_id, day, **fields):
    with app.app_context():
        c = db.session.get(Collection, coll_id)
        c.order_deadline = parse_order_deadline(day.strftime('%Y-%m-%d'))
        c.is_active = True
        c.created_by_user_id = fields.pop('created_by_user_id', c.created_by_user_id)
        c.created_at = datetime.utcnow() - timedelta(days=30)
        c.progress_sent_at = c.two_day_sent_at = c.closed_summary_sent_at = None
        for key, value in fields.items():
            setattr(c, key, value)
        db.session.commit()
        return c.name, c.slug


def _order(app, seed, size='M', qty=2, number='PMKC-GA1'):
    with app.app_context():
        o = Order(order_number=number, email='p@example.com', first_name='Pat', last_name='Parent', subtotal=40.0, total=40.0,
                  payment_status='paid', status='paid', payment_method='stripe', collection_id=seed['collection_id'],
                  paid_at=datetime.utcnow())
        db.session.add(o)
        db.session.flush()
        db.session.add(OrderItem(order_id=o.id, product_id=seed['tee_id'], product_name='Tee', size=size, color='Black', quantity=qty,
                                 unit_price=20.0, subtotal=20.0 * qty, collection_id=seed['collection_id']))
        db.session.commit()


def _run(app, fn, today=None):
    with app.app_context():
        return fn(today or _today())


def _to(outbox, address):
    return [m for m in outbox if address.lower() in [r.lower() for r in m.recipients]]


def test_sizes_are_counted_from_paid_orders(app, seed):
    _prepare(app, seed['collection_id'], _today() + timedelta(days=10), created_by_user_id=seed['customer_id'])
    _order(app, seed, 'M', 2)
    _order(app, seed, 'L', 3, number='PMKC-GA2')
    with app.app_context():
        store = db.session.get(Collection, seed['collection_id'])
        assert G.size_counts(store) == {'M': 2, 'L': 3}
        assert G.sizes_text(G.size_counts(store)) == 'M x2, L x3' and G.order_count(store) == 2
        assert G.sizes_text({}) == 'none yet'


def test_progress_goes_to_the_organizer_once_a_week(app, seed, outbox):
    _prepare(app, seed['collection_id'], _today() + timedelta(days=10), created_by_user_id=seed['customer_id'])
    _order(app, seed)
    assert _run(app, G.send_progress) == 1
    mail = _to(outbox, CUSTOMER_EMAIL)[0]
    assert 'going' in mail.subject.lower() and 'M x2' in mail.body and '10 days left' in mail.body
    assert _run(app, G.send_progress) == 0                                     # not again this week
    with app.app_context():
        db.session.get(Collection, seed['collection_id']).progress_sent_at = datetime.utcnow() - timedelta(days=7)
        db.session.commit()
    assert _run(app, G.send_progress) == 1


def test_progress_skips_new_stores_nearly_closed_stores_and_closed_ones(app, seed, outbox):
    _prepare(app, seed['collection_id'], _today() + timedelta(days=10), created_by_user_id=seed['customer_id'],
             created_at=datetime.utcnow() - timedelta(days=1))
    assert _run(app, G.send_progress) == 0                                     # opened yesterday
    _prepare(app, seed['collection_id'], _today() + timedelta(days=2), created_by_user_id=seed['customer_id'])
    assert _run(app, G.send_progress) == 0                                     # the two day note covers this
    _prepare(app, seed['collection_id'], _today() - timedelta(days=2), created_by_user_id=seed['customer_id'])
    assert _run(app, G.send_progress) == 0 and len(outbox) == 0


def test_two_day_note_has_text_to_copy_and_goes_once(app, seed, outbox):
    name, slug = _prepare(app, seed['collection_id'], _today() + timedelta(days=2), created_by_user_id=seed['customer_id'])
    assert _run(app, G.send_two_day) == 1
    mail = _to(outbox, CUSTOMER_EMAIL)[0]
    assert 'Two days left' in mail.subject and f'/c/{slug}' in mail.body and 'close on' in mail.body
    assert _run(app, G.send_two_day) == 0
    _prepare(app, seed['collection_id'], _today() + timedelta(days=5), created_by_user_id=seed['customer_id'])
    assert _run(app, G.send_two_day) == 0                                      # only exactly two days out


def test_closed_summary_goes_to_organizer_and_owner_once(app, seed, outbox):
    name, _slug = _prepare(app, seed['collection_id'], _today() - timedelta(days=1), created_by_user_id=seed['customer_id'])
    _order(app, seed, 'M', 4)
    assert _run(app, G.send_closed_summary) == 2
    organizer = _to(outbox, CUSTOMER_EMAIL)[0]
    owner = _to(outbox, app.config['ADMIN_EMAIL'])[0]
    assert organizer.subject == f'{name} is closed' and 'M x4' in organizer.body
    assert 'blank-apparel-list?collection=' in owner.body and '1 order' in owner.subject
    assert _run(app, G.send_closed_summary) == 0


def test_closed_summary_with_no_orders_tells_only_the_owner(app, seed, outbox):
    _prepare(app, seed['collection_id'], _today() - timedelta(days=1), created_by_user_id=seed['customer_id'])
    assert _run(app, G.send_closed_summary) == 1
    assert _to(outbox, CUSTOMER_EMAIL) == [] and len(_to(outbox, app.config['ADMIN_EMAIL'])) == 1


def test_old_closed_stores_are_never_emailed(app, seed, outbox):
    _prepare(app, seed['collection_id'], _today() - timedelta(days=40), created_by_user_id=seed['customer_id'])
    _order(app, seed)
    assert _run(app, G.send_closed_summary) == 0 and len(outbox) == 0


def test_the_daily_run_does_progress_only_on_mondays(app, seed, outbox):
    _prepare(app, seed['collection_id'], _today() + timedelta(days=12), created_by_user_id=seed['customer_id'])
    _order(app, seed)
    monday = _today() - timedelta(days=_today().weekday())
    tuesday = monday + timedelta(days=1)
    assert _run(app, G.run_all, tuesday)['progress'] == 0
    assert _run(app, G.run_all, monday)['progress'] == 1
