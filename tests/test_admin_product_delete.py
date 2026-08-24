"""Admin delete on the product edit page.

The button used to sit inside a nested <form>, which the HTML parser discards.
Clicking it therefore submitted nothing. These tests pin the replacement:

  * The markup no longer nests a form, and the button points at a sibling form
    with the HTML `form` attribute so it works even without JavaScript.
  * A style nobody has bought is removed from the catalog.
  * A style that appears in a past order is hidden, not deleted, because
    OrderItem.product_id cannot be null.
"""

import re

from models import db, Favorite, Order, OrderItem, Product, ProductColorVariant, collection_products


def edit_html(client, product_id):
    resp = client.get(f'/admin/products/{product_id}/edit')
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


def delete_url(product_id):
    return f'/admin/products/{product_id}/delete'


# ── Markup: the button has to be able to fire ────────────────────────────────

def test_edit_page_has_a_delete_button_wired_to_its_own_form(admin_client, seed):
    html = edit_html(admin_client, seed['tee_id'])
    assert 'Delete Product' in html
    assert 'form="deleteProductForm"' in html
    assert 'id="deleteProductForm"' in html
    assert f'action="{delete_url(seed["tee_id"])}"' in html or \
           f"action='{delete_url(seed['tee_id'])}'" in html or \
           f'/admin/products/{seed["tee_id"]}/delete' in html


def test_delete_form_is_not_nested_inside_the_edit_form(admin_client, seed):
    """Same invariant as tests/test_no_nested_forms.py, scoped to this page."""
    html = edit_html(admin_client, seed['tee_id'])
    body = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    depth = 0
    for match in re.finditer(r'<\s*(/?)form\b', body, re.IGNORECASE):
        if match.group(1) == '/':
            depth = max(0, depth - 1)
            continue
        depth += 1
        assert depth <= 1, 'edit page still nests a form; the delete button will do nothing'


# ── Who may call the route ───────────────────────────────────────────────────

def test_guest_cannot_delete(client, seed, app):
    resp = client.post(delete_url(seed['tee_id']))
    assert resp.status_code in (301, 302, 401, 403)
    with app.app_context():
        assert Product.query.get(seed['tee_id']) is not None


def test_customer_cannot_delete(customer_client, seed, app):
    resp = customer_client.post(delete_url(seed['tee_id']))
    assert resp.status_code in (301, 302, 401, 403)
    with app.app_context():
        assert Product.query.get(seed['tee_id']) is not None


# ── Unused product: actually removed ─────────────────────────────────────────

def test_admin_can_delete_a_product_nobody_has_bought(admin_client, seed, app):
    product_id = seed['hoodie_id']
    resp = admin_client.post(delete_url(product_id), follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lower()
    assert 'removed' in body

    with app.app_context():
        assert Product.query.get(product_id) is None
        assert ProductColorVariant.query.filter_by(product_id=product_id).count() == 0


def test_deleted_product_disappears_from_the_shop(admin_client, seed, app):
    product_id = seed['youth_id']
    with app.app_context():
        style = Product.query.get(product_id).style_number
    admin_client.post(delete_url(product_id), follow_redirects=True)
    shop = admin_client.get('/shop/').get_data(as_text=True)
    assert style not in shop


def test_delete_clears_favorites_and_group_order_membership(admin_client, seed, app):
    from models import Collection
    import secrets

    product_id = seed['youth_id']
    with app.app_context():
        collection = Collection(
            name='Team Tees', slug='team-tees-test',
            share_token=secrets.token_hex(8),
        )
        db.session.add(collection)
        db.session.flush()
        db.session.execute(collection_products.insert().values(
            collection_id=collection.id, product_id=product_id,
        ))
        db.session.add(Favorite(user_id=seed['customer_id'], product_id=product_id))
        db.session.commit()
        collection_id = collection.id

    admin_client.post(delete_url(product_id), follow_redirects=True)

    with app.app_context():
        assert Product.query.get(product_id) is None
        assert Favorite.query.filter_by(product_id=product_id).count() == 0
        remaining = db.session.query(collection_products).filter_by(
            product_id=product_id,
        ).count()
        assert remaining == 0
        assert Collection.query.get(collection_id) is not None


# ── Product in a past order: hidden, not deleted ─────────────────────────────

def test_product_in_a_past_order_is_hidden_not_deleted(admin_client, seed, app):
    product_id = seed['tee_id']
    with app.app_context():
        order = Order(
            order_number='PM-TEST-001',
            email='casey@example.com',
            subtotal=30.0, total=30.0,
            payment_status='paid', status='completed',
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=product_id,
            product_name='Unisex Jersey Short Sleeve Tee',
            style_number='3001',
            size='M', color='Black',
            quantity=1, unit_price=30.0, subtotal=30.0,
        ))
        db.session.commit()

    resp = admin_client.post(delete_url(product_id), follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lower()
    assert 'hidden' in body
    assert 'past order' in body

    with app.app_context():
        product = Product.query.get(product_id)
        assert product is not None
        assert product.is_active is False
        assert OrderItem.query.filter_by(product_id=product_id).count() == 1
