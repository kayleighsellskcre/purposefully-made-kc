"""Round 2 audit item 14: JSON-LD structured data on the homepage
(Organization + LocalBusiness) and product pages (Product, with real
offers). No fake ratings or reviews anywhere - the site collects none.
"""
import json
import re


def _ld_json_blocks(html):
    return [
        json.loads(match)
        for match in re.findall(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            html, re.S,
        )
    ]


def test_homepage_has_organization_and_local_business(client):
    body = client.get('/').get_data(as_text=True)
    blocks = _ld_json_blocks(body)
    assert blocks, 'no JSON-LD block found on the homepage'
    org = blocks[0]
    assert set(org['@type']) == {'Organization', 'LocalBusiness'}
    assert org['name'] == 'Purposefully Made KC'
    assert org['url'].startswith('http')
    assert org['logo'].startswith('http')
    assert org['address']['addressLocality'] == 'Kansas City'
    assert '/contact' in org['contactPoint']['url']


def test_homepage_structured_data_has_no_fake_ratings(client):
    body = client.get('/').get_data(as_text=True)
    org = _ld_json_blocks(body)[0]
    assert 'aggregateRating' not in org
    assert 'review' not in org


def test_product_page_has_product_schema(client, seed):
    body = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    blocks = _ld_json_blocks(body)
    assert blocks, 'no JSON-LD block found on the product page'
    product = next(b for b in blocks if b.get('@type') == 'Product')
    assert product['name'] == 'Unisex Jersey Short Sleeve Tee'
    assert product['image'].startswith('http')
    assert product['description']
    assert product['brand'] == {'@type': 'Brand', 'name': 'Bella+Canvas'}
    assert product['offers']['@type'] == 'Offer'
    assert product['offers']['priceCurrency'] == 'USD'
    assert product['offers']['price'] == '30.00'
    assert product['offers']['availability'] == 'https://schema.org/InStock'


def test_product_page_structured_data_has_no_fake_ratings(client, seed):
    body = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    product = next(b for b in _ld_json_blocks(body) if b.get('@type') == 'Product')
    assert 'aggregateRating' not in product
    assert 'review' not in product
