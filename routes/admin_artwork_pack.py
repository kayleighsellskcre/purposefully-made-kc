"""Admin: add a finished artwork pack (a folder with design-manifest.json and the PNGs) to one group order."""
from flask import abort, jsonify, render_template, request
from flask_login import current_user

from models import Collection, db
from routes.admin import admin_bp, admin_required
from utils import artwork_pack as AP


@admin_bp.route('/collections/<int:collection_id>/artwork-pack')
@admin_required
def artwork_pack(collection_id):
    return render_template('admin/artwork_pack.html', collection=Collection.query.get_or_404(collection_id), headings=AP.HEADINGS)


@admin_bp.route('/collections/<int:collection_id>/artwork-pack/item', methods=['POST'])
@admin_required
def artwork_pack_item(collection_id):
    """One picture of the pack per request (the whole pack is bigger than one upload may be).
    ``dry_run=1`` only reports what would happen."""
    collection = Collection.query.get_or_404(collection_id)
    entry = {k: request.form.get(k, '') for k in ('design_id', 'name', 'category', 'sha256')}
    picture = request.files.get('file')
    if not entry['design_id']:
        abort(400)
    try:
        result = AP.add_entry(collection, entry, picture, current_user, dry_run=request.form.get('dry_run') == '1')
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'status': 'problem', 'name': entry['name'], 'reason': 'something went wrong saving it'}), 500
    return jsonify(result)
