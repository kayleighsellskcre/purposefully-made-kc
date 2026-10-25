"""The morning digest and the Monday summary: what needs Kayleigh's attention, with a link to the right admin page.

The daily email goes at 7 AM Kansas City time, the weekly one on Monday. Each section opens the page where the work is done.
Nothing is sent twice for the same day or week.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import or_

from models import AdminNotification, Collection, CustomDesignRequest, Order
from utils import ledger as L
from utils.production_stages import OPEN_STATUSES, STAGE_LABELS, orders_for_stage
from utils.site_settings import get_setting, set_setting

STUCK_DAYS = 5
DUE_SOON_DAYS = 3
SHOW = 6                                   # names listed per section before "and N more"
DAILY_KEY, WEEKLY_KEY = 'daily_digest_sent', 'weekly_digest_sent'

LINKS = {
    'orders': '/admin/orders', 'workflow': '/admin/operations/workflow', 'inbox': '/admin/notifications',
    'requests': '/admin/custom-design-requests', 'stores': '/admin/collections', 'growth': '/admin/operations/growth',
    'blanks': '/admin/production/blank-apparel-list', 'reports': '/admin/operations/reports', 'lowstock': '/admin/operations/low-stock',
}


def _utc(day_start: datetime) -> datetime:
    return day_start.astimezone(timezone.utc).replace(tzinfo=None)


def _kc_midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time()).replace(tzinfo=L.CENTRAL)


def _names(rows, label, limit=SHOW):
    labels = [label(r) for r in rows]
    more = len(labels) - limit
    return labels[:limit] + ([f'and {more} more'] if more > 0 else [])


def _order_label(o):
    who = f'{o.first_name or ""} {o.last_name or ""}'.strip() or (o.email or '')
    return f'{o.order_number}  {who}'.strip()


def _open_orders():
    return Order.query.filter(Order.status.in_(OPEN_STATUSES), Order.payment_status.in_(['paid', 'pending']))


def daily_sections(now=None):
    """The sections of the morning digest. Empty sections are left out."""
    now = now or L.kc_now()
    today = now.date()
    since = _utc(now - timedelta(hours=24))
    out = []

    new = Order.query.filter(Order.payment_status == 'paid',
                             or_(Order.paid_at >= since, (Order.paid_at.is_(None)) & (Order.created_at >= since))
                             ).order_by(Order.created_at).all()
    if new:
        total = sum(float(o.total or 0) for o in new)
        out.append({'key': 'new', 'title': 'New orders since yesterday', 'count': len(new), 'tone': 'good',
                    'lines': _names(new, _order_label) + [f'${total:,.2f} in all'], 'link': LINKS['orders'], 'link_label': 'Open orders'})

    open_orders = _open_orders().all()
    overdue = sorted([o for o in open_orders if o.due_date and L.kc_day(o.due_date) < today], key=lambda o: o.due_date)
    if overdue:
        out.append({'key': 'overdue', 'title': 'Overdue', 'count': len(overdue), 'tone': 'warn',
                    'lines': _names(overdue, lambda o: f'{_order_label(o)} (due {L.kc_day(o.due_date).strftime("%b")} {L.kc_day(o.due_date).day})'),
                    'link': LINKS['workflow'], 'link_label': 'Open the workflow board'})
    soon_end = today + timedelta(days=DUE_SOON_DAYS)
    due_soon = sorted([o for o in open_orders if o.due_date and today <= L.kc_day(o.due_date) <= soon_end], key=lambda o: o.due_date)
    if due_soon:
        out.append({'key': 'due', 'title': f'Due in the next {DUE_SOON_DAYS} days', 'count': len(due_soon), 'tone': 'plain',
                    'lines': _names(due_soon, lambda o: f'{_order_label(o)} (due {L.kc_day(o.due_date).strftime("%b")} {L.kc_day(o.due_date).day})'),
                    'link': LINKS['workflow'], 'link_label': 'Open the workflow board'})

    cutoff = _utc(now - timedelta(days=STUCK_DAYS))
    stuck_lines, stuck_total = [], 0
    for stage_id in ('order_received', 'waiting_supplies', 'ready_to_press', 'pressed'):
        stuck = orders_for_stage(stage_id).filter(Order.updated_at < cutoff).count()
        if stuck:
            stuck_total += stuck
            stuck_lines.append(f'{stuck} in {STAGE_LABELS[stage_id]}')
    if stuck_total:
        out.append({'key': 'stuck', 'title': f'Sitting in one stage more than {STUCK_DAYS} days', 'count': stuck_total, 'tone': 'warn',
                    'lines': stuck_lines, 'link': LINKS['workflow'], 'link_label': 'Open the workflow board'})

    closing = (Collection.query.filter(Collection.is_active.is_(True), Collection.order_deadline.isnot(None),
                                       Collection.order_deadline >= _utc(now), Collection.order_deadline < _utc(now + timedelta(days=7)))
               .order_by(Collection.order_deadline).all())
    if closing:
        out.append({'key': 'closing', 'title': 'Group stores closing this week', 'count': len(closing), 'tone': 'plain',
                    'lines': _names(closing, lambda c: f'{c.name} (closes {L.kc_day(c.order_deadline).strftime("%a %b")} {L.kc_day(c.order_deadline).day})'),
                    'link': LINKS['stores'], 'link_label': 'Open group stores'})

    pending = CustomDesignRequest.query.filter(CustomDesignRequest.status == 'pending',
                                               CustomDesignRequest.is_deleted.isnot(True)).count()
    if pending:
        out.append({'key': 'requests', 'title': 'Recreate requests waiting', 'count': pending, 'tone': 'plain',
                    'lines': [f'{pending} waiting for you to start'], 'link': LINKS['requests'], 'link_label': 'Open the requests'})

    from utils import low_stock
    fresh = low_stock.newly_low()
    if fresh:
        out.append({'key': 'lowstock', 'title': 'Running low', 'count': len(fresh), 'tone': 'warn',
                    'lines': [low_stock.line(i) for i in fresh[:SHOW]] + ([f'and {len(fresh) - SHOW} more'] if len(fresh) > SHOW else []),
                    'link': LINKS['lowstock'], 'link_label': 'See what is low'})

    unread = AdminNotification.query.filter(AdminNotification.read_at.is_(None)).count()
    if unread:
        out.append({'key': 'messages', 'title': 'Unread messages', 'count': unread, 'tone': 'plain',
                    'lines': [f'{unread} in your inbox'], 'link': LINKS['inbox'], 'link_label': 'Open the inbox'})
    return out


def weekly_summary(now=None):
    """Last week's units, sales and profit, plus the blanks to order for orders not yet ordered."""
    from services.growth_sync import sync_weekly_metrics
    from utils.blank_orders import build_blank_shopping_list
    now = now or L.kc_now()
    this_monday = now.date() - timedelta(days=now.date().weekday())
    last_monday = this_monday - timedelta(days=7)
    metric, _how = sync_weekly_metrics(datetime.combine(last_monday, datetime.min.time()))
    p = L.pnl(last_monday, this_monday - timedelta(days=1))
    shopping = build_blank_shopping_list(orders_for_stage('order_received').all())
    blanks = [{'vendor': v['name'], 'quantity': v['quantity']} for v in shopping['vendors']]
    return {'week': last_monday, 'units': int(metric.units_sold or 0), 'net_sales': p['net_sales'], 'gross_profit': p['gross_profit'],
            'blanks': blanks, 'blank_total': sum(b['quantity'] for b in blanks)}


# ---- sending ---------------------------------------------------------------------------------------

def _deliver(subject, heading, intro, sections, base_url):
    from flask_mail import Message
    from routes.checkout import _render_email
    from utils.mailer import mail_configured, reply_to, send as send_mail, sender, admin_recipient
    app = current_app._get_current_object()
    to = admin_recipient(app)
    if not to or not mail_configured(app):
        return False
    for s in sections:
        s['url'] = base_url + s['link']
    html = _render_email('email/daily_digest.html', heading=heading, intro=intro, sections=sections)
    text = [heading, '', intro, '']
    for s in sections:
        text += [f"{s['title']} ({s['count']})"] + [f'  {line}' for line in s['lines']] + [f"  {s['link_label']}: {s['url']}", '']
    msg = Message(subject=subject, recipients=[to], body='\n'.join(text), html=html, sender=sender(app), reply_to=reply_to(app))

    def run():
        with app.app_context():
            send_mail(app, msg, description=f'digest: {subject}')
    if app.config.get('TESTING'):
        run()
    else:
        from threading import Thread
        Thread(target=run, daemon=True).start()
    return True


def send_daily(now=None, force=False):
    """The 7 AM digest. Sent once a day, and only when there is something to say. Returns True if sent."""
    from utils.mailer import admin_base_url
    now = now or L.kc_now()
    key = now.date().isoformat()
    if not force and get_setting(DAILY_KEY, '') == key:
        return False
    sections = daily_sections(now)
    if not sections:
        return False
    attention = sum(s['count'] for s in sections if s['tone'] == 'warn')
    subject = f"Your morning: {len(sections)} thing{'s' if len(sections) != 1 else ''} to look at" + (' (some overdue)' if any(s['key'] == 'overdue' for s in sections) else '')
    intro = f"Good morning! Here is what needs you today, {now.strftime('%A, %B')} {now.day}." + (f' {attention} need a closer look.' if attention else '')
    sent = _deliver(subject, 'Good morning', intro, sections, admin_base_url(current_app))
    if sent:
        set_setting(DAILY_KEY, key, 'The last day the morning digest was handled')
        if any(s['key'] == 'lowstock' for s in sections):
            from utils import low_stock
            low_stock.mark_seen()
    return sent


def send_weekly(now=None, force=False):
    """The Monday summary: last week's numbers and the blanks to order this week. Once per week."""
    from utils.mailer import admin_base_url
    now = now or L.kc_now()
    monday = now.date() - timedelta(days=now.date().weekday())
    key = monday.isoformat()
    if not force and get_setting(WEEKLY_KEY, '') == key:
        return False
    w = weekly_summary(now)
    end = w['week'] + timedelta(days=6)
    sections = [
        {'key': 'week', 'title': f"Last week ({w['week'].strftime('%b')} {w['week'].day} to {end.strftime('%b')} {end.day})", 'count': w['units'],
         'tone': 'good', 'lines': [f"{w['units']} units sold", f"{L.dollars(w['net_sales'])} net sales", f"{L.dollars(w['gross_profit'])} gross profit"],
         'link': LINKS['reports'], 'link_label': 'Open the reports'},
        {'key': 'blanks', 'title': 'Blanks to order this week', 'count': w['blank_total'], 'tone': 'plain',
         'lines': [f"{b['vendor']}: {b['quantity']} pieces" for b in w['blanks']] or ['Nothing new to order'],
         'link': LINKS['blanks'], 'link_label': 'Open the blank list'},
    ]
    from utils import low_stock
    low = low_stock.low_items()
    if low:
        sections.append({'key': 'low', 'title': 'Still running low', 'count': len(low), 'tone': 'plain',
                         'lines': [low_stock.line(i) for i in low[:SHOW]] + ([f'and {len(low) - SHOW} more'] if len(low) > SHOW else []),
                         'link': LINKS['lowstock'], 'link_label': 'See what is low'})
    sent = _deliver(f"Last week: {w['units']} units, {L.dollars(w['net_sales'])} in sales", 'Your week', 'Here is how last week went, and what to order for this one.',
                    sections, admin_base_url(current_app))
    if sent:
        set_setting(WEEKLY_KEY, key, 'The last week whose summary email was sent')
    return sent
