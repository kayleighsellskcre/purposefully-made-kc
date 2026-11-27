"""Admin Operations: vendors, the production workflow board, financial, equipment and the growth dashboard.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import or_
from models import (db, Order, Vendor, GrowthMetric, FinancialEntry)
from datetime import datetime

from routes.admin import _form_money, admin_bp, admin_required  # noqa: E402


# ===== OPERATIONS: VENDORS =====

@admin_bp.route('/operations/vendors')
@admin_required
def vendors():
    vendors_list = Vendor.query.order_by(Vendor.name).all()
    return render_template('admin/operations/vendors.html', vendors=vendors_list)


@admin_bp.route('/operations/vendors/add', methods=['GET', 'POST'])
@admin_required
def add_vendor():
    if request.method == 'POST':
        v = Vendor(name=request.form.get('name'), contact_name=request.form.get('contact_name'),
                   contact_email=request.form.get('contact_email'), contact_phone=request.form.get('contact_phone'),
                   website=request.form.get('website'), website_login=request.form.get('website_login'),
                   lead_time_days=int(request.form.get('lead_time_days') or 0) or None,
                   moq=int(request.form.get('moq') or 0) or None,
                   pricing_tier=request.form.get('pricing_tier'),
                   quality_rating=int(request.form.get('quality_rating') or 0) or None,
                   notes=request.form.get('notes'))
        db.session.add(v)
        db.session.commit()
        flash('Vendor added', 'success')
        return redirect(url_for('admin.vendors'))
    return render_template('admin/operations/vendor_form.html', vendor=None)


@admin_bp.route('/operations/vendors/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_vendor(id):
    v = Vendor.query.get_or_404(id)
    if request.method == 'POST':
        v.name = request.form.get('name')
        v.contact_name = request.form.get('contact_name')
        v.contact_email = request.form.get('contact_email')
        v.contact_phone = request.form.get('contact_phone')
        v.website = request.form.get('website')
        v.website_login = request.form.get('website_login')
        v.lead_time_days = int(request.form.get('lead_time_days') or 0) or None
        v.moq = int(request.form.get('moq') or 0) or None
        v.pricing_tier = request.form.get('pricing_tier')
        v.quality_rating = int(request.form.get('quality_rating') or 0) or None
        v.notes = request.form.get('notes')
        db.session.commit()
        flash('Vendor updated', 'success')
        return redirect(url_for('admin.vendors'))
    return render_template('admin/operations/vendor_form.html', vendor=v)


# ===== OPERATIONS: PRODUCTION WORKFLOW (KANBAN) =====

def _proof_waiting():
    try:
        from utils.proofs import waiting_order_ids
        return waiting_order_ids()
    except Exception:
        db.session.rollback()
        return set()


@admin_bp.route('/operations/workflow')
@admin_required
def production_workflow():
    """5-stage Kanban: Order Received → Waiting Supplies → Ready to Press → Pressed → Packaged Ready"""
    from utils.production_stages import STAGES, orders_for_stage
    from utils.ops_flow import current_collection
    from sqlalchemy.orm import joinedload
    stages = STAGES
    collection_id = current_collection() or None
    order_type = request.args.get('order_type') or None
    sort = request.args.get('sort') or 'oldest'
    if sort not in ('oldest', 'newest', 'due'):
        sort = 'oldest'
    orders_by_stage = {}
    for sid, _name, _desc in stages:
        query = orders_for_stage(sid).options(joinedload(Order.collection))
        if collection_id:
            from utils.group_orders import filter_orders_to_collection
            query = filter_orders_to_collection(query, collection_id)
        if order_type == 'retail':
            query = query.filter(or_(Order.order_type == 'retail', Order.order_type == None))
        elif order_type:
            query = query.filter(Order.order_type == order_type)
        if sort == 'newest':
            query = query.order_by(Order.created_at.desc())
        elif sort == 'due':
            query = query.order_by(Order.due_date.is_(None), Order.due_date, Order.created_at)
        else:
            query = query.order_by(Order.created_at)
        orders_by_stage[sid] = query.all()
    try:
        from models import PaymentCapture
        unsaved_payment_count = (
            PaymentCapture.query
            .filter(PaymentCapture.order_id.is_(None), PaymentCapture.resolved_at.is_(None),
                    db.or_(PaymentCapture.amount.isnot(None), PaymentCapture.awaiting_collection.is_(True)))
            .count()
        )
    except Exception:
        db.session.rollback()
        unsaved_payment_count = 0
    from datetime import datetime
    from utils.production_stages import item_counts_for
    from utils.order_artwork import preload_order_items
    preload_order_items([o for rows in orders_by_stage.values() for o in rows], deep=False)
    return render_template('admin/operations/workflow.html', stages=stages, orders_by_stage=orders_by_stage,
                           item_counts=item_counts_for([o for rows in orders_by_stage.values() for o in rows]),
                           now=datetime.utcnow(), selected_order_type=order_type, selected_sort=sort,
                           unsaved_payment_count=unsaved_payment_count, proof_waiting=_proof_waiting())


@admin_bp.route('/orders/<int:order_id>/update-stage', methods=['POST'])
@admin_required
def update_order_stage(order_id):
    from utils.production_stages import FINISH_LABELS, apply_stage
    order = Order.query.get_or_404(order_id)
    stage = request.form.get('stage')
    from utils.proofs import blocked_reason
    held = blocked_reason(order, stage)
    if held:
        flash(held, 'error')
        return redirect(request.referrer or url_for('admin.production_workflow'))
    if not apply_stage(order, stage):
        flash('Could not update that stage', 'error')
        return redirect(request.referrer or url_for('admin.production_workflow'))
    db.session.commit()
    from utils.customer_emails import notify_in_background
    notify_in_background([order.id], stage)
    if stage in FINISH_LABELS:
        flash('Moved to All Completed', 'success')
        return redirect(url_for('admin.orders_completed'))
    flash('Stage updated', 'success')
    return redirect(request.referrer or url_for('admin.production_workflow'))


@admin_bp.route('/orders/bulk-update-stage', methods=['POST'])
@admin_required
def bulk_update_order_stage():
    """Move one or many orders to a production stage (form or JSON)."""
    from utils.production_stages import MOVE_LABELS, apply_stage

    payload = request.get_json(silent=True) or {}
    stage = (request.form.get('stage') or payload.get('stage') or '').strip()
    raw_ids = request.form.getlist('order_ids')
    if not raw_ids:
        raw_ids = payload.get('order_ids') or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]

    order_ids = []
    for raw in raw_ids:
        try:
            order_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    # De-dupe while preserving order
    seen = set()
    order_ids = [i for i in order_ids if not (i in seen or seen.add(i))]

    wants_json = (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in (request.headers.get('Accept') or '')
    )

    if stage not in MOVE_LABELS:
        if wants_json:
            return jsonify({'ok': False, 'error': 'Invalid stage'}), 400
        flash('Invalid stage', 'error')
        return redirect(request.referrer or url_for('admin.orders'))

    if not order_ids:
        if wants_json:
            return jsonify({'ok': False, 'error': 'No orders selected'}), 400
        flash('Select at least one order', 'error')
        return redirect(request.referrer or url_for('admin.orders'))

    from utils.proofs import blocked_reason
    updated = 0
    moved_ids = []
    held_numbers = []
    for order in Order.query.filter(Order.id.in_(order_ids)).all():
        if blocked_reason(order, stage):
            held_numbers.append(order.order_number)          # waiting on the customer's proof approval
            continue
        if apply_stage(order, stage):
            updated += 1
            moved_ids.append(order.id)
    db.session.commit()
    from utils.customer_emails import notify_in_background
    notify_in_background(moved_ids, stage)

    if wants_json:
        return jsonify({
            'ok': True,
            'updated': updated,
            'stage': stage,
            'stage_label': MOVE_LABELS[stage],
            'order_ids': [i for i in order_ids if i in moved_ids],
            'held': held_numbers,
        })

    label = MOVE_LABELS[stage]
    if held_numbers:
        flash('Not moved, waiting on the customer to approve the proof: ' + ', '.join(held_numbers), 'error')
    flash(f'Moved {updated} order{"s" if updated != 1 else ""} to {label}', 'success')
    if stage in ('completed', 'shipped', 'picked_up'):
        return redirect(url_for('admin.orders_completed'))
    return redirect(request.referrer or url_for('admin.orders'))


# ===== OPERATIONS: FINANCIAL =====

@admin_bp.route('/operations/financial')
@admin_required
def financial():
    from utils.payment_fees import refresh_processing_fee, true_profit
    orders = Order.query.filter(Order.payment_status == 'paid').all()
    # Keep each order's stored profit on the true-profit basis. Fees are fetched
    # from Stripe/PayPal in the background (every 30 minutes), so this page
    # never waits on them.
    changed = False
    for o in orders:
        try:
            changed |= refresh_processing_fee(o, allow_network=False)
        except Exception:
            from utils.quiet_errors import report_quiet
            report_quiet(f'refreshing the card fee on order {o.order_number}')
        new_profit = true_profit(o)
        if new_profit is not None and o.profit != new_profit:
            o.profit = new_profit
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    counted = [o for o in orders if not getattr(o, 'is_refunded', False)]
    total_revenue = sum(o.total or 0 for o in counted)
    total_tax = sum(o.tax or 0 for o in counted)
    total_fees = sum(o.processing_fee or 0 for o in counted)
    total_cogs = sum(o.cost_of_goods or 0 for o in counted)
    total_profit = sum(o.profit or 0 for o in counted if o.profit is not None)
    fees_estimated = sum(1 for o in counted if not o.processing_fee_is_actual)
    entries = FinancialEntry.query.order_by(FinancialEntry.entry_date.desc()).limit(100).all()
    return render_template('admin/operations/financial.html',
                         total_revenue=total_revenue, total_profit=total_profit,
                         total_tax=total_tax, total_fees=total_fees, total_cogs=total_cogs,
                         fees_estimated=fees_estimated,
                         entries=entries)


@admin_bp.route('/operations/financial/entry/add', methods=['POST'])
@admin_required
def add_financial_entry():
    e = FinancialEntry(category=request.form.get('category'), amount=_form_money('amount', 0.0),
                       description=request.form.get('description'))
    db.session.add(e)
    db.session.commit()
    flash('Entry added', 'success')
    return redirect(url_for('admin.financial'))


# ===== OPERATIONS: EQUIPMENT =====

# ===== OPERATIONS: GROWTH DASHBOARD =====

@admin_bp.route('/operations/growth')
@admin_required
def growth():
    metrics = GrowthMetric.query.order_by(GrowthMetric.week_start.desc()).limit(12).all()
    return render_template('admin/operations/growth.html', metrics=metrics)


@admin_bp.route('/operations/growth/sync', methods=['POST'])
@admin_required
def sync_growth_metrics():
    """Auto-sync weekly metrics from orders & collections"""
    try:
        from services.growth_sync import sync_all_recent_weeks
        results = sync_all_recent_weeks(weeks=4)
        updated = sum(1 for _, a in results if a == 'updated')
        created = sum(1 for _, a in results if a == 'created')
        flash(f'Auto-synced: {created} new, {updated} updated (units, revenue, events, wholesale from your data)', 'success')
    except Exception as e:
        flash(f'Sync failed: {str(e)}', 'error')
    return redirect(url_for('admin.growth'))


@admin_bp.route('/operations/growth/add', methods=['POST'])
@admin_required
def add_growth_metric():
    m = GrowthMetric(week_start=datetime.fromisoformat(request.form.get('week_start')),
                     units_sold=int(request.form.get('units_sold') or 0),
                     revenue=_form_money('revenue', 0.0),
                     website_traffic=int(request.form.get('website_traffic') or 0),
                     events_booked=int(request.form.get('events_booked') or 0),
                     wholesale_inquiries=int(request.form.get('wholesale_inquiries') or 0),
                     social_reach=int(request.form.get('social_reach') or 0),
                     notes=request.form.get('notes'))
    db.session.add(m)
    db.session.commit()
    flash('Weekly metric added', 'success')
    return redirect(url_for('admin.growth'))


@admin_bp.route('/operations/growth/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_growth_metric(id):
    m = GrowthMetric.query.get_or_404(id)
    if request.method == 'POST':
        m.week_start = datetime.fromisoformat(request.form.get('week_start'))
        m.units_sold = int(request.form.get('units_sold') or 0)
        m.revenue = _form_money('revenue', 0.0)
        m.website_traffic = int(request.form.get('website_traffic') or 0)
        m.events_booked = int(request.form.get('events_booked') or 0)
        m.wholesale_inquiries = int(request.form.get('wholesale_inquiries') or 0)
        m.social_reach = int(request.form.get('social_reach') or 0)
        m.notes = request.form.get('notes') or None
        db.session.commit()
        flash('Weekly metric updated', 'success')
        return redirect(url_for('admin.growth'))
    return render_template('admin/operations/growth_edit.html', metric=m)
