"""
Background scheduler for automated tasks.
Nightly (America/Chicago):
  1:00 AM — SanMar curated catalog (does not overwrite live warehouse qty)
  2:00 AM — S&S ghost/front images for Bella+Canvas
  3:00 AM — live in-stock quantities from SanMar and S&S
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from zoneinfo import ZoneInfo
import sys

CHICAGO = ZoneInfo('America/Chicago')


def sync_full_catalog_job(app):
    """
    Nightly job: sync the complete Bella+Canvas catalog from SanMar.
    Adds new styles and refreshes inventory on all existing ones.
    Runs at 1:00 AM daily.
    """
    with app.app_context():
        try:
            print("=" * 80, file=sys.stderr, flush=True)
            print(f"NIGHTLY CATALOG SYNC STARTED - {datetime.now()}", file=sys.stderr, flush=True)
            print("=" * 80, file=sys.stderr, flush=True)

            from services.sanmar_api import SanMarAPI, check_credentials, SanMarAuthError
            from models import db, Product, ProductColorVariant

            # Skip gracefully if SanMar credentials aren't configured
            cred_check = check_credentials()
            if not cred_check['ok']:
                missing = ', '.join(cred_check['missing'])
                print(
                    f"NIGHTLY SYNC SKIPPED — missing SanMar credentials: {missing}",
                    file=sys.stderr, flush=True
                )
                return

            api = SanMarAPI()
            products_data = api.sync_bella_canvas_catalog()

            if not products_data:
                print("WARNING: No products returned from SanMar API.", file=sys.stderr, flush=True)
                return

            added = updated = variants_added = variants_updated = 0

            for product_data in products_data:
                color_variants_data = product_data.pop('color_variants', [])
                style_num = product_data.get('style_number', '')
                if not style_num:
                    continue

                try:
                    existing = Product.query.filter_by(style_number=style_num).first()
                    if existing:
                        # Preserve admin-set prices and active/inactive state
                        protected = {'base_price', 'wholesale_cost', 'is_active'}
                        for key, value in product_data.items():
                            if hasattr(existing, key) and value is not None and key not in protected:
                                setattr(existing, key, value)
                        product = existing
                        updated += 1
                    else:
                        product_data['is_active'] = True
                        product = Product(**product_data)
                        db.session.add(product)
                        added += 1

                    db.session.flush()

                    for variant_data in color_variants_data:
                        color_name = variant_data.get('color_name', '')
                        if not color_name:
                            continue

                        existing_variant = ProductColorVariant.query.filter_by(
                            product_id=product.id,
                            color_name=color_name
                        ).first()

                        if existing_variant:
                            existing_variant.front_image_url = variant_data.get('front_image') or existing_variant.front_image_url
                            existing_variant.back_image_url  = variant_data.get('back_image')  or existing_variant.back_image_url
                            # Catalog SOAP does not include warehouse qty — never wipe live stock.
                            from utils.stock import is_usable_inventory_payload
                            incoming_inv = variant_data.get('size_inventory')
                            if is_usable_inventory_payload(incoming_inv):
                                existing_variant.size_inventory = incoming_inv
                            existing_variant.last_synced     = datetime.utcnow()
                            variants_updated += 1
                        else:
                            db.session.add(ProductColorVariant(
                                product_id=product.id,
                                color_name=color_name,
                                front_image_url=variant_data.get('front_image'),
                                back_image_url=variant_data.get('back_image'),
                                size_inventory=variant_data.get('size_inventory'),
                                last_synced=datetime.utcnow()
                            ))
                            variants_added += 1

                    db.session.commit()

                except SanMarAuthError:
                    print("NIGHTLY SYNC ABORTED — SanMar auth failed mid-sync.", file=sys.stderr, flush=True)
                    db.session.rollback()
                    return
                except Exception as e:
                    print(f"  Error on {style_num}: {e}", file=sys.stderr, flush=True)
                    db.session.rollback()
                    continue

            print("=" * 80, file=sys.stderr, flush=True)
            print(f"NIGHTLY SYNC COMPLETE - {datetime.now()}", file=sys.stderr, flush=True)
            print(f"  Products added:         {added}", file=sys.stderr, flush=True)
            print(f"  Products updated:       {updated}", file=sys.stderr, flush=True)
            print(f"  Variants added:         {variants_added}", file=sys.stderr, flush=True)
            print(f"  Variants updated:       {variants_updated}", file=sys.stderr, flush=True)
            print(f"  Total products in DB:   {Product.query.count()}", file=sys.stderr, flush=True)
            print("=" * 80, file=sys.stderr, flush=True)

        except Exception as e:
            print(f"NIGHTLY SYNC FAILED: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)


def seed_catalog_if_empty(app):
    """
    Called once on startup: if the products table is empty (fresh PostgreSQL DB),
    run a full catalog sync immediately so the store is ready straight away.
    Only runs if SanMar credentials are configured.
    """
    with app.app_context():
        try:
            from models import Product
            from services.sanmar_api import check_credentials
            count = Product.query.count()
            if count == 0:
                cred_check = check_credentials()
                if cred_check['ok']:
                    print("Products table is empty — running initial SanMar catalog seed...", file=sys.stderr, flush=True)
                    sync_full_catalog_job(app)
                else:
                    print("Products table is empty but SanMar credentials not set — skipping auto-seed.", file=sys.stderr, flush=True)
            else:
                print(f"Products table has {count} rows — skipping initial seed.", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"Initial seed check failed: {e}", file=sys.stderr, flush=True)


def sync_ss_images_job(app):
    """
    Nightly job: fetch front/back ghost images for every BC product from S&S Activewear.
    Creates or updates ProductColorVariant records with S&S CDN image URLs.
    Runs at 2:00 AM daily (after SanMar sync).
    No web-request timeout — runs until complete.
    """
    with app.app_context():
        try:
            import os, re
            from pathlib import Path
            from datetime import datetime
            from models import db, Product, ProductColorVariant

            print("=" * 80, file=sys.stderr, flush=True)
            print(f"S&S IMAGE SYNC STARTED - {datetime.now()}", file=sys.stderr, flush=True)

            api_key = os.getenv('SSACTIVEWEAR_API_KEY', '').strip()
            account_number = os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER', '').strip()

            created = updated = skipped = 0

            # ── Phase 1: S&S Activewear API ────────────────────────────────────
            if api_key and account_number:
                try:
                    from services.ssactivewear_api import SSActivewearAPI
                    api = SSActivewearAPI(api_key=api_key, account_number=account_number)
                    cdn = 'https://cdn.ssactivewear.com/'

                    def _img(url):
                        if not url: return None
                        return url if url.startswith('http') else cdn + url.lstrip('/')

                    for product in Product.query.filter(Product.style_number.ilike('BC%')).all():
                        ss_style = product.style_number[2:] if product.style_number.upper().startswith('BC') else product.style_number
                        try:
                            ss_rows = api.get_products_by_style_number(ss_style) or api.get_products_by_style_number(product.style_number)
                            if not ss_rows:
                                skipped += 1
                                continue

                            color_map = {}
                            for row in ss_rows:
                                cname = (row.get('colorName') or '').strip()
                                if not cname: continue
                                k = cname.lower()
                                if k in color_map: continue
                                front = _img(row.get('ghostFrontImage') or row.get('colorFrontImage') or row.get('frontImage'))
                                back  = _img(row.get('ghostBackImage')  or row.get('colorBackImage')  or row.get('backImage'))
                                if front or back:
                                    color_map[k] = {'name': cname, 'front': front, 'back': back,
                                                    'hex': row.get('colorHex') or row.get('hex')}
                            if not color_map:
                                skipped += 1
                                continue

                            existing = {(v.color_name or '').lower(): v for v in ProductColorVariant.query.filter_by(product_id=product.id).all()}
                            changed = False
                            for k, imgs in color_map.items():
                                if k in existing:
                                    v = existing[k]
                                    if imgs['front'] and not v.front_image_url:
                                        v.front_image_url = imgs['front']; changed = True
                                    if imgs['back'] and not v.back_image_url:
                                        v.back_image_url = imgs['back']; changed = True
                                    if changed: updated += 1
                                else:
                                    db.session.add(ProductColorVariant(
                                        product_id=product.id,
                                        color_name=imgs['name'], color_hex=imgs.get('hex'),
                                        front_image_url=imgs['front'], back_image_url=imgs['back'],
                                        last_synced=datetime.utcnow(),
                                    ))
                                    created += 1
                                    changed = True

                            if changed:
                                if not product.front_mockup_template:
                                    ff = next((v['front'] for v in color_map.values() if v.get('front')), None)
                                    if ff: product.front_mockup_template = ff
                                db.session.commit()

                        except Exception as e:
                            db.session.rollback()
                            print(f"  S&S image error [{product.style_number}]: {e}", file=sys.stderr, flush=True)

                except Exception as e:
                    print(f"  S&S API init failed: {e}", file=sys.stderr, flush=True)
            else:
                print("  S&S skipped — no API credentials", file=sys.stderr, flush=True)

            # ── Phase 2: Fix local sanmar/ paths and link local images ─────────
            try:
                # Fix any variants with bare 'sanmar/...' path (missing /static/ prefix)
                bad_variants = ProductColorVariant.query.filter(
                    ProductColorVariant.front_image_url.like('sanmar/%')
                ).all()
                for v in bad_variants:
                    if v.front_image_url and not v.front_image_url.startswith('/'):
                        v.front_image_url = '/static/' + v.front_image_url
                    if v.back_image_url and not v.back_image_url.startswith('/') and v.back_image_url.startswith('sanmar/'):
                        v.back_image_url = '/static/' + v.back_image_url
                if bad_variants:
                    db.session.commit()
                    print(f"  Fixed {len(bad_variants)} bare sanmar/ paths", file=sys.stderr, flush=True)

                # Link any local static/sanmar/ images not yet in DB
                sanmar_dir = Path(app.root_path) / 'static' / 'sanmar'
                local_linked = 0
                if sanmar_dir.is_dir():
                    for style_folder in sanmar_dir.iterdir():
                        if not style_folder.is_dir(): continue
                        folder_name = style_folder.name
                        product = Product.query.filter(
                            db.or_(Product.style_number == 'BC' + folder_name, Product.style_number == folder_name)
                        ).first()
                        if not product: continue

                        file_map = {}
                        for f in style_folder.iterdir():
                            if not f.is_file(): continue
                            m = re.match(rf'^{re.escape(folder_name)}_(.+?)_(front|back)\.jpe?g$', f.name, re.IGNORECASE)
                            if not m: continue
                            key = m.group(1).replace('_', ' ').lower()
                            side = m.group(2).lower()
                            if key not in file_map: file_map[key] = {}
                            file_map[key][side] = f'/static/sanmar/{folder_name}/{f.name}'

                        existing = {(v.color_name or '').lower(): v for v in ProductColorVariant.query.filter_by(product_id=product.id).all()}
                        for color_key, paths in file_map.items():
                            if color_key in existing:
                                v = existing[color_key]
                                if paths.get('front'): v.front_image_url = paths['front']
                                if paths.get('back'):  v.back_image_url  = paths['back']
                            else:
                                db.session.add(ProductColorVariant(
                                    product_id=product.id,
                                    color_name=color_key.title(),
                                    front_image_url=paths.get('front'),
                                    back_image_url=paths.get('back'),
                                ))
                            local_linked += 1

                        if not product.front_mockup_template and file_map:
                            ff = next((v['front'] for v in file_map.values() if 'front' in v), None)
                            if ff: product.front_mockup_template = ff

                    db.session.commit()
                    print(f"  Local sanmar images linked: {local_linked}", file=sys.stderr, flush=True)

            except Exception as e:
                db.session.rollback()
                print(f"  Local image link error: {e}", file=sys.stderr, flush=True)

            print(f"S&S IMAGE SYNC COMPLETE — created {created}, updated {updated}, skipped {skipped}", file=sys.stderr, flush=True)
            print("=" * 80, file=sys.stderr, flush=True)

        except Exception as e:
            print(f"S&S IMAGE SYNC FAILED: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)


def sync_live_inventory_job(app):
    """Nightly warehouse qty refresh from SanMar and S&S for every active style."""
    with app.app_context():
        try:
            from services.inventory_sync import sync_all_inventory
            print("=" * 80, file=sys.stderr, flush=True)
            print(f"LIVE INVENTORY JOB STARTED - {datetime.now()}", file=sys.stderr, flush=True)
            sync_all_inventory()
        except Exception as e:
            print(f"LIVE INVENTORY JOB FAILED: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)


def init_scheduler(app):
    """
    Initialize the background scheduler.
    Only starts in production (not debug mode).
    """
    enabled = app.config.get('SCHEDULER_ENABLED', True)
    if not enabled:
        print("Scheduler disabled (SCHEDULER_ENABLED=False)", file=sys.stderr, flush=True)
        return None

    if app.debug:
        print("Scheduler disabled (debug mode)", file=sys.stderr, flush=True)
        return None

    try:
        # Seed the catalog immediately if the DB is empty (first deploy)
        seed_catalog_if_empty(app)

        scheduler = BackgroundScheduler(daemon=True)

        # Full catalog sync every night at 1:00 AM America/Chicago via SanMar
        scheduler.add_job(
            func=lambda: sync_full_catalog_job(app),
            trigger=CronTrigger(hour=1, minute=0, timezone=CHICAGO),
            id='nightly_catalog_sync',
            name='Nightly Bella+Canvas Catalog Sync (SanMar)',
            replace_existing=True
        )

        # S&S image fetch every night at 2:00 AM Chicago (after SanMar catalog)
        scheduler.add_job(
            func=lambda: sync_ss_images_job(app),
            trigger=CronTrigger(hour=2, minute=0, timezone=CHICAGO),
            id='nightly_ss_images',
            name='Nightly S&S Image Sync',
            replace_existing=True
        )

        # Live warehouse qty from SanMar + S&S at 3:00 AM Chicago
        scheduler.add_job(
            func=lambda: sync_live_inventory_job(app),
            trigger=CronTrigger(hour=3, minute=0, timezone=CHICAGO),
            id='nightly_live_inventory',
            name='Nightly Live Inventory Sync (SanMar + S&S)',
            replace_existing=True
        )

        # Also run S&S image sync once on startup (after a short delay)
        from apscheduler.triggers.date import DateTrigger
        from datetime import datetime, timedelta
        scheduler.add_job(
            func=lambda: sync_ss_images_job(app),
            trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=30)),
            id='startup_ss_images',
            name='Startup S&S Image Sync (one-time)',
            replace_existing=True
        )
        scheduler.add_job(
            func=lambda: sync_live_inventory_job(app),
            trigger=DateTrigger(run_date=datetime.now() + timedelta(seconds=20)),
            id='startup_live_inventory',
            name='Startup Live Inventory Sync (one-time)',
            replace_existing=True
        )

        scheduler.start()

        print("=" * 80, file=sys.stderr, flush=True)
        print("SCHEDULER STARTED", file=sys.stderr, flush=True)
        print("  - Nightly catalog sync (SanMar): 1:00 AM America/Chicago", file=sys.stderr, flush=True)
        print("  - Nightly S&S image sync: 2:00 AM America/Chicago", file=sys.stderr, flush=True)
        print("  - Nightly live inventory (SanMar + S&S): 3:00 AM America/Chicago", file=sys.stderr, flush=True)
        print("  - S&S image sync running in 30 seconds (startup)", file=sys.stderr, flush=True)
        print("  - Live inventory sync running in 20 seconds (startup)", file=sys.stderr, flush=True)
        print("=" * 80, file=sys.stderr, flush=True)

        import atexit
        atexit.register(lambda: scheduler.shutdown())

        return scheduler

    except Exception as e:
        print(f"ERROR: Failed to start scheduler: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None
