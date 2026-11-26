"""Admin: Kansas Sales Tax. One page per filing period that follows the Kansas portal screen by screen."""
import csv
import json
from datetime import datetime
from io import StringIO

from flask import Response, flash, redirect, render_template, request, url_for

from models import Order, db
from routes.admin import admin_bp, admin_required
from utils import ks_tax as K
from utils import ledger as L


def _start_param():
    return K.parse_date(request.values.get('start')) if request.values.get('start') else None


def _default_start(today):
    """The period that most needs a look: last period if it is not filed yet, otherwise the current one."""
    start, end = K.period_for(today)
    prev_start, prev_end = K.previous_period(start)
    prev = K.get_filing(prev_start, prev_end, create=False)
    if prev is None or not prev.return_filed_on:
        return prev_start
    return start


def _period_choices(today, count=10):
    start, _end = K.period_for(today)
    out = []
    for _ in range(count):
        s, e = K.period_for(start)
        out.append((s, e, K.period_label(s, e)))
        start = K.previous_period(s)[0]
    return out


def _back(start):
    return redirect(url_for('admin.kansas_tax', start=start.isoformat()))


@admin_bp.route('/operations/kansas-tax')
@admin_required
def kansas_tax():
    L.sync_all()
    today = L.kc_today()
    K.ensure_defaults()
    start = _start_param() or _default_start(today)
    start, end = K.period_for(start)
    filing = K.get_filing(start, end, create=False)
    live = K.build_report(start, end)
    snapshot = None
    if filing is not None and filing.return_filed_on and filing.snapshot_json:
        try:
            snapshot = json.loads(filing.snapshot_json)
        except ValueError:
            snapshot = None
    show_live = request.args.get('live') == '1'
    report = live
    changed = False
    if snapshot and not show_live:
        report = dict(live, rows=snapshot['rows'], line_m=snapshot['line_m'], exempt=snapshot['exempt'],
                      totals=snapshot['totals'], review=[])
        changed = snapshot['totals'] != live['totals'] or snapshot['line_m']['amount'] != live['line_m']['amount']
    status = K.status_of(filing, end, today)
    if request.args.get('format') == 'csv':
        return _csv(report, live, start, end)
    freq = K.frequency()
    prev_start, prev_end = K.previous_period(start, freq)
    next_start = K.next_period_start(end)
    return render_template(
        'admin/books/kansas_tax.html', start=start, end=end, label=K.period_label(start, end, freq), filing=filing,
        report=report, live=live, status=status, snapshot=snapshot, changed=changed, show_live=show_live,
        choices=_period_choices(today), prev_start=prev_start, next_start=next_start if next_start <= today else None,
        frequency=freq, frequencies=K.FREQUENCIES, reminder_days=', '.join(str(d) for d in K.reminder_days()),
        jurisdictions=K.jurisdictions(), home=K.pickup_code(), money=L.dollars, pretty=K.pretty, long_day=K.long_day,
        today=today, default_due=K.computed_due_date(end))


def _csv(report, live, start, end):
    out = StringIO()
    w = csv.writer(out)
    w.writerow(['Kansas sales tax', f'{start.isoformat()} to {end.isoformat()}'])
    w.writerow([])
    w.writerow(['Part III: Jurisdiction details'])
    w.writerow(['Code', 'Place', 'Gross sales', 'Refunds', 'Deductions', 'Net taxable sales', 'Rate %', 'Calculated tax', 'Tax collected'])
    for r in report['rows']:
        w.writerow([r['code'], r['name'], f"{r['gross'] / 100:.2f}", f"{r['refunds'] / 100:.2f}", f"{r['deductions'] / 100:.2f}",
                    f"{r['net'] / 100:.2f}", f"{r['rate']:g}", f"{r['calc'] / 100:.2f}", f"{r['collected'] / 100:.2f}"])
    t = report['totals']
    w.writerow(['Total', '', f"{t['gross'] / 100:.2f}", f"{t['refunds'] / 100:.2f}", f"{t['deductions'] / 100:.2f}",
                f"{t['net'] / 100:.2f}", '', f"{t['calc'] / 100:.2f}", f"{t['collected'] / 100:.2f}"])
    w.writerow([])
    w.writerow(['Part II: Deductions'])
    w.writerow(['Line M, out-of-state deliveries', f"{report['line_m']['amount'] / 100:.2f}"])
    w.writerow(['Tax-exempt customers', f"{report['exempt']['amount'] / 100:.2f}"])
    w.writerow([])
    w.writerow(['Part I: Tax due'])
    w.writerow(['Calculated tax', f"{t['calc'] / 100:.2f}"])
    w.writerow(['Tax collected', f"{t['collected'] / 100:.2f}"])
    w.writerow(['Difference', f"{t['diff'] / 100:.2f}"])
    w.writerow([])
    w.writerow(['Supporting detail'])
    w.writerow(['Date', 'Record', 'Code', 'Sales', 'Discounts', 'Refunds', 'Deduction', 'Deduction line', 'Tax collected'])
    for d in live['detail']:
        w.writerow([d['kc_date'].isoformat(), d['label'], d['code'], f"{d['sales'] / 100:.2f}", f"{d['discounts'] / 100:.2f}",
                    f"{d['refunds'] / 100:.2f}", f"{d['deduction'] / 100:.2f}", d['deduction_line'] or '', f"{d['tax'] / 100:.2f}"])
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="kansas-sales-tax-{start.isoformat()}.csv"'})


@admin_bp.route('/operations/kansas-tax/save', methods=['POST'])
@admin_required
def kansas_tax_save():
    start = K.parse_date(request.form.get('start'))
    start, end = K.period_for(start)
    filing = K.get_filing(start, end)
    action = request.form.get('action')
    try:
        if action == 'zero':
            filing.zero_activity_confirmed = request.form.get('zero') == '1'
            flash('Saved. A return with no sales is still filed.' if filing.zero_activity_confirmed else 'Zero activity unchecked.', 'success')
        elif action == 'due':
            filing.due_override = K.parse_date(request.form.get('due_override'))
            flash('Due date saved.' if filing.due_override else 'Back to the date Kansas rules give.', 'success')
        elif action == 'filing':
            filing.return_filed_on = K.parse_date(request.form.get('return_filed_on'))
            filing.confirmation_number = (request.form.get('confirmation_number') or '').strip()[:60] or None
            filing.tax_cents = K.parse_cents(request.form.get('tax'))
            filing.penalty_cents = K.parse_cents(request.form.get('penalty'))
            filing.interest_cents = K.parse_cents(request.form.get('interest'))
            filing.total_paid_cents = K.parse_cents(request.form.get('total_paid'))
            status = request.form.get('payment_status')
            filing.payment_status = status if status in ('unpaid', 'scheduled', 'paid') else 'unpaid'
            filing.payment_settles_on = K.parse_date(request.form.get('payment_settles_on'))
            filing.payment_verified_on = L.kc_today() if filing.payment_status == 'paid' else None
            filing.notes = (request.form.get('notes') or '').strip() or None
            if filing.return_filed_on and not filing.snapshot_json:
                filing.snapshot_json = K.snapshot_of(K.build_report(start, end))
                filing.snapshot_at = datetime.utcnow()
                flash('Filing saved, and a copy of what you submitted is kept.', 'success')
            elif not filing.return_filed_on:
                filing.snapshot_json, filing.snapshot_at = None, None
                flash('Saved. The return is not marked filed.', 'success')
            else:
                flash('Saved.', 'success')
        else:
            flash('Nothing to save.', 'error')
    except ValueError:
        db.session.rollback()
        flash('One of the dates or amounts was not readable. Dates look like 2026-10-25 and amounts like 86.30.', 'error')
        return _back(start)
    db.session.commit()
    return _back(start)


@admin_bp.route('/operations/kansas-tax/assign', methods=['POST'])
@admin_required
def kansas_tax_assign():
    start = K.parse_date(request.form.get('start')) or L.kc_today()
    order = db.session.get(Order, request.form.get('order_id', type=int) or 0)
    code = (request.form.get('code') or '').strip().upper()
    if order is None or code not in K.jurisdiction_map():
        flash('Pick one of your jurisdiction codes.', 'error')
        return _back(start)
    order.ks_code = code
    db.session.commit()
    flash(f'Order {order.order_number} will be reported under {code}.', 'success')
    return _back(start)


@admin_bp.route('/operations/kansas-tax/jurisdiction', methods=['POST'])
@admin_required
def kansas_tax_jurisdiction():
    start = K.parse_date(request.form.get('start')) or L.kc_today()
    try:
        row = K.save_jurisdiction(request.form.get('code'), request.form.get('name'), request.form.get('rate'))
        flash(f'{row.code} saved at {row.rate_percent:g}%.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return _back(start)


@admin_bp.route('/operations/kansas-tax/settings', methods=['POST'])
@admin_required
def kansas_tax_settings():
    start = K.parse_date(request.form.get('start')) or L.kc_today()
    try:
        K.save_frequency(request.form.get('frequency') or 'quarterly')
        K.save_reminder_days(request.form.get('reminder_days'))
        code = (request.form.get('pickup_code') or '').strip().upper()
        if code in K.jurisdiction_map():
            from utils.site_settings import set_setting
            set_setting('ks_pickup_code', code, 'Jurisdiction code for pickups in Shawnee')
            from utils import sales_tax
            sales_tax.clear_cache()
        flash('Saved.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return _back(start)
