"""Per-page metadata: titles, descriptions, canonical URLs, robots, Open Graph.

Before this, every one of the 74 templates shared base.html's single description
and a single Open Graph card, so every page looked identical to a search engine
and every shared link previewed as the shop logo. These tests pin the parts that
are easy to regress: a new page inheriting the generic description, a private
page becoming indexable, or the canonical drifting back to whatever host the
visitor happened to arrive on.
"""
import re

import pytest

from config import TestConfig

# The fallback wording in base.html. A page still showing this has no
# description of its own.
GENERIC_DESCRIPTION = 'premium custom apparel with DTF printing'

ORIGIN = TestConfig.SITE_ORIGIN.rstrip('/')


def _meta(html, name):
    match = re.search(
        r'<meta\s+name="%s"\s+content="([^"]*)"' % re.escape(name), html)
    return match.group(1) if match else None


def _og(html, prop):
    match = re.search(
        r'<meta\s+property="%s"\s+content="([^"]*)"' % re.escape(prop), html)
    return match.group(1) if match else None


def _canonical(html):
    match = re.search(r'<link\s+rel="canonical"\s+href="([^"]*)"', html)
    return match.group(1) if match else None


def _title(html):
    match = re.search(r'<title>(.*?)</title>', html, re.S)
    return match.group(1).strip() if match else None


def _get(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f'{path} returned {resp.status_code}'
    return resp.get_data(as_text=True)


# Public pages that should each describe themselves.
PUBLIC_PAGES = [
    '/',
    '/shop/',
    '/shop/designs',
    '/shop/group-orders',
    '/custom-design/',
    '/about',
    '/contact',
    '/privacy',
    '/terms',
]


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_public_page_has_its_own_description(client, path):
    html = _get(client, path)
    description = _meta(html, 'description')
    assert description, f'{path} has no meta description'
    assert GENERIC_DESCRIPTION not in description, (
        f'{path} is still falling back to the site-wide description'
    )


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_public_page_is_indexable(client, path):
    html = _get(client, path)
    assert _meta(html, 'robots') == 'index, follow', path


def test_public_descriptions_are_all_different(client):
    """Two pages sharing a description is the same problem as having none."""
    seen = {}
    for path in PUBLIC_PAGES:
        description = _meta(_get(client, path), 'description')
        assert description not in seen, (
            f'{path} shares its description with {seen.get(description)}'
        )
        seen[description] = path


def test_public_titles_are_all_different(client):
    seen = {}
    for path in PUBLIC_PAGES:
        title = _title(_get(client, path))
        assert title, f'{path} has no title'
        assert title not in seen, (
            f'{path} shares its title with {seen.get(title)}'
        )
        seen[title] = path


# ── Product pages ────────────────────────────────────────────────────────────

def test_product_page_describes_the_product(client, seed):
    html = _get(client, f'/shop/product/{seed["tee_id"]}')
    description = _meta(html, 'description')
    assert description
    assert GENERIC_DESCRIPTION not in description
    assert 'Unisex Jersey Short Sleeve Tee' in description


def test_product_page_title_names_the_product(client, seed):
    html = _get(client, f'/shop/product/{seed["tee_id"]}')
    assert 'Unisex Jersey Short Sleeve Tee' in _title(html)


def test_product_page_is_an_og_product(client, seed):
    html = _get(client, f'/shop/product/{seed["tee_id"]}')
    assert _og(html, 'og:type') == 'product'


def test_customize_page_describes_the_product(client, seed):
    html = _get(client, f'/shop/customize/{seed["tee_id"]}')
    description = _meta(html, 'description')
    assert description
    assert GENERIC_DESCRIPTION not in description
    assert 'Unisex Jersey Short Sleeve Tee' in description


# ── Canonical URLs ───────────────────────────────────────────────────────────

def test_canonical_uses_the_configured_origin(client):
    """Not the request host.

    request.base_url was used before, so arriving as www, as non-www, or on the
    raw Railway hostname advertised a different canonical for the same page.
    """
    html = _get(client, '/about')
    assert _canonical(html) == f'{ORIGIN}/about'


def test_canonical_ignores_the_request_host(client):
    html = client.get('/about', base_url='http://some-other-host.example')
    assert _canonical(html.get_data(as_text=True)) == f'{ORIGIN}/about'


def test_canonical_drops_the_query_string(client):
    """Filtered shop views are the same catalogue reordered."""
    html = _get(client, '/shop/?category=Tee&color=Black')
    assert _canonical(html) == f'{ORIGIN}/shop/'


def test_filtered_shop_view_is_not_indexed(client):
    """Otherwise every filter combination competes with /shop/ itself."""
    html = _get(client, '/shop/?category=Tee')
    assert _meta(html, 'robots') == 'noindex, follow'


def test_unfiltered_shop_view_is_indexed(client):
    assert _meta(_get(client, '/shop/'), 'robots') == 'index, follow'


def test_og_url_matches_the_canonical(client):
    html = _get(client, '/about')
    assert _og(html, 'og:url') == _canonical(html)


# ── Private areas stay out of search ─────────────────────────────────────────

PRIVATE_PAGES = [
    '/cart/',
    '/auth/login',
    '/auth/register',
    '/favorites',
]


@pytest.mark.parametrize('path', PRIVATE_PAGES)
def test_private_page_is_noindex(client, path):
    """Derived from the blueprint in app.py, so a new page in these areas is
    covered without anyone remembering to add a tag."""
    html = _get(client, path)
    assert _meta(html, 'robots') == 'noindex, nofollow', path


def test_account_pages_are_noindex(customer_client):
    html = _get(customer_client, '/account/orders')
    assert _meta(html, 'robots') == 'noindex, nofollow'


def test_admin_pages_are_noindex(admin_client):
    html = _get(admin_client, '/admin/')
    assert _meta(html, 'robots') == 'noindex, nofollow'


def test_404_page_is_noindex(client):
    """Every mistyped URL renders this page."""
    resp = client.get('/no-such-page-here')
    assert resp.status_code == 404
    assert _meta(resp.get_data(as_text=True), 'robots') == 'noindex, follow'


def test_private_group_order_is_noindex(client, app, seed):
    """A link-only or password-protected store is not for search results."""
    from models import Collection, db

    with app.app_context():
        collection = db.session.get(Collection, seed['collection_id'])
        collection.show_in_directory = False
        db.session.commit()

    html = _get(client, f'/c/{seed["collection_slug"]}')
    assert _meta(html, 'robots') == 'noindex, nofollow'


def test_public_group_order_is_indexed(client, seed):
    html = _get(client, f'/c/{seed["collection_slug"]}')
    assert _meta(html, 'robots') == 'index, follow'


# ── Open Graph completeness ──────────────────────────────────────────────────

def test_og_image_is_absolute(client):
    """A relative og:image is ignored by Facebook and iMessage."""
    image = _og(_get(client, '/'), 'og:image')
    assert image.startswith('http'), image


def test_og_image_file_exists(client):
    """The default card must point at a file that is actually served."""
    image = _og(_get(client, '/'), 'og:image')
    path = image[len(ORIGIN):]
    assert client.get(path).status_code == 200, path


def test_og_title_follows_the_page_title(client):
    html = _get(client, '/about')
    assert _og(html, 'og:title') == _title(html)


def test_og_description_follows_the_meta_description(client):
    html = _get(client, '/about')
    assert _og(html, 'og:description') == _meta(html, 'description')


def test_og_site_name_is_the_business_name(client):
    assert _og(_get(client, '/'), 'og:site_name') == 'Purposefully Made KC'
