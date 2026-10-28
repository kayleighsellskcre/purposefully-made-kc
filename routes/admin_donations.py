"""Admin: Donations (shirts given away, such as a school silent auction). Linked from Group Orders.

Each winner gets their own private link; when they choose, a free order is made and its cost is booked as a donation.
"""
import json

from flask import abort, flash, redirect, render_template, request, url_for

from models import Collection, Donation, DonationClaim, db
from routes.admin import admin_bp, admin_required
from utils import donations as D
from utils import ledger as L


def _claim_link(claim):
    return request.url_root.rstrip('/') + url_for('donations.claim', token=claim.token)


@admin_bp.route('/donations', methods=['GET', 'POST'])
@admin_required
def donations():
    if request.method == 'POST':
        try:
            donation = D.create_donation(
                recipient=request.form.get('recipient'), occasion=request.form.get('occasion'),
                donated_on=L.parse_day(request.form.get('donated_on')), winners=request.form.get('winners', type=int),
                collection_id=request.form.get('collection_id', type=int),
                product_ids=[int(i) for i in request.form.getlist('product_id') if i.isdigit()],
                note=request.form.get('note'))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return redirect(url_for('admin.donations'))
        flash('Donation saved. Add your winners below and send each their link.', 'success')
        return redirect(url_for('admin.donation_view', donation_id=donation.id))
    rows = []
    for d in Donation.query.order_by(Donation.donated_on.desc(), Donation.id.desc()).all():
        cost, count, estimate = D.cost_so_far(d)
        rows.append({'donation': d, 'chosen': count, 'cost': cost, 'estimate': estimate})
    collections = Collection.query.order_by(Collection.name).all()
    return render_template('admin/donations/index.html', rows=rows, collections=collections, tees=D.tee_products(),
                           today=L.kc_today().isoformat())


@admin_bp.route('/donations/<int:donation_id>')
@admin_required
def donation_view(donation_id):
    donation = db.session.get(Donation, donation_id) or abort(404)
    cost, count, estimate = D.cost_so_far(donation)
    chosen = set(D._ids(donation.design_ids))
    designs = D.group_designs(donation.collection)
    return render_template('admin/donations/view.html', donation=donation, links={c.id: _claim_link(c) for c in donation.claims},
                           products=D.available_products(donation), designs=designs, chosen=chosen, cost=cost, count=count,
                           estimate=estimate)


@admin_bp.route('/donations/<int:donation_id>/winner', methods=['POST'])
@admin_required
def donation_winner(donation_id):
    donation = db.session.get(Donation, donation_id) or abort(404)
    if request.form.get('action') == 'add':
        db.session.add(DonationClaim(donation_id=donation.id, token=D.new_token()))
        donation.winners_expected = (donation.winners_expected or 0) + 1
    else:
        claim = db.session.get(DonationClaim, request.form.get('claim_id', type=int) or 0)
        if claim is None or claim.donation_id != donation.id:
            abort(404)
        claim.winner_name = ' '.join((request.form.get('winner_name') or '').split())[:120] or None
        claim.winner_email = (request.form.get('winner_email') or '').strip()[:120] or None
    db.session.commit()
    return redirect(url_for('admin.donation_view', donation_id=donation.id))


@admin_bp.route('/donations/<int:donation_id>/designs', methods=['POST'])
@admin_required
def donation_designs(donation_id):
    donation = db.session.get(Donation, donation_id) or abort(404)
    ids = [int(i) for i in request.form.getlist('design_id') if i.isdigit()]
    donation.design_ids = json.dumps(ids)
    db.session.commit()
    flash('Saved. Winners can choose from the designs you ticked.', 'success')
    return redirect(url_for('admin.donation_view', donation_id=donation.id))

