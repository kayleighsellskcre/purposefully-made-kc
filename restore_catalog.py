"""
One-off catalog restore / health-check tool.

Talks DIRECTLY to the Railway Postgres (via schema reflection, so it matches
whatever columns the live DB actually has) and reuses the S&S Activewear client.
It does NOT boot the Flask app, so it needs only: sqlalchemy, psycopg2, requests.

Safety:
  * Default run is READ-ONLY: it reports product / variant counts and schema,
    and changes nothing.
  * Pass --apply to actually restore from S&S. The upsert is idempotent
    (matched on style_number / product+color), so it will NOT create duplicates.
  * Refuses to run against SQLite, so you can't accidentally hit the wrong DB.

Usage (PowerShell):
  $env:DATABASE_URL="postgresql://...";  `
  $env:SSACTIVEWEAR_API_KEY="...";       `
  $env:SSACTIVEWEAR_ACCOUNT_NUMBER="..."; `
  python restore_catalog.py            # read-only check
  python restore_catalog.py --apply    # perform the restore
"""
import argparse
import os
import sys
from datetime import datetime

from sqlalchemy import (
    create_engine, MetaData, Table, select, func, insert, update,
)


def normalize_url(url):
    if url and url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


# Protected on UPDATE only: never overwrite admin-set pricing/status/merchandising
# for products that already exist. (On a fresh empty DB everything is an INSERT.)
PROTECTED_ON_UPDATE = {'base_price', 'wholesale_cost', 'is_active', 'is_customer_favorite'}


def variant_values(vd, pid, vcols, now):
    """Map an S&S color-variant dict to the product_color_variant columns."""
    raw = {
        'product_id': pid,
        'color_name': vd.get('color_name'),
        'color_hex': vd.get('color_hex'),
        'front_image_url': vd.get('front_image'),
        'back_image_url': vd.get('back_image'),
        'side_image_url': vd.get('side_image'),
        'size_inventory': vd.get('size_inventory'),
        'ss_color_id': vd.get('color_id'),
        'last_synced': now,
    }
    return {k: v for k, v in raw.items() if k in vcols}


def main():
    ap = argparse.ArgumentParser(description='Catalog restore / health check')
    ap.add_argument('--apply', action='store_true',
                    help='Write to the DB (default: read-only check)')
    ap.add_argument('--limit', type=int, default=None,
                    help='Limit number of styles (for a quick test run)')
    args = ap.parse_args()

    db_url = normalize_url(os.environ.get('DATABASE_URL'))
    if not db_url:
        print('ERROR: DATABASE_URL is not set.')
        sys.exit(1)
    if db_url.startswith('sqlite'):
        print('ERROR: DATABASE_URL points to SQLite, not your Railway Postgres.')
        print('Aborting so we do not touch the wrong database.')
        sys.exit(1)

    engine = create_engine(db_url)
    md = MetaData()
    try:
        product = Table('product', md, autoload_with=engine)
        variant = Table('product_color_variant', md, autoload_with=engine)
    except Exception as e:
        print(f'ERROR: could not reflect tables: {e}')
        sys.exit(1)

    pcols = set(product.c.keys())
    vcols = set(variant.c.keys())

    with engine.connect() as conn:
        pcount = conn.execute(select(func.count()).select_from(product)).scalar()
        try:
            active = conn.execute(
                select(func.count()).select_from(product).where(product.c.is_active.is_(True))
            ).scalar()
        except Exception:
            active = '?'
        vcount = conn.execute(select(func.count()).select_from(variant)).scalar()

    print('=' * 70)
    print('CATALOG HEALTH CHECK')
    print('=' * 70)
    print(f'  Products:        {pcount}  (active: {active})')
    print(f'  Color variants:  {vcount}')
    print(f'  Product columns: {sorted(pcols)}')

    if pcount:
        with engine.connect() as conn:
            sample = conn.execute(
                select(product.c.style_number, product.c.name, product.c.is_active).limit(8)
            ).fetchall()
        print('  Sample products:')
        for r in sample:
            print(f'    - {r[0]}: {r[1]} (active={r[2]})')

    if not args.apply:
        print('-' * 70)
        if pcount == 0:
            print('Result: products table is EMPTY. Re-run with --apply to restore from S&S.')
        else:
            print('Result: products exist. If the store still looks empty, the issue is a')
            print('        display/filter problem (e.g. is_active), not data loss.')
        print('(Read-only run — nothing was changed.)')
        return

    # ---- APPLY: restore from S&S ------------------------------------------
    print('-' * 70)
    print('APPLY mode: fetching catalog from S&S Activewear...')
    from services.ssactivewear_api import SSActivewearAPI
    api = SSActivewearAPI()
    products_data = api.sync_bella_canvas_catalog(limit=args.limit)
    if not products_data:
        print('S&S returned no products — nothing to restore. Check API credentials.')
        return

    added = updated = v_added = v_updated = 0
    now = datetime.utcnow()

    with engine.begin() as conn:  # single transaction: all-or-nothing, no partials
        for pd in products_data:
            color_variants = pd.pop('color_variants', []) or []
            sn = pd.get('style_number')
            if not sn:
                continue

            data = {k: v for k, v in pd.items() if k in pcols}
            existing = conn.execute(
                select(product.c.id).where(product.c.style_number == sn)
            ).first()

            if existing:
                pid = existing[0]
                upd = {k: v for k, v in data.items()
                       if k not in PROTECTED_ON_UPDATE and v is not None}
                if 'updated_at' in pcols:
                    upd['updated_at'] = now
                if upd:
                    conn.execute(update(product).where(product.c.id == pid).values(**upd))
                updated += 1
            else:
                if 'is_active' in pcols and data.get('is_active') is None:
                    data['is_active'] = True
                if 'created_at' in pcols and 'created_at' not in data:
                    data['created_at'] = now
                if 'updated_at' in pcols and 'updated_at' not in data:
                    data['updated_at'] = now
                res = conn.execute(insert(product).values(**data))
                pid = res.inserted_primary_key[0]
                added += 1

            for vd in color_variants:
                cn = vd.get('color_name')
                if not cn:
                    continue
                vvals = variant_values(vd, pid, vcols, now)
                vrow = conn.execute(
                    select(variant.c.id).where(
                        variant.c.product_id == pid,
                        variant.c.color_name == cn,
                    )
                ).first()
                if vrow:
                    upd = {k: v for k, v in vvals.items()
                           if k not in ('product_id', 'color_name')}
                    conn.execute(update(variant).where(variant.c.id == vrow[0]).values(**upd))
                    v_updated += 1
                else:
                    conn.execute(insert(variant).values(**vvals))
                    v_added += 1

    with engine.connect() as conn:
        final = conn.execute(select(func.count()).select_from(product)).scalar()

    print('=' * 70)
    print('RESTORE COMPLETE')
    print(f'  Products added:    {added}')
    print(f'  Products updated:  {updated}')
    print(f'  Variants added:    {v_added}')
    print(f'  Variants updated:  {v_updated}')
    print(f'  Total products now: {final}')
    print('=' * 70)


if __name__ == '__main__':
    main()
