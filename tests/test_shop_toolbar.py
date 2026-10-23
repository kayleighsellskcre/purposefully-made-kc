"""Shop: one toolbar row, sorting, quick chips, and compact product cards."""
from models import Order, OrderItem, db


def _order_hoodies(seed, how_many):
    order = Order(user_id=seed['customer_id'], first_name='A', last_name='B', email='a@b.co', subtotal=1, total=1,
                  payment_status='paid', status='paid', production_stage='order_received')
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=seed['hoodie_id'], product_name='Hoodie', size='M',
                             color='Black', quantity=how_many, unit_price=45, subtotal=45 * how_many))
    db.session.commit()


def _order_of(html, *names):
    spots = [html.index(n) for n in names]
    return spots == sorted(spots)


def test_sort_by_price(guest):
    tee, hoodie = 'Unisex Jersey Short Sleeve Tee', 'Heavy Blend Hooded Sweatshirt'
    low = guest.get('/shop/?sort=price_asc').get_data(as_text=True)
    high = guest.get('/shop/?sort=price_desc').get_data(as_text=True)
    assert _order_of(low, tee, hoodie) and _order_of(high, hoodie, tee)
    assert 'value="price_desc" selected' in high


def test_sort_by_most_popular_and_unknown_sort_is_ignored(guest, app, seed):
    with app.app_context():
        _order_hoodies(seed, 5)
    popular = guest.get('/shop/?sort=popular').get_data(as_text=True)
    assert _order_of(popular, 'Heavy Blend Hooded Sweatshirt', 'Unisex Jersey Short Sleeve Tee')
    assert guest.get('/shop/?sort=nonsense').status_code == 200


def test_toolbar_chips_and_cards(guest):
    html = guest.get('/shop/').get_data(as_text=True)
    for text in ('class="filter-bar shop-toolbar"', 'id="sortSelect"', 'Tees', 'Long Sleeve', 'Sweatshirts',
                 'Hoodies', 'Kids &amp; Baby', 'Ordering for a team or group?', 'Customize'):
        assert text in html, text
    for gone in ('Refine Your Selection', 'class="product-category"', 'Choose Age Group',
                 'class="color-indicator"', 'daily-affirmation-wrap', 'Start a Group Order\n'):
        assert gone not in html, gone
    assert 'category=Hoodie' in html and 'age_group=kids' in html


def test_chip_links_keep_the_sort_choice(guest):
    html = guest.get('/shop/?sort=price_desc').get_data(as_text=True)
    assert 'category=Tee&amp;sort=price_desc' in html or 'category=Tee&sort=price_desc' in html
