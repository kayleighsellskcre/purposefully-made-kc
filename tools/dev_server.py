"""Run the site locally against a throwaway SQLite copy of the real catalogue.

    py -3.12 tools/dev_server.py            # seed if needed, then serve
    py -3.12 tools/dev_server.py --reseed   # rebuild dev.db from production

Why this exists: auditing layout, speed, and accessibility needs real products
with real image URLs, but nothing about the audit should touch live data. This
copies products, colour variants, gallery designs, and public group orders out
of production read-only, and copies no customers and no orders at all. Test
accounts are created locally.

Sign in with:
    owner@example.test    / DevPassw0rd!23   (admin)
    shopper@example.test  / DevPassw0rd!23
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

PRODUCTION_URL = (os.environ.get('DATABASE_URL') or '').replace(
    'postgres://', 'postgresql://', 1
)
DEV_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'dev.db'
)

# Point every service at nothing before the app is imported. app.py builds an
# app at module scope, so this has to happen first.
os.environ['DATABASE_URL'] = f'sqlite:///{DEV_DB_PATH}'
os.environ['SESSION_COOKIE_SECURE'] = 'false'
os.environ['PREFERRED_URL_SCHEME'] = 'http'
os.environ['SCHEDULER_ENABLED'] = 'false'
# Any mail this instance tries to send goes to the owner, never a customer.
os.environ.setdefault('MAIL_TEST_REDIRECT', 'purposefullymadekc@gmail.com')
for _var in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER',
             'ADMIN_PHONE_CARRIER', 'SANMAR_USERNAME', 'SANMAR_PASSWORD',
             'SSACTIVEWEAR_API_KEY', 'SSACTIVEWEAR_ACCOUNT_NUMBER'):
    os.environ.pop(_var, None)

PASSWORD = 'DevPassw0rd!23'
PRODUCT_LIMIT = 40


def _copy_from_production(app):
    """Copy catalogue rows only. No users, no orders, no design requests."""
    from sqlalchemy import create_engine, text

    from models import (
        db, Collection, Design, Product, ProductColorVariant,
    )

    if not PRODUCTION_URL.startswith('postgresql'):
        print('No production DATABASE_URL found; seeding a minimal catalogue.')
        return _minimal_catalogue(app)

    engine = create_engine(
        PRODUCTION_URL, connect_args={'connect_timeout': 20}, pool_pre_ping=True
    )

    def columns_of(model):
        return {c.name for c in model.__table__.columns}

    with engine.connect() as conn, app.app_context():
        def fetch(table, model, where='', limit=None):
            cols = columns_of(model)
            live = {r[0] for r in conn.execute(text(
                'select column_name from information_schema.columns '
                'where table_name = :t'
            ), {'t': table})}
            usable = sorted(cols & live)
            sql = f'select {", ".join(chr(34) + c + chr(34) for c in usable)} from "{table}" {where}'
            if limit:
                sql += f' limit {limit}'
            return [dict(r) for r in conn.execute(text(sql)).mappings()]

        products = fetch('product', Product,
                         'where is_active = true order by id', PRODUCT_LIMIT)
        for row in products:
            db.session.add(Product(**row))
        db.session.flush()

        ids = [p['id'] for p in products]
        if ids:
            id_list = ','.join(str(i) for i in ids)
            for row in fetch('product_color_variant', ProductColorVariant,
                             f'where product_id in ({id_list})'):
                db.session.add(ProductColorVariant(**row))

        for row in fetch('design', Design, 'where is_gallery = true', 48):
            db.session.add(Design(**row))

        # Public group orders only, and drop the password so nothing private
        # is reachable from the copy.
        for row in fetch('collection', Collection,
                         'where is_active = true and password_hash is null', 10):
            db.session.add(Collection(**row))

        db.session.commit()
        print(f'Copied {len(products)} products, '
              f'{ProductColorVariant.query.count()} colour variants, '
              f'{Design.query.count()} designs, '
              f'{Collection.query.count()} group orders.')


def _minimal_catalogue(app):
    from models import db, Design, Product, ProductColorVariant

    sizes = json.dumps(['S', 'M', 'L', 'XL', '2XL', '3XL'])
    with app.app_context():
        tee = Product(style_number='3001', name='Unisex Jersey Short Sleeve Tee',
                      category='Tee', age_group='adult', base_price=30.0,
                      wholesale_cost=6.0, is_active=True,
                      available_sizes=sizes,
                      available_colors=json.dumps(['Black', 'White']))
        hoodie = Product(style_number='18500', name='Heavy Blend Hooded Sweatshirt',
                         category='Hoodie', age_group='adult', base_price=45.0,
                         wholesale_cost=14.0, is_active=True,
                         available_sizes=sizes,
                         available_colors=json.dumps(['Black']))
        db.session.add_all([tee, hoodie])
        db.session.flush()
        stock = json.dumps({s: 50 for s in json.loads(sizes)})
        db.session.add_all([
            ProductColorVariant(product_id=tee.id, color_name='Black',
                                color_hex='#000000', size_inventory=stock),
            ProductColorVariant(product_id=hoodie.id, color_name='Black',
                                color_hex='#000000', size_inventory=stock),
        ])
        db.session.add(Design(filename='logo.png',
                              file_path='uploads/designs/logo.png',
                              title='Sample Logo', is_gallery=True, design_fee=0))
        db.session.commit()


def _create_test_accounts(app):
    from models import db, User

    with app.app_context():
        for email, admin, first in (
            ('owner@example.test', True, 'Dev'),
            ('shopper@example.test', False, 'Sam'),
        ):
            if User.query.filter_by(email=email).first():
                continue
            user = User(email=email, first_name=first, last_name='Tester',
                        is_admin=admin, phone='816-555-0100')
            user.set_password(PASSWORD)
            db.session.add(user)
        db.session.commit()


def seed(app):
    from models import db

    with app.app_context():
        db.drop_all()
        db.create_all()
    _copy_from_production(app)
    _create_test_accounts(app)
    print('\nSign in as owner@example.test (admin) or shopper@example.test')
    print(f'Password for both: {PASSWORD}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reseed', action='store_true',
                        help='rebuild dev.db from production before serving')
    parser.add_argument('--seed-only', action='store_true')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()

    fresh = args.reseed or args.seed_only or not os.path.exists(DEV_DB_PATH)

    from app import create_app
    app = create_app()

    if fresh:
        seed(app)
    if args.seed_only:
        return

    print(f'\nServing http://127.0.0.1:{args.port}  (SQLite at {DEV_DB_PATH})')
    # threaded so a slow page cannot block the audit, debug off so the
    # production error handlers are the ones being exercised.
    app.run(host='127.0.0.1', port=args.port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
