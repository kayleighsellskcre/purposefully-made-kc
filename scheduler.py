"""
Background scheduler for automated tasks
Sets up daily inventory sync and other scheduled jobs
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import sys


def sync_inventory_job(app):
    """
    Background job to sync inventory from S&S Activewear API
    Runs daily at 1 AM
    """
    with app.app_context():
        try:
            print("="*80, file=sys.stderr, flush=True)
            print(f"SCHEDULED INVENTORY SYNC STARTED - {datetime.now()}", file=sys.stderr, flush=True)
            print("="*80, file=sys.stderr, flush=True)
            
            from services.ssactivewear_api import SSActivewearAPI
            from models import db, Product, ProductColorVariant
            
            # Initialize API client
            api = SSActivewearAPI()
            
            # Get all active products
            products = Product.query.filter_by(is_active=True).all()
            
            total_updated = 0
            total_colors = 0
            
            for product in products:
                try:
                    print(f"Syncing {product.style_number}...", file=sys.stderr, flush=True)
                    
                    # Fetch latest data from S&S
                    style_data = api.fetch_style_data_by_style_number(product.style_number)
                    
                    if not style_data or 'color_variants' not in style_data:
                        print(f"  No data for {product.style_number}", file=sys.stderr, flush=True)
                        continue
                    
                    # Update color variants with fresh inventory
                    for variant_data in style_data['color_variants']:
                        color_name = variant_data['color_name']
                        size_inventory = variant_data.get('sizes', {})
                        
                        # Find or create variant
                        variant = ProductColorVariant.query.filter_by(
                            product_id=product.id,
                            color_name=color_name
                        ).first()
                        
                        if variant:
                            # Update existing
                            import json
                            variant.size_inventory = json.dumps(size_inventory)
                            variant.last_synced = datetime.utcnow()
                            total_colors += 1
                        else:
                            # Create new variant
                            import json
                            new_variant = ProductColorVariant(
                                product_id=product.id,
                                color_name=color_name,
                                front_image_url=variant_data.get('front_image'),
                                back_image_url=variant_data.get('back_image'),
                                side_image_url=variant_data.get('side_image'),
                                size_inventory=json.dumps(size_inventory),
                                ss_color_id=variant_data.get('color_id'),
                                last_synced=datetime.utcnow()
                            )
                            db.session.add(new_variant)
                            total_colors += 1
                    
                    total_updated += 1
                    db.session.commit()
                    
                except Exception as e:
                    print(f"  Error syncing {product.style_number}: {e}", file=sys.stderr, flush=True)
                    db.session.rollback()
                    continue
            
            print("="*80, file=sys.stderr, flush=True)
            print(f"SYNC COMPLETE: {total_updated} products, {total_colors} color variants updated", file=sys.stderr, flush=True)
            print(f"Completed at {datetime.now()}", file=sys.stderr, flush=True)
            print("="*80, file=sys.stderr, flush=True)
            
        except Exception as e:
            print(f"SCHEDULED SYNC FAILED: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()


def init_scheduler(app):
    """
    Initialize background scheduler with all scheduled jobs
    """
    # Only start scheduler in production or if explicitly enabled
    # Don't start in debug mode to avoid duplicate jobs
    if app.config.get('SCHEDULER_ENABLED', True) and not app.debug:
        scheduler = BackgroundScheduler(daemon=True)
        
        # Add daily inventory sync at 1 AM
        scheduler.add_job(
            func=lambda: sync_inventory_job(app),
            trigger=CronTrigger(hour=1, minute=0),  # 1:00 AM daily
            id='daily_inventory_sync',
            name='Daily S&S Inventory Sync',
            replace_existing=True
        )
        
        # Start the scheduler
        scheduler.start()
        
        print("="*80, file=sys.stderr, flush=True)
        print("SCHEDULER STARTED", file=sys.stderr, flush=True)
        print("Scheduled Jobs:", file=sys.stderr, flush=True)
        print("  - Daily Inventory Sync: 1:00 AM", file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        
        # Shut down the scheduler when exiting the app
        import atexit
        atexit.register(lambda: scheduler.shutdown())
        
        return scheduler
    else:
        print("Scheduler disabled (debug mode or SCHEDULER_ENABLED=False)", file=sys.stderr, flush=True)
        return None
