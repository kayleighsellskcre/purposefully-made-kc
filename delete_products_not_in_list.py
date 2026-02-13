"""Delete all products except those with these style numbers: 3001, 3413, 3719, 3729, 3901, 3501, 3945, 4719, 4711, 6400, 3513, 3911"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KEEP_STYLE_NUMBERS = ['3001', '3413', '3719', '3729', '3901', '3501', '3945', '4719', '4711', '6400', '3513', '3911']

def style_should_keep(style_number):
    """Check if style_number contains any of the keep numbers."""
    if not style_number:
        return False
    sn = str(style_number)
    return any(keep in sn for keep in KEEP_STYLE_NUMBERS)

def main():
    from app import create_app
    from models import db, Product, ProductColorVariant

    app = create_app()
    with app.app_context():
        all_products = Product.query.all()
        to_delete = [p for p in all_products if not style_should_keep(p.style_number)]
        to_keep = [p for p in all_products if style_should_keep(p.style_number)]

        print(f"Products to KEEP ({len(to_keep)}):")
        for p in to_keep:
            print(f"  - {p.style_number}: {p.name}")

        print(f"\nProducts to DELETE ({len(to_delete)}):")
        deleted = 0
        skipped_has_orders = 0
        for p in to_delete:
            order_count = p.order_items.count()
            if order_count > 0:
                print(f"  SKIP {p.style_number}: {p.name} (has {order_count} order items - cannot delete)")
                skipped_has_orders += 1
            else:
                # Delete color variants first (cascade should handle, but ensure)
                ProductColorVariant.query.filter_by(product_id=p.id).delete()
                db.session.delete(p)
                print(f"  DELETED {p.style_number}: {p.name}")
                deleted += 1

        db.session.commit()
        print(f"\nDone. Deleted: {deleted}, Skipped (has orders): {skipped_has_orders}")

if __name__ == '__main__':
    main()
