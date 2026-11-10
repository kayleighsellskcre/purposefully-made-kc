"""Make sure an order's artwork is somewhere that survives a site update.

Files saved on the web server's own disk are erased at every deploy. A design a customer uploaded can end up there (cloud
storage was briefly unreachable, a guest upload, an older upload), and then the print file is gone by the time the order is
made. At the moment an order is created every local picture it needs is copied to cloud storage and the order keeps the
permanent address.
"""
from __future__ import annotations

from pathlib import PurePosixPath


def is_local(url):
    url = (url or '').strip()
    return bool(url) and not url.startswith(('http://', 'https://', 'data:'))


def make_durable(app, url, subfolder='designs', prefix='order'):
    """The permanent https address for ``url``, or the url unchanged when it is already permanent or cannot be copied."""
    from utils.cloud_storage import r2_configured, upload_bytes
    from utils.order_artwork import local_file_for_url
    if not is_local(url) or not r2_configured(app):
        return url
    try:
        path = local_file_for_url(app, url if url.startswith('/') else '/static/' + url.lstrip('/'))
        if path is None:
            return url                                     # already gone: nothing left to copy
        name = PurePosixPath(str(path)).name or 'artwork.png'
        stored = upload_bytes(path.read_bytes(), app, name, subfolder=subfolder, public_id_prefix=prefix)
        return stored if stored and stored.startswith('http') else url
    except Exception:
        app.logger.exception('could not copy %s to permanent storage', url)
        return url


def promote_local_files(app, days=5):
    """Move recent pictures that are still on the server's disk to permanent storage. Returns how many were moved.

    Runs every few minutes, so a file that landed on the temporary disk (cloud storage hiccup, a promotion that was cut off)
    is rescued long before the next site update erases it.
    """
    from models import CustomDesignRequest, Design, OrderItem, db
    from datetime import datetime, timedelta
    from utils.cloud_storage import r2_configured
    if not r2_configured(app):
        return 0
    moved = 0
    cutoff = datetime.utcnow() - timedelta(days=days)

    def swap(obj, field, subfolder='designs'):
        nonlocal moved
        old = getattr(obj, field, None)
        if not is_local(old):
            return
        new = make_durable(app, old, subfolder=subfolder, prefix='rescued')
        if new and new != old:
            setattr(obj, field, new)
            moved += 1

    try:
        for d in Design.query.filter(Design.uploaded_at >= cutoff, ~Design.file_path.like('http%')).limit(200).all():
            swap(d, 'file_path')
        for r in CustomDesignRequest.query.filter(~CustomDesignRequest.reference_file_path.like('http%')).limit(200).all():
            swap(r, 'reference_file_path', 'custom_requests')
        for it in OrderItem.query.filter(OrderItem.design_file_name.isnot(None), ~OrderItem.design_file_name.like('http%')).order_by(OrderItem.id.desc()).limit(200).all():
            swap(it, 'proof_image', 'proofs')
            swap(it, 'proof_back_image', 'proofs')
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('promoting local files failed')
    return moved
