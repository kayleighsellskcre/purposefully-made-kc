"""Every template must parse.

/shop/product/279 returned 500 twice in production with
"TemplateSyntaxError: Encountered unknown tag 'endif'". A stray tag like that
is invisible until someone loads the exact page that uses it, so compile the
whole template tree here instead of waiting for a customer to find it.
"""
import os

import pytest
from jinja2 import TemplateSyntaxError


def _template_names(app):
    return sorted(app.jinja_env.list_templates(extensions=('html', 'xml', 'txt')))


def test_there_are_templates_to_check(app):
    assert len(_template_names(app)) > 50


def test_every_template_parses(app):
    broken = []
    for name in _template_names(app):
        try:
            app.jinja_env.get_template(name)
        except TemplateSyntaxError as exc:
            broken.append(f'{name}:{exc.lineno}: {exc.message}')
        except Exception as exc:  # a missing include or import is also fatal
            broken.append(f'{name}: {type(exc).__name__}: {exc}')
    assert not broken, 'templates that will 500 when rendered:\n' + '\n'.join(broken)


def test_no_template_is_left_with_merge_conflict_markers(app):
    root = os.path.join(app.root_path, 'templates')
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            with open(path, encoding='utf-8', errors='replace') as handle:
                for lineno, line in enumerate(handle, 1):
                    if line.startswith(('<<<<<<< ', '>>>>>>> ')):
                        hits.append(f'{os.path.relpath(path, root)}:{lineno}')
    assert not hits, f'unresolved merge markers: {hits}'


@pytest.mark.parametrize('name', [
    'base.html',
    'errors/404.html',
    'errors/500.html',
    'shop/index.html',
    'shop/product_detail.html',
    'shop/customize.html',
    'cart/index.html',
    'checkout/index.html',
    'email/order_confirmation.html',
    'email/admin_order_alert.html',
    'email/design_request_customer.html',
    'email/design_request_admin.html',
])
def test_critical_templates_exist_and_parse(app, name):
    assert app.jinja_env.get_template(name) is not None
