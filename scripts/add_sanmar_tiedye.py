"""
add_sanmar_tiedye.py
────────────────────
Adds Port & Company tie-dye styles from SanMar to the database:

  PC147     Tie-Dye Tee
  PC147Y    Youth Tie-Dye Tee
  LPC147V   Women's Tie-Dye V-Neck
  PC147LS   Tie-Dye Long Sleeve
  PC147YLS  Youth Tie-Dye Long Sleeve
  PC146     Tie-Dye Pullover Hooded Sweatshirt (regular / spiral)
  PC146Y    Youth Tie-Dye Pullover Hooded Sweatshirt
  PC145     Crystal Tie-Dye Tee
  PC144     Crystal Tie-Dye Pullover Hoodie

Run from project root:

    py -3.12 scripts/add_sanmar_tiedye.py --dry-run
    py -3.12 scripts/add_sanmar_tiedye.py

Then pull images:

    py -3.12 scripts/populate_brand_images.py --brands PC --cookie "YOUR_JSESSIONID"
"""
import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

ADULT_SIZES = json.dumps(["S", "M", "L", "XL", "2XL", "3XL", "4XL"])
LADIES_SIZES = json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"])
YOUTH_SIZES = json.dumps(["XS", "S", "M", "L", "XL"])

NEW_TIEDYE = [
    {
        'style_number': 'PC147',
        'name': 'Port & Company Tie-Dye Tee',
        'brand': 'Port & Company',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 28.00,
        'wholesale_cost': 12.40,
        'available_sizes': ADULT_SIZES,
        'description': (
            "Port & Company Tie-Dye Tee — a prepared-for-dye cotton blank with "
            "vibrant, one-of-a-kind color. Each shirt is unique, so group orders "
            "look coordinated without being identical. A favorite for festivals, "
            "camps, and school spirit."
        ),
        'fabric_details': '5.4 oz / 100% cotton; prepared-for-dye; tear-away label',
        'fit_guide': 'Unisex classic fit; true to size. Each garment has slight color variation from the tie-dye process.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147.pdf',
        'is_active': True,
        'is_customer_favorite': True,
    },
    {
        'style_number': 'PC147Y',
        'name': 'Port & Company Youth Tie-Dye Tee',
        'brand': 'Port & Company',
        'category': 'Tee',
        'age_group': 'youth',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 24.00,
        'wholesale_cost': 11.36,
        'available_sizes': YOUTH_SIZES,
        'description': (
            "Youth Tie-Dye Tee — the same groovy PC147 in kids' sizes. Perfect for "
            "camps, youth sports, family matching sets, and school spirit orders."
        ),
        'fabric_details': '5.4 oz / 100% cotton; prepared-for-dye; tear-away label',
        'fit_guide': 'Youth classic fit; sizes XS–XL. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147Y.pdf',
        'is_active': True,
        'is_customer_favorite': False,
    },
    {
        'style_number': 'LPC147V',
        'name': "Port & Company Women's Tie-Dye V-Neck Tee",
        'brand': 'Port & Company',
        'category': 'V-Neck Tee',
        'age_group': 'adult',
        'fit_type': "Women's",
        'neck_style': 'V-Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 28.00,
        'wholesale_cost': 12.40,
        'available_sizes': LADIES_SIZES,
        'description': (
            "Women's Tie-Dye V-Neck — side-seamed and contoured, with the same "
            "vibrant prepared-for-dye color as the unisex PC147. Great for matching "
            "group orders that need a women's cut."
        ),
        'fabric_details': '5.4 oz / 100% cotton; side seamed; prepared-for-dye',
        'fit_guide': "Women's contoured fit; true to size. Each garment has slight color variation.",
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/LPC147V.pdf',
        'is_active': True,
        'is_customer_favorite': False,
    },
    {
        'style_number': 'PC147LS',
        'name': 'Port & Company Tie-Dye Long Sleeve Tee',
        'brand': 'Port & Company',
        'category': 'Long Sleeve',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'base_price': 32.00,
        'wholesale_cost': 14.46,
        'available_sizes': ADULT_SIZES,
        'description': (
            "Tie-Dye Long Sleeve Tee — the PC147 look with rib-knit cuffs for cooler "
            "weather, camps, and fall events. Same unique color on every shirt."
        ),
        'fabric_details': '5.4 oz / 100% cotton; rib knit cuffs; prepared-for-dye',
        'fit_guide': 'Unisex classic fit; true to size. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147LS.pdf',
        'is_active': True,
        'is_customer_favorite': False,
    },
    {
        'style_number': 'PC147YLS',
        'name': 'Port & Company Youth Tie-Dye Long Sleeve Tee',
        'brand': 'Port & Company',
        'category': 'Long Sleeve',
        'age_group': 'youth',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'base_price': 28.00,
        'wholesale_cost': 12.80,
        'available_sizes': YOUTH_SIZES,
        'description': (
            "Youth Tie-Dye Long Sleeve Tee — the same vibrant prepared-for-dye "
            "PC147 look with rib-knit cuffs, sized for kids. Great for camps, "
            "fall spirit wear, and matching family group orders."
        ),
        'fabric_details': '5.4 oz / 100% cotton; rib knit cuffs; prepared-for-dye; tear-away label',
        'fit_guide': 'Youth classic fit; sizes XS–XL. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147YLS.pdf',
        'is_active': True,
        'is_customer_favorite': False,
    },
    {
        'style_number': 'PC146',
        'name': 'Port & Company Tie-Dye Pullover Hooded Sweatshirt',
        'brand': 'Port & Company',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 51.00,
        'wholesale_cost': 32.06,
        'available_sizes': ADULT_SIZES,
        'description': (
            "Port & Company Tie-Dye Pullover Hooded Sweatshirt — the classic spiral "
            "tie-dye hoodie (not crystal). Hand-dyed 80/20 fleece with a two-ply hood "
            "and pouch pocket. Perfect for group orders that want the regular PC147 look."
        ),
        'fabric_details': '7.8 oz / 80% cotton, 20% polyester fleece; prepared-for-dye; tear-away label',
        'fit_guide': 'Unisex classic fit; true to size. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC146.pdf',
        'is_active': True,
        'is_customer_favorite': True,
    },
    {
        'style_number': 'PC146Y',
        'name': 'Port & Company Youth Tie-Dye Pullover Hooded Sweatshirt',
        'brand': 'Port & Company',
        'category': 'Hoodie',
        'age_group': 'youth',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 45.00,
        'wholesale_cost': 24.00,
        'available_sizes': YOUTH_SIZES,
        'description': (
            "Youth Tie-Dye Pullover Hooded Sweatshirt — the regular (non-crystal) PC146 "
            "hoodie sized for kids. Hand-dyed fleece with a two-ply hood (no drawcord) "
            "and front pouch pocket."
        ),
        'fabric_details': '7.8 oz / 80% cotton, 20% polyester fleece; prepared-for-dye; no drawcord',
        'fit_guide': 'Youth classic fit; sizes XS–XL. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC146Y.pdf',
        'is_active': True,
        'is_customer_favorite': False,
    },
    {
        'style_number': 'PC145',
        'name': 'Port & Company Crystal Tie-Dye Tee',
        'brand': 'Port & Company',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 28.00,
        'wholesale_cost': 11.60,
        'available_sizes': ADULT_SIZES,
        'description': (
            "Crystal Tie-Dye Tee — individually hand-dyed so the pattern is a little "
            "different on every shirt. A softer crystal wash than the classic PC147 spiral."
        ),
        'fabric_details': '5.4 oz / 100% cotton; individually hand dyed; tear-away label',
        'fit_guide': 'Unisex classic fit; true to size. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC145.pdf',
        'is_active': True,
        'is_customer_favorite': False,
    },
    {
        'style_number': 'PC144',
        'name': 'Port & Company Crystal Tie-Dye Pullover Hoodie',
        'brand': 'Port & Company',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 56.00,
        'wholesale_cost': 31.02,
        'available_sizes': ADULT_SIZES,
        'description': (
            "Crystal Tie-Dye Pullover Hoodie — hand-dyed 80/20 fleece with a lined hood "
            "and pouch pocket. The matching hoodie for crystal tie-dye group orders."
        ),
        'fabric_details': '7.8 oz / 80% cotton, 20% polyester fleece; individually hand dyed',
        'fit_guide': 'Unisex classic fit; true to size. Each garment has slight color variation.',
        'spec_sheet_url': 'https://cdnm.sanmar.com/SpecSheetMeasurements/PC144.pdf',
        'is_active': True,
        'is_customer_favorite': True,
    },
]


def main():
    parser = argparse.ArgumentParser(description='Add Port & Company tie-dye styles from SanMar')
    parser.add_argument('--dry-run', action='store_true', help='Preview only — no DB writes')
    args = parser.parse_args()

    from app import create_app
    from models import db, Product

    app = create_app()
    with app.app_context():
        added = skipped = 0
        print(f"\n{'DRY RUN — ' if args.dry_run else ''}Adding {len(NEW_TIEDYE)} Port & Company tie-dye styles...\n")

        for data in NEW_TIEDYE:
            style = data['style_number']
            existing = Product.query.filter_by(style_number=style).first()
            if existing:
                print(f"  SKIP  {style:12s}  already in DB")
                skipped += 1
                continue

            print(f"  ADD   {style:12s}  {data['name']}")
            print(f"         wholesale=${data['wholesale_cost']:.2f}  retail=${data['base_price']:.2f}")
            added += 1
            if not args.dry_run:
                db.session.add(Product(**data))

        print(f"\nTotal: {added} to add, {skipped} already exist.")
        if args.dry_run:
            print("\n[DRY RUN] No changes made. Remove --dry-run to apply.")
            return

        db.session.commit()
        print("\nDone! Tie-dye styles are in the catalog.")
        print("Next: py -3.12 scripts/populate_brand_images.py --brands PC --cookie \"YOUR_JSESSIONID\"")


if __name__ == '__main__':
    main()
