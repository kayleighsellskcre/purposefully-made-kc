"""Round 2 audit item 2: homepage and the Group Orders page must list the
same public stores.

The homepage used to also require an empty created_by_user_id, meant to hide
customer self-service stores, but every store made through the normal create
flow (including ones an admin makes) gets a creator recorded, so it silently
dropped admin-made stores from the homepage while they stayed on the Group
Orders directory.
"""
from models import db, Collection


def test_an_admin_made_public_store_appears_on_both_pages(client, seed):
    """The seeded collection has created_by_user_id set (an admin made it),
    is_active and show_in_directory True: it should show up in both places.
    """
    home = client.get('/')
    assert seed['collection_slug'] in home.get_data(as_text=True)

    directory = client.get('/shop/group-orders')
    assert seed['collection_slug'] in directory.get_data(as_text=True)


def test_password_protected_stores_are_off_the_homepage_but_in_the_directory(app, client, seed):
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.is_password_protected = True
        db.session.commit()

    home = client.get('/')
    assert seed['collection_slug'] not in home.get_data(as_text=True)

    directory = client.get('/shop/group-orders')
    assert seed['collection_slug'] in directory.get_data(as_text=True)


def test_a_store_past_its_deadline_is_off_the_homepage(app, client, seed):
    from datetime import datetime, timedelta
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.order_deadline = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

    home = client.get('/')
    assert seed['collection_slug'] not in home.get_data(as_text=True)


# ── The homepage lists organizations the same way the Group Orders page does ──

def _public(app, **fields):
    from models import Collection
    with app.app_context():
        for coll in Collection.query.filter(Collection.name.like('%: Rainbow Cheetahs')).all():
            coll.show_in_directory = True
            for key, value in fields.items():
                setattr(coll, key, value)
        db.session.commit()


def test_homepage_shows_one_card_per_organization_not_one_per_team(admin_client, client, app, seed):
    from tests.test_org_fan_wear import _build, _org_slug
    _build(admin_client, app, seed)
    _public(app)
    html = client.get('/').get_data(as_text=True)
    section = html.split('id="collections"')[1].split('<!-- CTA Section -->')[0]
    assert section.count('class="hg-card"') >= 1
    assert f'/org/{_org_slug(app)}' in section
    for team in ('Basketball: Rainbow Cheetahs', 'Soccer: Rainbow Cheetahs', 'Volleyball: Rainbow Cheetahs'):
        assert team not in section


def test_a_hidden_organization_is_off_the_homepage_too(admin_client, client, app, seed):
    from models import Organization
    from tests.test_org_fan_wear import _build, _org_slug
    _build(admin_client, app, seed)
    _public(app)
    with app.app_context():
        Organization.query.filter_by(slug=_org_slug(app)).one().is_active = False
        db.session.commit()
    html = client.get('/').get_data(as_text=True)
    section = html.split('id="collections"')[1].split('<!-- CTA Section -->')[0]
    assert 'Rainbow Cheetahs' not in section


def test_homepage_cards_keep_long_messages_short(admin_client, client, app, seed):
    from models import Organization
    from tests.test_org_fan_wear import _build, _org_slug
    _build(admin_client, app, seed)
    _public(app)
    long_text = 'Welcome to the team shop! ' * 40
    with app.app_context():
        Organization.query.filter_by(slug=_org_slug(app)).one().description = long_text
        db.session.commit()
    section = client.get('/').get_data(as_text=True).split('id="collections"')[1].split('<!-- CTA Section -->')[0]
    assert long_text.strip() not in section and '…' in section


def test_homepage_shows_three_cards_and_a_see_all_link_when_there_are_more(client, app, seed):
    with app.app_context():
        for n in range(4):
            db.session.add(Collection(name=f'Extra Store {n}', slug=f'extra-store-{n}',
                                      is_active=True, show_in_directory=True))
        db.session.commit()
    section = client.get('/').get_data(as_text=True).split('id="collections"')[1].split('<!-- CTA Section -->')[0]
    assert section.count('class="hg-card"') == 3
    assert 'See all 5 group orders' in section


# ── Group Orders page: the open orders come first ────────────────────────────

def test_group_orders_page_lists_open_orders_before_the_explanations(client, seed):
    html = client.get('/shop/group-orders').get_data(as_text=True)
    assert html.index('id="open-orders"') < html.index('class="go-help"')
    assert 'class="cta-section"' not in html and 'Ready to get started' not in html     # the repeat block is gone
    assert 'Everyone pays their own' in html and 'Company covers it' in html           # the two ways to order
    assert 'href="#open-orders"' in html                         # "Find your group"


def test_group_orders_explanations_start_collapsed_when_there_are_open_orders(client, seed):
    html = client.get('/shop/group-orders').get_data(as_text=True)
    tag = html[html.index('<details class="go-help"'):].split('>')[0]
    assert ' open' not in tag
    assert 'Common Questions' in html and 'Build your store' in html     # still on the page, just folded


def test_group_orders_explanations_start_open_when_nothing_is_open(app, client, seed):
    with app.app_context():
        c = db.session.get(Collection, seed['collection_id'])
        c.show_in_directory = False
        db.session.commit()
    html = client.get('/shop/group-orders').get_data(as_text=True)
    tag = html[html.index('<details class="go-help"'):].split('>')[0]
    assert ' open' in tag
    assert 'href="#open-orders"' not in html
