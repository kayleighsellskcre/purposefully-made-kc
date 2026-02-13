"""Auto-sync weekly growth metrics from database (orders, collections)."""
from datetime import datetime, timedelta
from sqlalchemy import and_, or_
from models import db, Order, OrderItem, Collection, GrowthMetric


def get_monday_of_week(dt):
    """Return Monday 00:00:00 of the week containing dt."""
    return (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def sync_weekly_metrics(week_start=None):
    """
    Sync growth metrics for a given week from database.
    Auto-populates: units_sold, revenue, events_booked, wholesale_inquiries.
    website_traffic and social_reach require external integrations (Google Analytics, etc.).
    
    Args:
        week_start: datetime of Monday, or None for current week
    Returns:
        (GrowthMetric, created_or_updated)
    """
    if week_start is None:
        week_start = get_monday_of_week(datetime.utcnow())
    elif isinstance(week_start, datetime) and week_start.weekday() != 0:
        week_start = get_monday_of_week(week_start)
    
    week_end = week_start + timedelta(days=7)
    
    # Orders paid in this week (use paid_at, fallback to created_at for cash)
    paid_orders = Order.query.filter(
        Order.payment_status == 'paid',
        or_(
            and_(Order.paid_at >= week_start, Order.paid_at < week_end),
            and_(Order.paid_at.is_(None), Order.created_at >= week_start, Order.created_at < week_end)
        )
    ).all()
    
    units_sold = sum(
        sum(item.quantity for item in o.items)
        for o in paid_orders
    )
    revenue = sum(o.total for o in paid_orders if not getattr(o, 'is_refunded', False))
    wholesale_orders = sum(1 for o in paid_orders if (o.order_type or '') == 'wholesale')
    
    # New collections (events) created in this week
    events_booked = Collection.query.filter(
        Collection.created_at >= week_start,
        Collection.created_at < week_end
    ).count()
    
    existing = GrowthMetric.query.filter(
        GrowthMetric.week_start >= week_start,
        GrowthMetric.week_start < week_end
    ).first()
    
    if existing:
        existing.units_sold = units_sold
        existing.revenue = revenue
        existing.events_booked = events_booked
        existing.wholesale_inquiries = wholesale_orders
        # Preserve website_traffic and social_reach (require external integration)
        db.session.commit()
        return existing, 'updated'
    else:
        m = GrowthMetric(
            week_start=week_start,
            units_sold=units_sold,
            revenue=revenue,
            events_booked=events_booked,
            wholesale_inquiries=wholesale_orders,
            website_traffic=0,
            social_reach=0,
            notes='Auto-synced from orders & collections'
        )
        db.session.add(m)
        db.session.commit()
        return m, 'created'


def sync_all_recent_weeks(weeks=4):
    """Sync metrics for the last N weeks."""
    results = []
    for i in range(weeks):
        week_start = get_monday_of_week(datetime.utcnow()) - timedelta(weeks=i)
        m, action = sync_weekly_metrics(week_start)
        results.append((m, action))
    return results
