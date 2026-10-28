"""Take a vote: /vote/new makes one from your own pictures, /vote/<token> is the link you send, results are only for you.

  GET/POST /vote/new                  make a vote (signed in)
  GET/POST /vote/<token>              the page voters see; POST submits one vote
  GET      /vote/<token>/qr.png       its QR code
  GET      /vote/<token>/results      who picked what (the maker only)
  POST     /vote/<token>/toggle       close or reopen it (the maker only)
  GET      /vote/<token>/results.csv  download results (the maker only)
  GET      /account/votes             your votes
"""
from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import VotePoll, db
from utils import votes as V
from utils.cloud_storage import store_upload

votes_bp = Blueprint('votes', __name__)


def _link(poll):
    return request.url_root.rstrip('/') + url_for('votes.view', token=poll.token)


def _mine_or_404(token):
    poll = V.get_poll(token)
    if poll is None or not (poll.user_id == current_user.id or getattr(current_user, 'is_admin', False)):
        abort(404)
    return poll


@votes_bp.route('/vote/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        files = [f for f in request.files.getlist('pictures') if f and f.filename]
        error = None
        if not title:
            error = 'Give your vote a name so people know what they are picking.'
        elif len(files) < V.MIN_PICTURES:
            error = 'Add at least two pictures to vote on.'
        elif len(files) > V.MAX_PICTURES:
            error = f'Please add no more than {V.MAX_PICTURES} pictures.'
        elif not all(V.is_picture(f) for f in files):
            error = 'Pictures need to be PNG, JPG, WEBP or GIF files.'
        if error:
            flash(error, 'error')
            return render_template('vote/new.html', title=title, note=request.form.get('note', '')), 400
        urls = [store_upload(f, 'votes', 'vote') for f in files]
        poll = V.create_poll(current_user, title, request.form.get('note'), urls)
        return redirect(url_for('votes.results', token=poll.token, made=1))
    return render_template('vote/new.html', title='', note='')


@votes_bp.route('/vote/<token>', methods=['GET', 'POST'])
def view(token):
    poll = V.get_poll(token)
    if poll is None:
        abort(404)
    if request.method == 'POST':
        response, error = V.submit(poll, request.form.get('voter_name'), request.form.getlist('pick'))
        if error:
            flash(error, 'error')
            return render_template('vote/view.html', poll=poll, name=request.form.get('voter_name', ''),
                                   picked={str(x) for x in request.form.getlist('pick')}, sent=False), 400
        return redirect(url_for('votes.view', token=poll.token, sent=1))
    return render_template('vote/view.html', poll=poll, name='', picked=set(), sent=bool(request.args.get('sent')))


@votes_bp.route('/vote/<token>/qr.png')
def qr(token):
    poll = V.get_poll(token)
    if poll is None:
        abort(404)
    from utils.invoice_pay import qr_png
    return Response(qr_png(_link(poll)), mimetype='image/png',
                    headers={'Content-Disposition': 'inline; filename="vote-qr.png"'})


@votes_bp.route('/vote/<token>/results')
@login_required
def results(token):
    poll = _mine_or_404(token)
    return render_template('vote/results.html', poll=poll, link=_link(poll), rows=V.tally(poll), made=bool(request.args.get('made')))


@votes_bp.route('/vote/<token>/toggle', methods=['POST'])
@login_required
def toggle(token):
    poll = _mine_or_404(token)
    poll.is_open = not poll.is_open
    db.session.commit()
    return redirect(url_for('votes.results', token=poll.token))


@votes_bp.route('/vote/<token>/results.csv')
@login_required
def download(token):
    poll = _mine_or_404(token)
    return Response(V.csv_text(poll), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="vote-results.csv"'})


@votes_bp.route('/account/votes')
@login_required
def mine():
    polls = VotePoll.query.filter_by(user_id=current_user.id).order_by(VotePoll.created_at.desc()).all()
    return render_template('vote/mine.html', polls=polls)
