"""Share a design: /made/<token> opens exactly what a customer made, and /account/shared-designs lists their links.

  POST /made/share/cart/<index>        make a link from a cart item
  POST /made/share/order-item/<id>     make a link from something they ordered before
  GET  /made/<token>                   the shared design: pick a size, add it to the cart
  GET  /made/<token>/qr.png            its QR code
"""
from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import OrderItem, SharedDesign, db
from utils import shared_designs as SD
from utils.cart_store import cart_count, get_cart, save_cart

made_bp = Blueprint('made', __name__)


def _link(share):
    return request.url_root.rstrip('/') + url_for('made.view', token=share.token)


def _reply(share, message):
    if share is None:
        return jsonify({'success': False, 'message': message}), 400
    return jsonify({'success': True, 'url': _link(share), 'qr': url_for('made.qr', token=share.token),
                    'title': share.title})


def _user():
    return current_user if getattr(current_user, 'is_authenticated', False) else None


@made_bp.route('/made/share/cart/<int:index>', methods=['POST'])
def share_from_cart(index):
    cart = get_cart()
    if index < 0 or index >= len(cart):
        return _reply(None, 'That item is no longer in your cart.')
    return _reply(*SD.share_line(cart[index], _user()))


@made_bp.route('/made/share/order-item/<int:item_id>', methods=['POST'])
@login_required
def share_from_order_item(item_id):
    from utils.reorder import _line_from
    item = db.session.get(OrderItem, item_id)
    if item is None or item.order is None or item.order.user_id != current_user.id:
        abort(404)
    line, reason = _line_from(item)
    if line is None:
        return _reply(None, f'This design cannot be shared right now: {reason}.')
    return _reply(*SD.share_line(line, current_user))


@made_bp.route('/made/<token>')
def view(token):
    share = SD.get_active(token)
    if share is None:
        abort(404)
    share.views = (share.views or 0) + 1
    db.session.commit()
    from models import Product
    from utils.order_artwork import existing_image_url, mockup_urls
    product = db.session.get(Product, share.line.get('product_id') or 0)
    sizes, unavailable = SD.sizes_with_prices(share)
    front, _back = mockup_urls(product, share.line.get('color')) if product else (None, None)
    image = existing_image_url(share.line.get('proof_front_url') or share.line.get('proof_image')) or front
    return render_template('made/view.html', share=share, product=product, sizes=sizes, unavailable=unavailable,
                           image=image, qr=url_for('made.qr', token=share.token), link=_link(share))


@made_bp.route('/made/<token>/add', methods=['POST'])
def add(token):
    share = SD.get_active(token)
    if share is None:
        abort(404)
    line, reason = SD.line_for(share, request.form.get('size'), request.form.get('quantity', 1, type=int))
    if line is None:
        from flask import flash
        flash(f'Sorry, this cannot be ordered right now: {reason}.', 'error')
        return redirect(url_for('made.view', token=token))
    from utils.reorder import merge_lines
    cart = get_cart()
    _added, note = merge_lines(cart, [line])
    save_cart(cart)
    if note:
        from flask import flash
        flash(note, 'info')
    return redirect(url_for('cart.index'))


@made_bp.route('/made/<token>/qr.png')
def qr(token):
    share = SD.get_active(token)
    if share is None:
        abort(404)
    from utils.invoice_pay import qr_png
    data = qr_png(_link(share))
    disposition = 'attachment' if request.args.get('download') else 'inline'
    return Response(data, mimetype='image/png',
                    headers={'Content-Disposition': f'{disposition}; filename="shared-design-qr.png"'})


@made_bp.route('/account/shared-designs')
@login_required
def mine():
    shares = SharedDesign.query.filter_by(user_id=current_user.id).order_by(SharedDesign.created_at.desc()).all()
    rows = []
    for s in shares:
        orders, pieces = SD.results(s)
        rows.append({'share': s, 'link': _link(s), 'orders': orders, 'pieces': pieces})
    return render_template('account/shared_designs.html', rows=rows)


@made_bp.route('/account/shared-designs/<int:share_id>/toggle', methods=['POST'])
@login_required
def toggle(share_id):
    share = SharedDesign.query.filter_by(id=share_id, user_id=current_user.id).first_or_404()
    share.is_active = not share.is_active
    db.session.commit()
    return redirect(url_for('made.mine'))
