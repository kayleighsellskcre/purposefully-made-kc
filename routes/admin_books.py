"""Admin: Reports (profit and loss), the Ledger, Expenses and owner money.

These pages hang off the admin blueprint, so the same sign-in and admin-only locks apply as everywhere else in /admin.
"""
import csv
import os
from io import StringIO

from flask import Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import Expense, LedgerEntry, Payout, db
from routes.admin import admin_bp, admin_required
from utils import ledger as L

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
