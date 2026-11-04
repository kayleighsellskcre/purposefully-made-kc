"""A saved cart gets one friendly reminder after a day, never twice, never after an order, and can be switched off."""
import json
from datetime import datetime, timedelta

from models import Order, User, db
from tests.conftest import CUSTOMER_EMAIL
from utils import cart_reminders as CR


def _leave_cart(app, seed, hours_ago=30):
    with app.app_context():
        u = User.query.filter_by(email=CUSTOMER_EMAIL).first()
        u.cart_json = json.dumps([{'product_id': seed['tee_id'], 'quantity': 2, 'size': 'M', 'color': 'Black', 'unit_price': 20.0}])
        u.cart_updated_at = datetime.utcnow() - timedelta(hours=hours_ago)
        u.cart_reminder_sent_at = None
        u.cart_reminders_off = False
        db.session.commit()
        return u.id


def _reminders(outbox):
    return [m for m in outbox if 'left something' in m.subject]


def test_a_day_old_cart_gets_one_reminder_with_an_unsubscribe_link(app, seed, outbox):
    _leave_cart(app, seed)
    with app.app_context():
        assert CR.send_due() == 1
        assert CR.send_due() == 0                      # never twice for the same cart
    mails = _reminders(outbox)
    assert len(mails) == 1 and mails[0].recipients == [CUSTOMER_EMAIL]
    assert '/unsubscribe/cart/' in mails[0].html and 'Stop cart reminder emails' in mails[0].body


def test_a_new_change_to_the_cart_starts_it_over(app, seed, outbox):
    uid = _leave_cart(app, seed)
    with app.app_context():
        CR.send_due()
        u = db.session.get(User, uid)
        u.cart_updated_at = datetime.utcnow() - timedelta(hours=26)
        u.cart_reminder_sent_at = datetime.utcnow() - timedelta(days=3)
        db.session.commit()
        assert CR.send_due() == 1


def test_fresh_old_ordered_and_unsubscribed_carts_get_nothing(app, seed, outbox):
    _leave_cart(app, seed, hours_ago=3)
    with app.app_context():
        assert CR.send_due() == 0                      # too fresh
    _leave_cart(app, seed, hours_ago=24 * 9)
    with app.app_context():
        assert CR.send_due() == 0                      # too old
    uid = _leave_cart(app, seed)
    with app.app_context():
        db.session.add(Order(order_number='PMKC-CR1', email=CUSTOMER_EMAIL, user_id=uid, subtotal=10, total=10, status='paid'))
        db.session.commit()
        assert CR.send_due() == 0                      # they ordered since
        db.session.query(Order).delete()
        db.session.commit()
    uid = _leave_cart(app, seed)
    client = app.test_client()
    with app.app_context():
        url = CR.unsubscribe_url(db.session.get(User, uid))
    page = client.get(url[url.index('/unsubscribe'):])
    assert page.status_code == 200 and b'You are unsubscribed' in page.data
    with app.app_context():
        assert CR.send_due() == 0
    assert not _reminders(outbox)
    assert b'did not work' in client.get('/unsubscribe/cart/nonsense').data
