"""
trim_bc_styles.py
─────────────────
Removes Bella+Canvas styles that are NOT in the curated keep list,
reducing the catalog from ~88 styles down to the 20 core best-sellers.

Run from project root in Cursor terminal:

    python scripts/trim_bc_styles.py --dry-run   # preview only
    python scripts/trim_bc_styles.py             # actually delete
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

# ── BC styles to KEEP ─────────────────────────────────────────────────────────
# Core bestsellers + trending women's Micro Rib styles (Y2K/baby tee aesthetic).
# Removed: true infant/toddler BC (covered by Rabbit Skins), garment-dyed BC
# (covered by Comfort Colors), and niche styles with low market demand.
BC_KEEP = {
    # Core unisex tees
    'BC3001',      # Unisex Jersey Short Sleeve Tee (#1 custom tee in the USA)
    'BC3001CVC',   # CVC Unisex Jersey Short Sleeve Tee (best for DTG)
    'BC3001Y',     # Youth Jersey Short Sleeve Tee
    'BC3001YCVC',  # Youth CVC Jersey Short Sleeve Tee
    'BC3005',      # Unisex Jersey Short Sleeve V-Neck Tee
    'BC3005CVC',   # CVC Unisex Jersey Short Sleeve V-Neck Tee
    'BC3413',      # Unisex Triblend Short Sleeve Tee (top 3 BC style)
    'BC3413Y',     # Youth Triblend Short Sleeve Tee
    # Tanks
    'BC3480',      # Unisex Jersey Tank
    'BC3480CVC',   # CVC Unisex Jersey Tank (great for DTG)
    # Long sleeve
    'BC3501',      # Unisex Jersey Long Sleeve Tee
    'BC3501CVC',   # CVC Unisex Jersey Long Sleeve Tee
    # Hoodies & sweatshirts
    'BC3719',      # Unisex Sponge Fleece Pullover Hooded Sweatshirt (#1 BC hoodie)
    'BC3719Y',     # Youth Sponge Fleece Pullover Hooded Sweatshirt
    'BC3739',      # Unisex Poly-Cotton Fleece Pullover Hooded Sweatshirt
    'BC3787',      # Unisex Sponge Fleece Pullover Crewneck Sweatshirt
    # Trending/boutique
    'BC3945',      # Unisex Sponge Fleece Short Sleeve Crop Tee (trending)
    'BC6400',      # Unisex Jersey Short Sleeve Tee (popular women's/unisex cut)
    'BC6400CVC',   # CVC Unisex Jersey Short Sleeve Tee
    'BC8800',      # Unisex Sponge Fleece Pullover Hooded Sweatshirt (newer)
    # Women's Micro Rib series — Y2K/baby tee aesthetic, very popular right now
    'BC1010',      # Women's Micro Rib Baby Tee
    'BC1012',      # Women's Micro Rib Spaghetti Strap Tank
    'BC1019',      # Women's Micro Rib Racer Tank
    'BC1080',      # Women's Baby Rib Tank
    'BC1200',      # Women's Micro Rib 3/4 Raglan Baby Tee
    'BC1201',      # Women's Micro Rib Raglan Baby Tee
    'BC1501',      # Women's Micro Rib Long Sleeve Baby Tee
}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Preview only — do not delete')
    args = parser.parse_args()

    from app import create_app
    from models import db, Product

    app = create_app()
    with app.app_context():
        bc_products = Product.query.filter(Product.style_number.like('BC%')).all()
        to_keep   = [p for p in bc_products if p.style_number in BC_KEEP]
        to_delete = [p for p in bc_products if p.style_number not in BC_KEEP]

        print(f"\nBC styles in DB:     {len(bc_products)}")
        print(f"BC styles to keep:   {len(to_keep)}")
        print(f"BC styles to remove: {len(to_delete)}\n")

        if to_delete:
            print("Styles being REMOVED:")
            for p in sorted(to_delete, key=lambda x: x.style_number):
                print(f"  {p.style_number:20s}  {p.name}")

        if to_keep:
            print(f"\nStyles KEEPING ({len(to_keep)}):")
            for p in sorted(to_keep, key=lambda x: x.style_number):
                print(f"  {p.style_number:20s}  {p.name}")

        if args.dry_run:
            print("\n[DRY RUN] No changes made. Remove --dry-run to apply.")
            return

        # Try to delete each product; if it has orders, deactivate instead
        deleted = deactivated = 0
        for p in to_delete:
            from sqlalchemy import text
            result = db.session.execute(
                text("SELECT COUNT(*) FROM order_item WHERE product_id = :pid"),
                {"pid": p.id}
            ).scalar()
            if result and result > 0:
                # Has orders — deactivate instead of delete
                p.is_active = False
                deactivated += 1
                print(f"  DEACTIVATED (has orders): {p.style_number}")
            else:
                db.session.delete(p)
                deleted += 1

        db.session.commit()
        print(f"\nDone! Deleted {deleted}, deactivated {deactivated} BC styles. {len(to_keep)} styles kept active.")


if __name__ == '__main__':
    main()
