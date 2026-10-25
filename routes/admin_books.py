"""Admin: Reports (profit and loss), the Ledger, Expenses and owner money.

These pages hang off the admin blueprint, so the same sign-in and admin-only locks apply as everywhere else in /admin.
"""
import csv
import os
from io import StringIO

from flask import Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import Expense, LedgerEntry, Payout, RecurringExpense, db
from routes.admin import admin_bp, admin_required
from utils import ledger as L
from utils import year_end as Y

_RECEIPT_TYPES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.pdf'}
_RECEIPT_MAX = 10 * 1024 * 1024


def _period():
    period = request.args.get('period') or 'this_month'
    start, end = L.parse_day(request.args.get('from')), L.parse_day(request.args.get('to'))
    first, last, label = L.resolve_period(period, year=request.args.get('year', type=int), start=start, end=end)
    return period, first, last, label


def _business():
    from utils.business_info import BUSINESS
    return BUSINESS


def _drill(p, **kw):
    """The Ledger link that lists the entries behind a number on a report."""
    return url_for('admin.ledger', **{'from': p['start'].isoformat(), 'to': p['end'].isoformat()}, **kw)


@admin_bp.route('/operations/reports')
@admin_required
def reports():
    L.sync_all()
    period, first, last, label = _period()
    p = L.pnl(first, last)
    year = request.args.get('year', type=int) or last.year
    links = {
        'gross_sales': _drill(p, type='sale,shipping'), 'discounts': _drill(p, type='discount'),
        'refunds': _drill(p, type='refund'), 'cogs': _drill(p, type='cogs'),
        'other_income': _drill(p, type='other_income'), 'tax': _drill(p, type='sales_tax,refund_tax'),
        'draws': _drill(p, type='owner_draw'), 'contributions': _drill(p, type='owner_contribution'),
        'expenses': {name: _drill(p, type='expense,processing_fee', category=name) for name, _c in p['expenses']},
    }
    months = L.monthly(year)
    keys = ('net_sales', 'cogs', 'gross_profit', 'total_expenses', 'net_profit', 'tax_collected')
    totals = {k: sum(mp[k] for _m, mp in months) for k in keys}
    chart_max = max([1] + [mp['net_sales'] for _m, mp in months])
    return render_template(
        'admin/books/reports.html', p=p, label=label, totals=totals, chart_max=chart_max, period=period, periods=L.PERIODS, first=first, last=last, year=year,
        years=list(range(L.kc_today().year, L.kc_today().year - 6, -1)), links=links,
        months=months, channels=L.sales_by_channel(first, last), estimates=L.estimate_counts(), money=L.dollars,
        query={'period': period, 'year': year, 'from': first.isoformat(), 'to': last.isoformat()})


@admin_bp.route('/operations/reports/refresh', methods=['POST'])
@admin_required
def reports_refresh():
    added = L.sync_all(force=True)
    flash(f'Books refreshed. {added} new entr{"y" if added == 1 else "ies"} added.' if added else 'Books are already up to date.', 'success')
    return redirect(request.referrer or url_for('admin.reports'))


@admin_bp.route('/operations/reports/close-email', methods=['POST'])
@admin_required
def reports_close_email():
    """Email last month's close to the owner right now (it also goes out by itself on the 2nd)."""
    from utils import monthly_close
    if monthly_close.send_close(force=True):
        flash('The monthly close was emailed to you.', 'success')
    else:
        flash('The email could not be sent. Please check your email settings.', 'error')
    return redirect(request.referrer or url_for('admin.reports'))


@admin_bp.route('/operations/reports/fees', methods=['POST'])
@admin_required
def reports_fetch_fees():
    from utils.background import run_in_background
    from utils.money_events import fetch_real_fees
    run_in_background(current_app._get_current_object(), fetch_real_fees, 40)
    flash('Asking Stripe and PayPal for the real fees. Refresh this page in a minute to see them.', 'info')
    return redirect(request.referrer or url_for('admin.reports'))


@admin_bp.route('/operations/reports/pnl.pdf')
@admin_required
def reports_pnl_pdf():
    from utils.report_pdf import build_pnl_pdf
    L.sync_all()
    _period_key, first, last, label = _period()
    pdf = build_pnl_pdf(L.pnl(first, last), label, _business(), channels=L.sales_by_channel(first, last),
                        estimates=L.estimate_counts())
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="Profit-and-Loss-{first.isoformat()}-to-{last.isoformat()}.pdf"'})


@admin_bp.route('/operations/reports/monthly.pdf')
@admin_required
def reports_monthly_pdf():
    from utils.report_pdf import build_monthly_pdf
    L.sync_all()
    year = request.args.get('year', type=int) or L.kc_today().year
    pdf = build_monthly_pdf(year, L.monthly(year), _business())
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="Monthly-Profit-and-Loss-{year}.pdf"'})


@admin_bp.route('/operations/ledger')
@admin_required
def ledger():
    L.sync_all()
    query = LedgerEntry.query
    types = [t for t in (request.args.get('type') or '').split(',') if t]
    if types:
        query = query.filter(LedgerEntry.entry_type.in_(types))
    category = (request.args.get('category') or '').strip()
    if category:
        query = query.filter(LedgerEntry.category == category)
    start, end = L.parse_day(request.args.get('from')), L.parse_day(request.args.get('to'))
    if start:
        query = query.filter(LedgerEntry.kc_date >= start)
    if end:
        query = query.filter(LedgerEntry.kc_date <= end)
    total = query.with_entities(db.func.coalesce(db.func.sum(LedgerEntry.amount_cents), 0)).scalar()
    ordered = query.order_by(LedgerEntry.kc_date.desc(), LedgerEntry.id.desc())
    if request.args.get('format') == 'csv':
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(['Date', 'Type', 'Category', 'Amount', 'Source', 'Channel', 'Order', 'Invoice', 'Vendor', 'Estimate', 'Note'])
        for e in ordered.all():
            writer.writerow([e.kc_date.isoformat(), L.TYPE_LABELS.get(e.entry_type, e.entry_type), e.category or '',
                             f'{e.amount_cents / 100:.2f}', e.pay_source or '', e.channel or '',
                             e.order.order_number if e.order else '', e.invoice.number if e.invoice else '',
                             e.vendor or '', 'yes' if e.is_estimate else '', e.note or ''])
        return Response(out.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="ledger.csv"'})
    page = max(1, request.args.get('page', type=int) or 1)
    per = 200
    count = query.count()
    rows = ordered.offset((page - 1) * per).limit(per).all()
    args = {k: v for k, v in request.args.items() if k != 'page'}
    return render_template('admin/books/ledger.html', rows=rows, total=total, count=count, page=page, per=per,
                           args=args, labels=L.TYPE_LABELS, money=L.dollars, categories=[c for c, _l in L.EXPENSE_CATEGORIES])


def _save_receipt(file):
    if not file or not file.filename:
        return None, None
    ext = os.path.splitext(file.filename.lower())[1]
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if ext not in _RECEIPT_TYPES or size == 0 or size > _RECEIPT_MAX:
        return None, 'The receipt must be a photo or PDF under 10 MB, so it was not attached.'
    from utils.cloud_storage import store_upload
    return store_upload(file, 'receipts', 'receipt'), None


@admin_bp.route('/operations/expenses', methods=['GET', 'POST'])
@admin_required
def expenses():
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'void':
                L.void_expense(int(request.form.get('expense_id') or 0), user_id=current_user.id)
                flash('Voided. A reversing entry was added; the original stays on record.', 'success')
            elif action in ('contribution', 'draw'):
                L.add_owner_entry(L.CONTRIBUTION if action == 'contribution' else L.DRAW,
                                  when_day=L.parse_day(request.form.get('day')) or L.kc_today(),
                                  amount_dollars=request.form.get('amount'), note=request.form.get('note'),
                                  user_id=current_user.id)
                flash('Saved.', 'success')
            else:
                url, problem = _save_receipt(request.files.get('receipt'))
                if problem:
                    flash(problem, 'info')
                L.add_expense(when_day=L.parse_day(request.form.get('day')) or L.kc_today(),
                              vendor=request.form.get('vendor'), amount_dollars=request.form.get('amount'),
                              category=request.form.get('category'), payment_method=request.form.get('payment_method'),
                              note=request.form.get('note'), receipt_url=url,
                              is_equipment=bool(request.form.get('is_equipment')), user_id=current_user.id)
                flash('Expense saved.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
        return redirect(url_for('admin.expenses'))
    L.sync_all()
    year = request.args.get('year', type=int) or L.kc_today().year
    rows = (Expense.query.filter(Expense.expense_date >= L.date(year, 1, 1), Expense.expense_date <= L.date(year, 12, 31))
            .order_by(Expense.expense_date.desc(), Expense.id.desc()).all())
    owner = (LedgerEntry.query.filter(LedgerEntry.entry_type.in_([L.CONTRIBUTION, L.DRAW]))
             .order_by(LedgerEntry.kc_date.desc(), LedgerEntry.id.desc()).limit(25).all())
    total = sum(e.amount_cents for e in rows if not e.voided_at)
    missing = sum(1 for e in rows if not e.receipt_url and not e.voided_at)
    return render_template('admin/books/expenses.html', rows=rows, owner=owner, year=year, total=total, missing=missing,
                           categories=L.EXPENSE_CATEGORIES, methods=L.PAY_METHODS, today=L.kc_today().isoformat(),
                           years=list(range(L.kc_today().year, L.kc_today().year - 6, -1)), money=L.dollars)


@admin_bp.route('/operations/payouts')
@admin_required
def payouts():
    """What Stripe has sent to the bank. Each paid payout also appears in the ledger as a transfer."""
    rows = Payout.query.order_by(Payout.arrival_date.desc(), Payout.id.desc()).limit(200).all()
    paid = sum(r.amount_cents for r in rows if r.status == 'paid')
    return render_template('admin/books/payouts.html', rows=rows, paid=paid, money=L.dollars)


@admin_bp.route('/operations/sales-tax')
@admin_required
def sales_tax_report():
    from utils import sales_tax
    L.sync_all()
    period, first, last, label = _period()
    report = L.sales_tax_report(first, last)
    if request.args.get('format') == 'csv':
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(['Where taxed', 'Orders', 'Taxable sales', 'Not taxed', 'Shipping charged', 'Tax collected'])
        for r in report['rows']:
            writer.writerow([r['label'], r['orders'], f"{r['taxable'] / 100:.2f}", f"{r['not_taxed'] / 100:.2f}",
                             f"{r['shipping'] / 100:.2f}", f"{r['tax'] / 100:.2f}"])
        t = report['totals']
        writer.writerow(['Total', t['orders'], f"{t['taxable'] / 100:.2f}", f"{t['not_taxed'] / 100:.2f}",
                         f"{t['shipping'] / 100:.2f}", f"{t['tax'] / 100:.2f}"])
        return Response(out.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="sales-tax-{first.isoformat()}-to-{last.isoformat()}.csv"'})
    if request.args.get('format') == 'pdf':
        from utils.report_pdf import build_sales_tax_pdf
        pdf = build_sales_tax_pdf(report, label, _business(), sales_tax.rate_percent())
        return Response(pdf, mimetype='application/pdf',
                        headers={'Content-Disposition': f'inline; filename="Sales-Tax-{first.isoformat()}-to-{last.isoformat()}.pdf"'})
    query = {'period': period, 'from': first.isoformat(), 'to': last.isoformat(),
             'year': request.args.get('year', type=int) or last.year}
    return render_template('admin/books/sales_tax.html', report=report, label=label, period=period, periods=L.PERIODS,
                           first=first, last=last, year=query['year'],
                           years=list(range(L.kc_today().year, L.kc_today().year - 6, -1)), query=query, money=L.dollars,
                           rate=sales_tax.rate_percent())


def _year():
    year = request.args.get('year', type=int) or request.form.get('year', type=int) or L.kc_today().year
    return min(max(year, 2000), L.kc_today().year + 1)


def _years():
    return list(range(L.kc_today().year, L.kc_today().year - 6, -1))


@admin_bp.route('/operations/inventory-count', methods=['GET', 'POST'])
@admin_required
def inventory_count():
    year = _year()
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'start':
                Y.start_count(year)
                flash(f'The {year} count is started from your current stock. Adjust any line, then lock it when you are done.', 'success')
            elif action == 'update':
                Y.update_line(request.form.get('line_id'), request.form.get('quantity'), request.form.get('unit_cost'))
                flash('Saved.', 'success')
            elif action == 'add':
                count = Y.count_for(year)
                if count is None:
                    raise ValueError('Start the count first.')
                Y.add_line(count, request.form.get('kind'), request.form.get('description'), request.form.get('quantity'),
                           request.form.get('unit_cost'))
                flash('Added.', 'success')
            elif action == 'delete':
                Y.delete_line(request.form.get('line_id'))
                flash('Removed from the count.', 'success')
            elif action == 'lock':
                count = Y.count_for(year)
                if count is not None:
                    Y.lock_count(count)
                    flash(f'The {year} count is locked. It will not change.', 'success')
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc) or 'That did not save. Please check the numbers.', 'error')
        return redirect(url_for('admin.inventory_count', year=year))
    count = Y.count_for(year)
    by_kind, total = Y.count_totals(count) if count else ({}, 0)
    if request.args.get('format') == 'csv' and count:
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(['Type', 'Description', 'Quantity', 'Unit cost', 'Value at cost'])
        for line in count.lines:
            writer.writerow([Y.KIND_LABELS.get(line.kind, line.kind), line.description, line.quantity,
                             f'{line.unit_cost_cents / 100:.2f}', f'{line.value_cents / 100:.2f}'])
        writer.writerow(['Total', '', '', '', f'{total / 100:.2f}'])
        return Response(out.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="inventory-count-{year}.csv"'})
    return render_template('admin/books/inventory_count.html', year=year, years=_years(), count=count, by_kind=by_kind, total=total,
                           kinds=Y.KINDS, kind_labels=Y.KIND_LABELS, money=L.dollars)


@admin_bp.route('/operations/mileage', methods=['GET', 'POST'])
@admin_required
def mileage():
    from models import MileageFavorite, MileageTrip
    year = _year()
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            day = L.parse_day(request.form.get('day')) or L.kc_today()
            if action == 'trip':
                Y.add_trip(day, request.form.get('start'), request.form.get('destination'), request.form.get('purpose'),
                           request.form.get('miles'))
                if (request.form.get('label') or '').strip():            # also keep it as a one-tap trip
                    Y.add_favorite(request.form.get('label'), request.form.get('start'), request.form.get('destination'),
                                   request.form.get('purpose'), request.form.get('miles'))
                flash('Trip saved.', 'success')
            elif action == 'favorite':
                Y.add_favorite(request.form.get('label'), request.form.get('start'), request.form.get('destination'),
                               request.form.get('purpose'), request.form.get('miles'))
                flash('Saved. Now it is one tap.', 'success')
            elif action == 'use_favorite':
                Y.log_favorite(request.form.get('favorite_id'), day)
                flash('Trip logged.', 'success')
            elif action == 'delete_favorite':
                fav = db.session.get(MileageFavorite, int(request.form.get('favorite_id') or 0))
                if fav:
                    db.session.delete(fav)
                    db.session.commit()
            elif action == 'delete_trip':
                trip = db.session.get(MileageTrip, int(request.form.get('trip_id') or 0))
                if trip:
                    db.session.delete(trip)
                    db.session.commit()
                    flash('Trip removed.', 'success')
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc) or 'That did not save.', 'error')
        return redirect(url_for('admin.mileage', year=year))
    trips = Y.trips_in_year(year)
    return render_template('admin/books/mileage.html', year=year, years=_years(), trips=trips,
                           total_miles=Y.miles_text(sum(t.miles_tenths for t in trips)), miles_text=Y.miles_text,
                           favorites=MileageFavorite.query.order_by(MileageFavorite.label).all(), today=L.kc_today().isoformat())


@admin_bp.route('/operations/payout-check')
@admin_required
def payout_check():
    L.sync_all()
    year = _year()
    return render_template('admin/books/payout_check.html', year=year, years=_years(), summary=Y.processor_summary(year), money=L.dollars)


@admin_bp.route('/operations/cpa-package')
@admin_required
def cpa_package():
    L.sync_all()
    year = _year()
    return render_template('admin/books/cpa_package.html', year=year, years=_years(), checks=Y.package_checks(year))


@admin_bp.route('/operations/cpa-package.zip')
@admin_required
def cpa_package_zip():
    from utils.cpa_package import build_package
    L.sync_all()
    year = _year()
    data = build_package(year, current_app._get_current_object())
    return Response(data, mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="PMKC-CPA-Package-{year}.zip"'})


@admin_bp.route('/operations/recurring', methods=['GET', 'POST'])
@admin_required
def recurring_expenses():
    """Monthly bills. Each month's real expense is made automatically, once."""
    from utils import recurring
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action in ('stop', 'resume'):
                recurring.set_active(request.form.get('rule_id'), action == 'resume')
                flash('Saved. Months already made stay on your books.', 'success')
            else:
                recurring.add_rule(vendor=request.form.get('vendor'), amount_dollars=request.form.get('amount'),
                                   category=request.form.get('category'), payment_method=request.form.get('payment_method'),
                                   note=request.form.get('note'), day_of_month=request.form.get('day_of_month', type=int),
                                   start_date=L.parse_day(request.form.get('start')))
                made = recurring.make_due()
                flash(f'Saved. {made} past or current month{"s" if made != 1 else ""} added to your expenses.' if made else 'Saved.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
        return redirect(url_for('admin.recurring_expenses'))
    rules = RecurringExpense.query.order_by(RecurringExpense.active.desc(), RecurringExpense.vendor).all()
    yearly = sum(r.amount_cents * 12 for r in rules if r.active)
    return render_template('admin/books/recurring.html', rules=rules, yearly=yearly, categories=L.EXPENSE_CATEGORIES,
                           methods=L.PAY_METHODS, today=L.kc_today().isoformat(), money=L.dollars)


@admin_bp.route('/operations/equipment')
@admin_required
def equipment_log():
    """Equipment bought (heat press, printer, cutter), counted as supplies, with its receipt."""
    year = _year()
    first, last = L.date(year, 1, 1), L.date(year, 12, 31)
    rows = (Expense.query.filter(Expense.is_equipment.is_(True), Expense.expense_date >= first, Expense.expense_date <= last)
            .order_by(Expense.expense_date.desc(), Expense.id.desc()).all())
    total = sum(e.amount_cents for e in rows if not e.voided_at)
    if request.args.get('format') == 'csv':
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(['Date', 'Item', 'Cost', 'Paid with', 'Has receipt', 'Voided'])
        for e in rows:
            writer.writerow([e.expense_date.isoformat(), e.vendor or e.note or '', f'{e.amount_cents / 100:.2f}', e.payment_method or '',
                             'yes' if e.receipt_url else 'no', 'yes' if e.voided_at else ''])
        return Response(out.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="equipment-{year}.csv"'})
    return render_template('admin/books/equipment.html', rows=rows, total=total, year=year, years=_years(), money=L.dollars)


@admin_bp.route('/operations/receivables', methods=['GET', 'POST'])
@admin_required
def receivables():
    """Open invoices by age, the cash/Venmo/check payment log, and the optional customer reminders."""
    from models import InvoicePayment, ManualInvoice
    from utils import receivables as R
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'payment':
                row = R.record_payment(request.form.get('invoice_id'), request.form.get('amount'), request.form.get('method'),
                                       paid_on=L.parse_day(request.form.get('day')), note=request.form.get('note'))
                flash(f'Recorded {L.dollars(row.amount_cents)} by {row.method}. It is on your books.', 'success')
            elif action == 'remind':
                inv = db.session.get(ManualInvoice, int(request.form.get('invoice_id') or 0))
                if inv is None or not R.send_reminder(inv, max(1, R.target_stage(R.age_days(inv)))):
                    flash('The reminder could not be sent. Check that the invoice has an email address.', 'error')
                else:
                    inv.reminder_sent_at = L.datetime.utcnow()
                    db.session.commit()
                    flash(f'Reminder emailed to {inv.email}.', 'success')
            elif action == 'auto':
                R.set_reminders(request.form.get('on') == '1')
                flash('Automatic reminders are on.' if R.reminders_on() else 'Automatic reminders are off.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
        return redirect(url_for('admin.receivables'))
    L.sync_all()
    rows = R.open_rows()
    log = (InvoicePayment.query.order_by(InvoicePayment.paid_on.desc(), InvoicePayment.id.desc()).limit(50).all())
    return render_template('admin/books/receivables.html', rows=sorted(rows, key=lambda r: -r['age']), buckets=R.buckets(rows),
                           total=sum(r['balance_cents'] for r in rows), log=log, methods=R.METHODS, auto=R.reminders_on(),
                           days=R.REMINDER_DAYS, today=L.kc_today().isoformat(), money=L.dollars)
