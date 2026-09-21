from functools import wraps
from flask import abort
from flask_login import current_user


def require_admin_or_404(f):
    """Gate an internal/diagnostic route to logged-in admins.

    Anonymous visitors get a 404, not a login redirect, so the route doesn't
    advertise its own existence. Logged-in non-admins get a 403.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(404)
        if not getattr(current_user, 'is_admin', False):
            abort(403)
        return f(*args, **kwargs)
    return decorated
