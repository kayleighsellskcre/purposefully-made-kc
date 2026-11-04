"""Admin: The Backroom. Who holds a key, one-time key codes to hand out, and every design that gets shared."""
import secrets

from flask import flash, redirect, render_template, request, url_for
from sqlalchemy import func

from models import KeyCode, SharedDesign, User, db
from routes.admin import admin_bp, admin_required
from utils import creator_credit as CC
from utils import shared_designs as SD


@admin_bp.route('/backroom')
@admin_required
def backroom():
    keyholders = User.query.filter(User.is_keyholder.is_(True)).order_by(User.email).all()
    unused = KeyCode.query.filter(KeyCode.used_by_user_id.is_(None)).order_by(KeyCode.created_at.desc()).all()
    used = KeyCode.query.filter(KeyCode.used_by_user_id.isnot(None)).order_by(KeyCode.used_at.desc()).limit(20).all()
    users = {u.id: u for u in User.query.filter(User.id.in_([c.used_by_user_id for c in used] or [0])).all()}
    shares = []
    for s in SharedDesign.query.order_by(SharedDesign.created_at.desc()).limit(30).all():
        owner = db.session.get(User, s.user_id) if s.user_id else None
        orders, pieces = SD.results(s)
        shares.append({'share': s, 'owner': owner, 'orders': orders, 'pieces': pieces, 'earned': CC.earned_by_share(s.id)})
    return render_template('admin/operations/backroom.html', keyholders=keyholders, unused=unused, used=used, users=users,
                           shares=shares, rate=CC.rate_percent())


@admin_bp.route('/backroom/grant', methods=['POST'])
@admin_required
def backroom_grant():
    email = (request.form.get('email') or '').strip().lower()
    user = User.query.filter(func.lower(User.email) == email).first() if email else None
    if user is None:
        flash('No account with that email. Send them a key code instead, or ask them to make an account first.', 'error')
    else:
        user.is_keyholder = True
        db.session.commit()
        flash(f'{user.email} now holds a key.', 'success')
    return redirect(url_for('admin.backroom'))


@admin_bp.route('/backroom/revoke/<int:user_id>', methods=['POST'])
@admin_required
def backroom_revoke(user_id):
    user = db.session.get(User, user_id)
    if user is not None:
        user.is_keyholder = False
        db.session.commit()
        flash(f'{user.email} no longer holds a key. Credit they already earned stays theirs.', 'success')
    return redirect(url_for('admin.backroom'))


@admin_bp.route('/backroom/code', methods=['POST'])
@admin_required
def backroom_code():
    code = secrets.token_hex(5).upper()
    db.session.add(KeyCode(code=code, note=(request.form.get('note') or '').strip()[:200] or None))
    db.session.commit()
    flash(f'New key: {code[:5]}-{code[5:]}. It works once.', 'success')
    return redirect(url_for('admin.backroom'))


@admin_bp.route('/backroom/code/<int:code_id>/delete', methods=['POST'])
@admin_required
def backroom_code_delete(code_id):
    row = db.session.get(KeyCode, code_id)
    if row is not None and not row.used_by_user_id:
        db.session.delete(row)
        db.session.commit()
    return redirect(url_for('admin.backroom'))
