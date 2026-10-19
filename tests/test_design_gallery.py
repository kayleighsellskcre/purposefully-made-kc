"""Customer design gallery: collections -> subcategories -> designs, search, filters, automatic collections."""
from datetime import datetime, timedelta

from models import Design, DesignCategoryLink, DesignRelation, Order, OrderItem, db
from utils import design_tags as dt


def _d(title, collection=None, sub=None, tags=(), path=None, **over):
    d = Design(filename=f'{title}.png', original_filename=f'{title}.png', file_path=path or f'uploads/{title}.png',
               title=title, is_gallery=True, design_fee=0)
    for k, v in over.items():
        setattr(d, k, v)
    db.session.add(d)
    db.session.flush()
    if collection:
        db.session.add(DesignCategoryLink(design_id=d.id, category_key=collection, subcategory_key=sub, is_primary=True))
    if tags:
        dt.ensure_vocabulary()
        dt.apply_auto_tags(d, list(tags))
    return d


def _order(design_id, qty=1, days_ago=0, product_id=None):
    o = Order(order_number=f'PM-G-{design_id}-{days_ago}-{qty}', email='x@example.com', first_name='X', last_name='Y',
              subtotal=30, total=30, status='paid', payment_status='paid',
              created_at=datetime.utcnow() - timedelta(days=days_ago))
    db.session.add(o)
    db.session.flush()
    db.session.add(OrderItem(order_id=o.id, product_id=product_id, product_name='Tee', style_number='3001', size='M',
                             color='Black', quantity=qty, unit_price=30, subtotal=30 * qty, design_id=design_id))


def _get(client, url):
    return client.get(url).get_data(as_text=True)


def test_the_front_page_shows_collections_that_have_designs(app, client, seed):
    with app.app_context():
        _d('Chiefs Kingdom', 'kansas-city', 'kc-chiefs')
        _d('Cross Heart', 'faith-inspiration')
        db.session.commit()
    page = _get(client, '/shop/designs')
    assert 'Kansas City' in page and 'Faith &amp; Inspiration' in page
    assert 'collection=kansas-city' in page
    assert 'Christmas' not in page                       # empty collections stay hidden


def test_a_collection_lists_its_designs_with_subcategory_chips(app, client, seed):
    with app.app_context():
        _d('Chiefs Kingdom', 'kansas-city', 'kc-chiefs')
        _d('Royals Crown', 'kansas-city', 'kc-royals')
        _d('Cross Heart', 'faith-inspiration')
        db.session.commit()
    page = _get(client, '/shop/designs?collection=kansas-city')
    assert 'Chiefs Kingdom' in page and 'Royals Crown' in page and 'Cross Heart' not in page
    assert 'KC Chiefs' in page and 'KC Royals' in page
    assert 'Sporting KC' not in page                     # a subcategory with no designs is not offered
    sub = _get(client, '/shop/designs?collection=kansas-city&sub=kc-royals')
    assert 'Royals Crown' in sub and 'Chiefs Kingdom' not in sub


def test_old_category_links_still_work(app, client, seed):
    with app.app_context():
        _d('Prayer', None, folder='faith')
        _d('Helmet', None, folder='sports')
        db.session.commit()
    page = _get(client, '/shop/designs?category=faith')
    assert 'Prayer' in page and 'Helmet' not in page


def test_a_design_in_two_collections_shows_in_both(app, client, seed):
    with app.app_context():
        d = _d('Chiefs Mom', 'kansas-city', 'kc-chiefs')
        db.session.add(DesignCategoryLink(design_id=d.id, category_key='family-relationships', subcategory_key='moms'))
        db.session.commit()
    assert 'Chiefs Mom' in _get(client, '/shop/designs?collection=kansas-city')
    assert 'Chiefs Mom' in _get(client, '/shop/designs?collection=family-relationships&sub=moms')


def test_search_understands_synonyms_and_puts_close_cousins_after(app, client, seed):
    with app.app_context():
        _d('Best Mom Ever', 'family-relationships', 'moms', tags=['mom'])
        _d('Grandma Life', 'family-relationships', 'grandparents', tags=['grandma'])
        _d('Dad Joke', 'family-relationships', 'dads', tags=['dad'])
        db.session.commit()
    mama = _get(client, '/shop/designs?q=mama')
    assert 'Best Mom Ever' in mama and 'Dad Joke' not in mama
    nana = _get(client, '/shop/designs?q=grandma')
    assert 'Grandma Life' in nana


def test_search_inside_a_collection_stays_inside_it(app, client, seed):
    with app.app_context():
        _d('Best Mom Ever', 'family-relationships', 'moms', tags=['mom'])
        _d('Funny Mom', 'funny-sarcastic', 'mom-and-dad-humor', tags=['mom'])
        db.session.commit()
    page = _get(client, '/shop/designs?collection=funny-sarcastic&q=mom')
    assert 'Funny Mom' in page and 'Best Mom Ever' not in page


def test_filters_only_offer_choices_that_exist_and_narrow_the_designs(app, client, seed):
    with app.app_context():
        _d('Football Mom', 'sports-game-day', 'football', tags=['football', 'mom'])
        _d('Soccer Dad', 'sports-game-day', 'soccer', tags=['soccer', 'dad'])
        _d('Soccer Mom', 'sports-game-day', 'soccer', tags=['soccer', 'mom'])
        db.session.commit()
    page = _get(client, '/shop/designs?collection=sports-game-day')
    assert 'Who it is for' in page and 'Sport' in page
    narrowed = _get(client, '/shop/designs?collection=sports-game-day&recipient=mom&sport=soccer')
    assert 'Soccer Mom' in narrowed and 'Soccer Dad' not in narrowed and 'Football Mom' not in narrowed


def test_new_arrivals_are_recent_designs_only(app, client, seed):
    with app.app_context():
        _d('Fresh Design', 'faith-inspiration', uploaded_at=datetime.utcnow() - timedelta(days=3))
        _d('Old Design', 'faith-inspiration', uploaded_at=datetime.utcnow() - timedelta(days=400))
        db.session.commit()
    front = _get(client, '/shop/designs')
    assert 'New Arrivals' in front
    page = _get(client, '/shop/designs?collection=new-arrivals')
    assert 'Fresh Design' in page and 'Old Design' not in page


def test_fan_favorites_come_from_real_sales_and_you_can_pin_or_hide(app, client, seed):
    with app.app_context():
        best = _d('Best Seller', 'faith-inspiration')
        quiet = _d('Quiet One', 'faith-inspiration')
        pinned = _d('Pinned One', 'faith-inspiration', tags=[])
        hidden = _d('Hidden Hit', 'faith-inspiration')
        dt.ensure_vocabulary()
        from models import DesignTag
        for slug, design in (('fan-favorite', pinned), ('hide-favorite', hidden)):
            tag = DesignTag.query.filter_by(slug=slug).first()
            if tag is None:
                tag = DesignTag(slug=slug, label=slug.replace('-', ' ').title(), tag_type='theme', is_active=True)
                db.session.add(tag)
                db.session.flush()
            from models import DesignTagLink
            db.session.add(DesignTagLink(design_id=design.id, tag_id=tag.id, source='manual'))
        _order(best.id, qty=3, product_id=seed['tee_id'])
        _order(hidden.id, qty=5, product_id=seed['tee_id'])
        _order(quiet.id, qty=1, product_id=seed['tee_id'])
        db.session.commit()
    page = _get(client, '/shop/designs?collection=fan-favorites')
    assert 'Best Seller' in page and 'Pinned One' in page
    assert 'Hidden Hit' not in page and 'Quiet One' not in page
    assert page.index('Pinned One') < page.index('Best Seller')         # pinned first


def test_cancelled_orders_do_not_make_a_favorite(app, client, seed):
    with app.app_context():
        d = _d('Refunded Hit', 'faith-inspiration')
        _order(d.id, qty=4, product_id=seed['tee_id'])
        Order.query.update({'status': 'cancelled'})
        db.session.commit()
    assert 'Refunded Hit' not in _get(client, '/shop/designs?collection=fan-favorites')


def test_trending_is_recent_sales_only(app, client, seed):
    with app.app_context():
        hot = _d('Hot Now', 'faith-inspiration')
        stale = _d('Was Hot', 'faith-inspiration')
        _order(hot.id, days_ago=2, product_id=seed['tee_id'])
        _order(stale.id, days_ago=200, product_id=seed['tee_id'])
        db.session.commit()
    page = _get(client, '/shop/designs?collection=trending')
    assert 'Hot Now' in page and 'Was Hot' not in page


def test_matching_sets_use_only_sets_you_confirmed(app, client, seed):
    with app.app_context():
        a = _d('Set Shirt A', 'family-relationships', 'moms')
        b = _d('Set Shirt B', 'family-relationships', 'kids-and-babies')
        c = _d('Lone Shirt', 'family-relationships', 'dads')
        e = _d('Suggested Only', 'family-relationships', 'dads')
        db.session.add(DesignRelation(design_id=a.id, related_design_id=b.id, relation_type='matching_set', status='confirmed'))
        db.session.add(DesignRelation(design_id=c.id, related_design_id=e.id, relation_type='matching_set', status='suggested'))
        db.session.commit()
    page = _get(client, '/shop/designs?collection=matching-sets')
    assert 'Set Shirt A' in page and 'Set Shirt B' in page
    assert 'Lone Shirt' not in page and 'Suggested Only' not in page


def test_automatic_collections_are_hidden_when_there_is_nothing_to_show(app, client, seed):
    with app.app_context():
        Design.query.update({'uploaded_at': datetime.utcnow() - timedelta(days=400)})
        _d('Old Design', 'faith-inspiration', uploaded_at=datetime.utcnow() - timedelta(days=400))
        db.session.commit()
    front = _get(client, '/shop/designs')
    for name in ('New Arrivals', 'Trending Designs', 'Matching Sets'):
        assert name not in front


def test_related_designs_ride_along_on_each_card(app, client, seed):
    with app.app_context():
        a = _d('Crest Navy', 'school-spirit', 'mascots', tags=['football', 'mom'])
        b = _d('Crest Gold', 'school-spirit', 'mascots', tags=['football', 'mom'])
        db.session.commit()
    page = _get(client, '/shop/designs?collection=school-spirit')
    assert 'data-related=' in page and 'Crest Gold' in page
    assert 'You might also like' in page


def test_unknown_collection_falls_back_to_the_front_page(app, client, seed):
    with app.app_context():
        _d('Cross Heart', 'faith-inspiration')
        db.session.commit()
    page = _get(client, '/shop/designs?collection=nope')
    assert 'collection=faith-inspiration' in page


def test_leaving_a_group_order_still_happens_in_the_gallery(app, client, seed):
    r = client.get('/shop/designs?collection=faith-inspiration')
    assert r.status_code == 200
