"""
Background scheduler for automated tasks.
Runs a full Bella+Canvas catalog sync every night at 1 AM:
  - Adds any new Bella+Canvas styles from S&S Activewear
  - Updates inventory quantities on all existing products/variants
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import sys


def sync_full_catalog_job(app):
    """
    Nightly job: sync the complete Bella+Canvas catalog from S&S Activewear.
    Adds new styles and refreshes inventory on all existing ones.
    Runs at 1:00 AM daily.
    """
    with app.app_context():
        try:
            print("=" * 80, file=sys.stderr, flush=True)
            print(f"NIGHTLY CATALOG SYNC STARTED - {datetime.now()}", file=sys.stderr, flush=True)
            print("=" * 80, file=sys.stderr, flush=True)

            from services.ssactivewear_api import SSActivewearAPI
            from models import db, Product, ProductColorVariant

            api = SSActivewearAPI()
            products_data = api.sync_bella_canvas_catalog()

            if not products_data:
                print("WARNING: No products returned from S&S API.", file=sys.stderr, flush=True)
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
                        for key, value in product_data.items():
                            if hasattr(existing, key) and value is not None:
                                setattr(existing, key, value)
                        existing.is_active = True
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
                            existing_variant.side_image_url  = variant_data.get('side_image')  or existing_variant.side_image_url
                            existing_variant.size_inventory  = variant_data.get('size_inventory')
                            existing_variant.ss_color_id     = variant_data.get('color_id')
                            existing_variant.last_synced     = datetime.utcnow()
                            variants_updated += 1
                        else:
                            db.session.add(ProductColorVariant(
                                product_id=product.id,
                                color_name=color_name,
                                front_image_url=variant_data.get('front_image'),
                                back_image_url=variant_data.get('back_image'),
                                side_image_url=variant_data.get('side_image'),
                                size_inventory=variant_data.get('size_inventory'),
                                ss_color_id=variant_data.get('color_id'),
                                last_synced=datetime.utcnow()
                            ))
                            variants_added += 1

                    db.session.commit()

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
    """
    with app.app_context():
        try:
            from models import Product
            count = Product.query.count()
            if count == 0:
                print("Products table is empty - running initial catalog seed...", file=sys.stderr, flush=True)
                sync_full_catalog_job(app)
            else:
                print(f"Products table has {count} rows - skipping initial seed.", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"Initial seed check failed: {e}", file=sys.stderr, flush=True)


def init_scheduler(app):
    """
    Initialize the background scheduler.
    Only starts in Railway production (RAILWAY_ENVIRONMENT is set).
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

        # Full Bella+Canvas catalog sync every night at 1:00 AM
        scheduler.add_job(
            func=lambda: sync_full_catalog_job(app),
            trigger=CronTrigger(hour=1, minute=0),
            id='nightly_catalog_sync',
            name='Nightly Bella+Canvas Catalog Sync',
            replace_existing=True
        )

        scheduler.start()

        print("=" * 80, file=sys.stderr, flush=True)
        print("SCHEDULER STARTED", file=sys.stderr, flush=True)
        print("  - Nightly Bella+Canvas catalog sync: 1:00 AM daily", file=sys.stderr, flush=True)
        print("=" * 80, file=sys.stderr, flush=True)

        import atexit
        atexit.register(lambda: scheduler.shutdown())

        return scheduler

    except Exception as e:
        print(f"ERROR: Failed to start scheduler: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None
