"""Admin: School District stores.

One screen sets up a whole district (schools by level, each with its stores); another manages it.
These pages hang off the admin blueprint, so the same admin-only lock applies as everywhere in /admin.
"""
from flask import Response, abort, flash, redirect, render_template, request, url_for

from models import District, Organization, db
from routes.admin import admin_bp, admin_required
from utils import districts as DS


def _fail(exc):
    db.session.rollback()
    flash(str(exc), 'error')


def _lines(text):
    return [ln.strip() for ln in (text or '').splitlines() if ln.strip()]


def _parse_schools(form):
    """[(name, level, [store names], settings)] from the three level boxes.

    A line is ``School name | Mascot | Football, Volleyball``. The mascot and the stores are optional;
    a line with no stores gets the "every school" list.
    """
    common = [s.strip() for s in (form.get('common_stores') or '').replace('\n', ',').split(',') if s.strip()]
    out, seen = [], set()
    for level, _heading in DS.LEVELS:
        for line in _lines(form.get(f'schools_{level}')):
            bits = [b.strip() for b in line.split('|')]
            name = bits[0]
            if not name or (name.lower(), level) in seen:
                continue
            seen.add((name.lower(), level))
            mascot = bits[1] if len(bits) > 1 and bits[1] else None
            own = [s.strip() for s in bits[2].split(',') if s.strip()] if len(bits) > 2 else None
            stores = list(own if own else common)
            if form.get('add_staff') and DS.STAFF_LABEL.lower() not in {s.lower() for s in stores}:
                stores.append(DS.STAFF_LABEL)
            out.append((name, level, stores, {'mascot': mascot} if mascot else {}))
    return out


@admin_bp.route('/districts')
@admin_required
def districts():
    rows = []
    for d in District.query.order_by(District.name).all():
        schools = d.schools.all()
        rows.append({'district': d, 'schools': len(schools), 'stores': sum(len(DS.stores_of(s, True)) for s in schools),
                     'live': sum(len(DS.live_stores(s)) for s in schools)})
    return render_template('admin/districts/index.html', rows=rows)


@admin_bp.route('/districts/new', methods=['GET', 'POST'])
@admin_required
def district_new():
    if request.method == 'POST':
        try:
            schools = _parse_schools(request.form)
            if not schools:
                raise DS.DistrictError('Add at least one school, one per line.')
            d = DS.set_up_district(request.form.get('name'), schools, description=request.form.get('description'),
                                   opens=request.form.get('opens'), deadline=request.form.get('deadline'))
            db.session.commit()
            flash(f'{d.name} is set up with {len(schools)} schools. Each one has a School Spirit store. '
                  'Open a store to add its products.', 'success')
            return redirect(url_for('admin.district_manage', district_id=d.id))
        except DS.DistrictError as exc:
            _fail(exc)
    return render_template('admin/districts/new.html', levels=DS.LEVELS, form=request.form)


@admin_bp.route('/districts/<int:district_id>', methods=['GET', 'POST'])
@admin_required
def district_manage(district_id):
    d = db.session.get(District, district_id) or abort(404)
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'save':
                d.name = (request.form.get('name') or d.name).strip()[:200]      # the links never change on rename
                d.description = (request.form.get('description') or '').strip() or None
                d.order_opens_at = DS._parse_dt(request.form.get('opens'))
                d.order_deadline = DS._parse_dt(request.form.get('deadline'))
                from routes.org import _store_upload
                logo = _store_upload(request.files.get('logo'), 'org-logos')
                if logo:
                    d.logo_url = logo
                flash('Saved.', 'success')
            elif action == 'push_window':
                n = DS.push_deadline(d, request.form.get('deadline') or d.order_deadline,
                                     request.form.get('opens') or d.order_opens_at)
                d.order_deadline = DS._parse_dt(request.form.get('deadline')) or d.order_deadline
                flash(f'The ordering window was applied to {n} stores.', 'success')
            elif action == 'add_school':
                school = DS.add_school(d, request.form.get('name'), request.form.get('level'),
                                       mascot=request.form.get('mascot'))
                for label in [s.strip() for s in (request.form.get('stores') or '').split(',') if s.strip()]:
                    DS.add_store(school, label, kind='staff' if label.lower() == 'staff' else 'sport')
                flash(f'{school.name} was added with a School Spirit store.', 'success')
            elif action == 'add_store':
                school = Organization.query.filter_by(id=request.form.get('school_id', type=int), district_id=d.id).first() or abort(404)
                label = request.form.get('label')
                DS.add_store(school, label, kind='staff' if (label or '').strip().lower() == 'staff' else 'sport')
                flash(f'{label.strip()} was added to {school.name}.', 'success')
            db.session.commit()
        except DS.DistrictError as exc:
            _fail(exc)
        return redirect(url_for('admin.district_manage', district_id=d.id))
    levels = [(k, h, [s for s in d.schools.all() if s.level == k]) for k, h in DS.LEVELS]
    levels = [lv for lv in levels if lv[2]]
    stores = {s.id: DS.stores_of(s, include_inactive=True) for _k, _h, schools in levels for s in schools}
    return render_template('admin/districts/manage.html', district=d, levels=levels, stores=stores, DS=DS,
                           share=DS.share_info(d), blank_scope=f'd:{d.id}')


@admin_bp.route('/districts/school/<int:school_id>', methods=['GET', 'POST'])
@admin_required
def district_school(school_id):
    school = db.session.get(Organization, school_id)
    if school is None or not school.district_id:
        abort(404)
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'save':
                name = (request.form.get('name') or '').strip()
                if name:
                    school.name = name[:200]                  # the links never change on rename
                DS.apply_school_settings(school, request.form)
                level = request.form.get('level')
                if level in DS.LEVEL_KEYS:
                    school.level = level
                from routes.org import _store_upload
                logo = _store_upload(request.files.get('logo'), 'org-logos')
                if logo:
                    school.logo_url = logo
                DS.sync_school_delivery(school)
                flash('Saved.', 'success')
            elif action == 'push_window':
                n = DS.push_deadline(school, request.form.get('deadline'), request.form.get('opens'))
                flash(f'The ordering window was applied to {n} stores.', 'success')
            elif action == 'fundraiser_paid':
                from decimal import Decimal, InvalidOperation
                try:
                    cents = int((Decimal(request.form.get('amount') or '0') * 100).to_integral_value())
                except InvalidOperation:
                    raise DS.DistrictError('Type the amount as a number, like 25 or 25.50.')
                school.fundraiser_paid_cents = max(0, (school.fundraiser_paid_cents or 0) + cents)
                flash('Payment recorded.', 'success')
            elif action == 'tax':
                school.tax_exempt = bool(request.form.get('tax_exempt'))
                school.tax_cert_number = (request.form.get('tax_cert_number') or '').strip()[:80] or None
                school.tax_expires_on = _date(request.form.get('tax_expires_on'))
                from routes.admin_books import _save_receipt
                url, problem = _save_receipt(request.files.get('certificate'))
                if problem:
                    flash(problem.replace('receipt', 'certificate'), 'info')
                if url:
                    school.tax_cert_url = url
                if school.tax_exempt and not (school.tax_cert_url or school.tax_cert_number):
                    flash('Saved, but there is no certificate on file yet. Kansas expects one for every exempt sale.', 'info')
                else:
                    flash('Saved.', 'success')
            db.session.commit()
        except DS.DistrictError as exc:
            _fail(exc)
        return redirect(url_for('admin.district_school', school_id=school.id))
    return render_template('admin/districts/school.html', school=school, district=school.district,
                           stores=DS.stores_of(school, include_inactive=True), DS=DS, share=DS.share_info(school),
                           report=DS.school_report(school), exempt=DS.school_exempt(school),
                           blank_scope=f's:{school.id}')


def _date(value):
    from datetime import datetime
    try:
        return datetime.strptime((value or '').strip(), '%Y-%m-%d').date() if (value or '').strip() else None
    except ValueError:
        raise DS.DistrictError('Dates look like 2026-11-15.')


@admin_bp.route('/districts/store/<int:store_id>/copy', methods=['GET', 'POST'])
@admin_required
def district_copy_store(store_id):
    from models import Collection
    store = db.session.get(Collection, store_id) or abort(404)
    source_school = DS.school_for_store(store) or abort(404)
    d = source_school.district
    if request.method == 'POST':
        ids = [int(i) for i in request.form.getlist('school_id') if i.isdigit()]
        ids = [i for i in ids if i != source_school.id]
        if not ids:
            flash('Pick at least one school to copy to.', 'error')
        else:
            try:
                created, updated = DS.copy_store_to_schools(store, ids)
                db.session.commit()
                flash(f'{DS.store_label(store)} was copied to {len(ids)} schools: {created} new, {updated} updated.', 'success')
                return redirect(url_for('admin.district_manage', district_id=d.id))
            except DS.DistrictError as exc:
                _fail(exc)
    levels = [(k, h, [s for s in d.schools.all() if s.level == k and s.id != source_school.id]) for k, h in DS.LEVELS]
    return render_template('admin/districts/copy.html', store=store, label=DS.store_label(store), school=source_school,
                           district=d, levels=[lv for lv in levels if lv[2]])


@admin_bp.route('/districts/<int:district_id>/report')
@admin_required
def district_report(district_id):
    d = db.session.get(District, district_id) or abort(404)
    blanks = sorted(DS.blanks_total(d).items())
    return render_template('admin/districts/report.html', district=d, report=DS.district_report(d), blanks=blanks,
                           blank_scope=f'd:{d.id}')


@admin_bp.route('/districts/<int:district_id>/qr.zip')
@admin_required
def district_qr_zip(district_id):
    d = db.session.get(District, district_id) or abort(404)
    return _zip(DS.qr_zip(d), d.name)


@admin_bp.route('/districts/school/<int:school_id>/qr.zip')
@admin_required
def district_school_qr_zip(school_id):
    school = db.session.get(Organization, school_id)
    if school is None or not school.district_id:
        abort(404)
    return _zip(DS.qr_zip(school), school.name)


def _zip(data, name):
    return Response(data, mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{DS._file_safe(name)} QR codes.zip"'})
