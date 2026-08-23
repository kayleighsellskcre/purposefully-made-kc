"""Authentication for the Widen bulk image-import endpoints.

Two routes accept scraped SanMar media-library data and upsert product image
URLs: `POST /widen-import` and `POST /admin/import-widen`. Both deliberately
skip the login session, because the whole point is to POST cross-origin from
medialibrary1.com, and both therefore send `Access-Control-Allow-Origin: *`.

That left a shared secret string as the only thing standing between the open
internet and a write to every product's image URLs. The string was hardcoded in
both files, so it was readable by anyone with repository access and could never
be rotated without a deploy.

Two properties matter here:

Fails closed. The secret now comes from WIDEN_IMPORT_SECRET, and when that is
unset the endpoints refuse everything. There is no default value to fall back
to, because a default is how a "temporary" credential becomes a permanent one.
An import is a rare, deliberate act: set the variable when you want to run one.

Constant time. The comparison uses hmac.compare_digest so a caller cannot
recover the secret one character at a time by measuring response latency.
"""
import hmac
import os


def configured_secret():
    """The expected secret, or None when the import endpoints are disabled."""
    return (os.environ.get('WIDEN_IMPORT_SECRET') or '').strip() or None


def is_enabled():
    return configured_secret() is not None


def secret_matches(supplied):
    """True only if the import is enabled and `supplied` is exactly right."""
    expected = configured_secret()
    if not expected:
        return False
    if not isinstance(supplied, str) or not supplied:
        return False
    return hmac.compare_digest(supplied, expected)
