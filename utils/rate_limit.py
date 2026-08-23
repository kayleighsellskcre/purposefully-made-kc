"""One way to attach a Flask-Limiter limit to a route.

routes/auth.py grew a private version of this for login, register, and password
reset. Anything that sends mail or checks a credential wants the same treatment,
so it lives here now rather than being copied per blueprint.

The limiter is created in app.py at module scope, but route modules are imported
*during* create_app(). The import is therefore done inside the decorator and
guarded: if it is not available the route is returned unchanged, so a missing
limiter degrades to no limit instead of breaking the import and taking the whole
site down with it.
"""


def rate_limit(limit_string, **kwargs):
    """Limit a view, e.g. rate_limit("5 per hour").

    Extra keyword arguments are passed to Flask-Limiter's limit(), so callers
    can use exempt_when and friends.

    Honours RATELIMIT_ENABLED, which the test config turns off, so tests are
    not flaky in the order they happen to run.
    """
    def decorator(view):
        try:
            from app import limiter
        except Exception:
            return view
        if limiter is None:
            return view
        return limiter.limit(limit_string, **kwargs)(view)
    return decorator


def post_only(limit_string):
    """Limit the submissions to a view, but never merely viewing it.

    Every form here answers both GET and POST from one route. A bare limit
    counts both, so a customer who reloads the contact page or returns to the
    sign-in form a few times gets locked out without having submitted anything.
    Only the POST is worth counting.
    """
    from flask import request

    return rate_limit(limit_string,
                      exempt_when=lambda: request.method != 'POST')
