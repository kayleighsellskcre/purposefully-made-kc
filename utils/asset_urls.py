"""Which picture addresses the server may open.

A picture address can arrive from a visitor (the cart takes one for a design or a back image) and is later opened by the
server to measure it or to build print files. Only our own storage and the garment photo hosts we already use are allowed,
decided by the real host name of the address, never by text found somewhere inside it.
"""
from urllib.parse import urlparse

# Garment photo hosts the shop already loads mockups from.
MOCKUP_HOSTS = frozenset((
    'cdn.ssactivewear.com', 'cdnm.sanmar.com', 'www.sanmar.com', 'sanmar.com', 'www.apparel4print.com',
    'apparel4print.com', 'cdn.shopify.com', 'embed.widencdn.net', 'widencdn.net',
))
_LOCAL_PREFIXES = ('/static/', '/uploads/')


def _host(url):
    try:
        return (urlparse(url).hostname or '').lower().rstrip('.')
    except ValueError:
        return ''


def _is_cloud_storage_host(host):
    return host == 'r2.dev' or host.endswith('.r2.dev') or host.endswith('.r2.cloudflarestorage.com')


def our_hosts(app=None, host_url=None):
    """Host names that are ours: the picture storage, the site itself and the address this request came to."""
    hosts = set()
    if app is not None:
        for key in ('R2_PUBLIC_URL', 'SITE_ORIGIN', 'ADMIN_BASE_URL'):
            host = _host(app.config.get(key) or '')
            if host:
                hosts.add(host)
    host = _host(host_url or '')
    if host:
        hosts.add(host)
    return hosts


def is_local_asset_path(url):
    """A /static/ or /uploads/ path with no way out of those folders."""
    path = str(url or '').split('?', 1)[0]
    return path.startswith(_LOCAL_PREFIXES) and '..' not in path and '\\' not in path and '//' not in path[1:]


def is_own_asset_url(url, app=None, host_url=None):
    """True for a path inside our own folders, or an http(s) address on our own storage or site."""
    url = str(url or '').strip()
    if not url:
        return False
    if url.startswith('/'):
        return is_local_asset_path(url)
    if not url.lower().startswith(('http://', 'https://')):
        return False
    host = _host(url)
    return bool(host) and (host in our_hosts(app, host_url) or _is_cloud_storage_host(host))


def is_fetchable_url(url, app=None, host_url=None):
    """Own pictures plus the garment photo hosts: the only addresses the server will download."""
    if is_own_asset_url(url, app, host_url):
        return True
    url = str(url or '').strip()
    return url.lower().startswith(('http://', 'https://')) and _host(url) in MOCKUP_HOSTS
