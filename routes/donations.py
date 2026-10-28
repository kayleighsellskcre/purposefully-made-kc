"""A winner's private link: /gift/<token> lets them pick a color, design and size for a donated shirt."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from utils import donations as D
from utils.json_fields import parse_json_list
from utils.sizes import sort_sizes

donations_bp = Blueprint('donations', __name__)


def _choices(donation):
    out = []
    for p in D.available_products(donation):
        out.append({'product': p, 'colors': D.colors_for(donation, p), 'sizes': sort_sizes(parse_json_list(p.available_sizes))})
    return out


@donations_bp.route('/gift/<token>', methods=['GET', 'POST'])
def claim(token):
    claim = D.get_claim(token)
    if claim is None:
        abort(404)
    donation = claim.donation
    if claim.order_id:
        return render_template('gift/thanks.html', claim=claim, donation=donation)
    if request.method == 'POST':
        order, error = D.place_claim(claim, request.form)
        if error:
            flash(error, 'error')
            return render_template('gift/claim.html', claim=claim, donation=donation, choices=_choices(donation),
                                   designs=D.available_designs(donation), form=request.form), 400
        try:
            from routes.checkout import queue_order_confirmation_email
            queue_order_confirmation_email(order.id)
        except Exception:
            current_app.logger.exception('donation order %s: confirmation email not queued', order.id)
        return redirect(url_for('donations.claim', token=claim.token))
    return render_template('gift/claim.html', claim=claim, donation=donation, choices=_choices(donation),
                           designs=D.available_designs(donation), form={})
