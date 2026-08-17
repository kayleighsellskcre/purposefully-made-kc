"""
add_new_brands.py
─────────────────
Adds Product records for 7 new brands to the database.
All sourced through SanMar / SanMar Media Library.

Run from project root in Cursor terminal (after trim_bc_styles.py):

    python scripts/add_new_brands.py --dry-run   # preview only
    python scripts/add_new_brands.py             # actually insert
"""
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

# Size sets
ADULT_SIZES     = json.dumps(["S", "M", "L", "XL", "2XL", "3XL"])
ADULT_SIZES_XS  = json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL"])
TODDLER_SIZES   = json.dumps(["2T", "3T", "4T"])
INFANT_SIZES    = json.dumps(["NB", "6M", "12M", "18M", "24M"])

NEW_PRODUCTS = [

    # ── COMFORT COLORS ───────────────────────────────────────────────────────
    {
        'style_number': 'CC1717',
        'name': 'Comfort Colors Garment-Dyed Heavyweight Tee',
        'brand': 'Comfort Colors',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 18.99,
        'wholesale_cost': 8.50,
        'available_sizes': ADULT_SIZES,
        'description': 'The go-to garment-dyed tee. Ring-spun cotton with a vintage, lived-in feel and 60+ colorways. Trending #1 for boutique custom shops.',
        'fabric_details': '6.1 oz / 100% ring-spun cotton, garment-dyed',
        'is_customer_favorite': True,
    },
    {
        'style_number': 'CC1566',
        'name': "Comfort Colors Garment-Dyed Ladies Tee",
        'brand': 'Comfort Colors',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': "Women's",
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 18.99,
        'wholesale_cost': 8.50,
        'available_sizes': ADULT_SIZES,
        'description': "Women's cut of the iconic 1717. Same garment-dyed look, fitted silhouette. Great for coordinating sets.",
        'fabric_details': '6.1 oz / 100% ring-spun cotton, garment-dyed',
    },
    {
        'style_number': 'CC1466',
        'name': 'Comfort Colors Garment-Dyed Pullover Hoodie',
        'brand': 'Comfort Colors',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 34.99,
        'wholesale_cost': 16.00,
        'available_sizes': ADULT_SIZES,
        'description': 'Garment-dyed hoodie in matching colorways to the 1717 tee. Cotton-poly fleece with a vintage, broken-in feel.',
        'fabric_details': '8.5 oz / 80% cotton, 20% polyester fleece, garment-dyed',
    },

    # ── PORT & COMPANY ───────────────────────────────────────────────────────
    {
        'style_number': 'PC54',
        'name': 'Port & Company Core Cotton Tee',
        'brand': 'Port & Company',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 12.99,
        'wholesale_cost': 4.50,
        'available_sizes': ADULT_SIZES,
        'description': 'Budget-friendly workhorse tee. Great for large bulk orders, group orders, and events where value matters.',
        'fabric_details': '5.4 oz / 100% cotton',
    },
    {
        'style_number': 'PC78H',
        'name': 'Port & Company Core Fleece Pullover Hoodie',
        'brand': 'Port & Company',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 22.99,
        'wholesale_cost': 9.50,
        'available_sizes': ADULT_SIZES,
        'description': 'Value-priced pullover hoodie. Perfect for school spirit, charity, and team orders on a budget.',
        'fabric_details': '7.8 oz / 50% cotton, 50% polyester fleece',
    },
    {
        'style_number': 'LPC54',
        'name': "Port & Company Ladies Core Cotton Tee",
        'brand': 'Port & Company',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': "Women's",
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 12.99,
        'wholesale_cost': 4.50,
        'available_sizes': ADULT_SIZES,
        'description': "Women's fitted cut of the PC54. Same great value, flattering junior silhouette.",
        'fabric_details': '5.4 oz / 100% cotton',
    },

    # ── SPORT-TEK ────────────────────────────────────────────────────────────
    {
        'style_number': 'ST350',
        'name': 'Sport-Tek PosiCharge Competitor Tee',
        'brand': 'Sport-Tek',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 14.99,
        'wholesale_cost': 5.50,
        'available_sizes': ADULT_SIZES,
        'description': 'Moisture-wicking performance tee with PosiCharge color-lock technology. The go-to for sports teams, gyms, and athletic events.',
        'fabric_details': '3.8 oz / 100% polyester with PosiCharge technology',
    },
    {
        'style_number': 'ST254',
        'name': 'Sport-Tek PosiCharge Pullover Hooded Sweatshirt',
        'brand': 'Sport-Tek',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 27.99,
        'wholesale_cost': 12.00,
        'available_sizes': ADULT_SIZES,
        'description': 'Sport fleece hoodie with PosiCharge color-lock technology. Popular for team warmups and athletic programs.',
        'fabric_details': 'Sport-Wick fleece / 100% polyester',
    },
    {
        'style_number': 'LST350',
        'name': "Sport-Tek Ladies PosiCharge Competitor Tee",
        'brand': 'Sport-Tek',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': "Women's",
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 14.99,
        'wholesale_cost': 5.50,
        'available_sizes': ADULT_SIZES,
        'description': "Women's cut performance tee with moisture-wicking PosiCharge technology. Great for women's sports and fitness groups.",
        'fabric_details': '3.8 oz / 100% polyester with PosiCharge technology',
    },

    # ── DISTRICT ─────────────────────────────────────────────────────────────
    {
        'style_number': 'DT6000',
        'name': 'District Very Important Tee',
        'brand': 'District',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 14.99,
        'wholesale_cost': 5.75,
        'available_sizes': ADULT_SIZES_XS,
        'description': "District's signature style. Soft ring-spun cotton with a fashion-forward fit — popular for lifestyle and boutique-style custom shops.",
        'fabric_details': '4.3 oz / 100% combed ring-spun cotton',
        'is_customer_favorite': True,
    },
    {
        'style_number': 'DM130',
        'name': 'District Perfect Tri Tee',
        'brand': 'District',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 17.99,
        'wholesale_cost': 7.25,
        'available_sizes': ADULT_SIZES_XS,
        'description': 'Tri-blend tee with a heathered vintage look. Incredibly soft and popular for DTG printing and boutique brands.',
        'fabric_details': '4.5 oz / 50% polyester, 25% combed ring-spun cotton, 25% rayon',
    },
    {
        'style_number': 'DT8000',
        'name': 'District Re-Tee Pullover Hoodie',
        'brand': 'District',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 27.99,
        'wholesale_cost': 11.50,
        'available_sizes': ADULT_SIZES,
        'description': 'On-trend sustainable hoodie made from recycled polyester. Fits the fashion-forward District aesthetic perfectly.',
        'fabric_details': '60% recycled polyester, 40% cotton fleece',
    },

    # ── RABBIT SKINS ─────────────────────────────────────────────────────────
    {
        'style_number': 'RS3401',
        'name': 'Rabbit Skins Infant Fine Jersey Bodysuit',
        'brand': 'Rabbit Skins',
        'category': 'Bodysuit',
        'age_group': 'baby',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 10.99,
        'wholesale_cost': 4.00,
        'available_sizes': INFANT_SIZES,
        'description': 'Soft combed ring-spun cotton onesie with lap shoulders for easy dressing. The #1 custom infant item for boutique shops.',
        'fabric_details': '4.5 oz / 100% combed ring-spun cotton fine jersey',
        'is_customer_favorite': True,
    },
    {
        'style_number': 'RS3321',
        'name': 'Rabbit Skins Toddler Fine Jersey Tee',
        'brand': 'Rabbit Skins',
        'category': 'Tee',
        'age_group': 'toddler',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 10.99,
        'wholesale_cost': 4.00,
        'available_sizes': TODDLER_SIZES,
        'description': 'Soft and durable toddler tee in combed ring-spun cotton. Perfect for matching family sets and custom toddler apparel.',
        'fabric_details': '4.5 oz / 100% combed ring-spun cotton fine jersey',
    },
    {
        'style_number': 'RS4400',
        'name': 'Rabbit Skins Infant Baby Rib Bodysuit',
        'brand': 'Rabbit Skins',
        'category': 'Bodysuit',
        'age_group': 'baby',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 12.99,
        'wholesale_cost': 4.75,
        'available_sizes': INFANT_SIZES,
        'description': 'Stretchy baby rib knit onesie with lap shoulders. Snug, comfortable fit — a boutique-feel alternative to fine jersey.',
        'fabric_details': '5.5 oz / 100% combed ring-spun cotton baby rib knit',
    },

    # ── STANLEY/STELLA ───────────────────────────────────────────────────────
    {
        'style_number': 'STTU755',
        'name': 'Stanley/Stella Creator 2.0 Unisex Tee',
        'brand': 'Stanley/Stella',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 26.99,
        'wholesale_cost': 12.00,
        'available_sizes': ADULT_SIZES_XS,
        'description': 'Premium GOTS-certified organic cotton tee with a clean, relaxed boxy fit. For eco-conscious buyers who want quality they can feel.',
        'fabric_details': '5.5 oz / 100% GOTS-certified organic ring-spun cotton',
        'is_customer_favorite': True,
    },
    {
        'style_number': 'STTU169',
        'name': "Stanley/Stella Stella Muser Women's Tee",
        'brand': 'Stanley/Stella',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': "Women's",
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 24.99,
        'wholesale_cost': 11.00,
        'available_sizes': ADULT_SIZES,
        'description': "Relaxed organic cotton women's tee with an on-trend silhouette. Popular in the sustainable fashion and eco-boutique space.",
        'fabric_details': '5.3 oz / 100% GOTS-certified organic cotton',
    },
    {
        'style_number': 'STSW013',
        'name': 'Stanley/Stella Cruiser 2.0 Pullover Hoodie',
        'brand': 'Stanley/Stella',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 49.99,
        'wholesale_cost': 22.00,
        'available_sizes': ADULT_SIZES,
        'description': 'Premium organic cotton hoodie with a heavy, luxurious feel. Eco-conscious buyers who invest in quality will love this.',
        'fabric_details': '85% organic cotton, 15% recycled polyester fleece',
    },

    # ── GILDAN ───────────────────────────────────────────────────────────────
    {
        'style_number': 'G500',
        'name': 'Gildan Heavy Cotton Tee',
        'brand': 'Gildan',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'base_price': 9.99,
        'wholesale_cost': 3.00,
        'available_sizes': ADULT_SIZES,
        'description': 'The most widely sold wholesale tee. Best price point for large bulk orders, giveaways, church events, and nonprofits.',
        'fabric_details': '5.3 oz / 100% cotton (Sport Grey: 90/10 cotton/polyester)',
    },
    {
        'style_number': 'G18500',
        'name': 'Gildan Heavy Blend Pullover Hoodie',
        'brand': 'Gildan',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'base_price': 19.99,
        'wholesale_cost': 8.00,
        'available_sizes': ADULT_SIZES,
        'description': 'Best-selling value-tier sweatshirt. The go-to for school spirit, charity events, and nonprofit custom apparel.',
        'fabric_details': '8 oz / 50% cotton, 50% polyester fleece',
        'is_customer_favorite': True,
    },
    {
        'style_number': 'G18000',
        'name': 'Gildan Heavy Blend Crewneck Sweatshirt',
        'brand': 'Gildan',
        'category': 'Sweatshirt',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'base_price': 18.99,
        'wholesale_cost': 7.50,
        'available_sizes': ADULT_SIZES,
        'description': 'Classic crewneck sweatshirt at an unbeatable price. Popular for churches, school groups, and community organizations.',
        'fabric_details': '8 oz / 50% cotton, 50% polyester fleece',
    },
]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Preview only — do not insert')
    args = parser.parse_args()

    from app import create_app
    from models import db, Product

    app = create_app()
    with app.app_context():
        added = skipped = 0

        print(f"\nAdding {len(NEW_PRODUCTS)} new brand products...\n")
        for data in NEW_PRODUCTS:
            existing = Product.query.filter_by(style_number=data['style_number']).first()
            if existing:
                print(f"  SKIP  {data['style_number']:12s}  already in DB")
                skipped += 1
                continue

            print(f"  ADD   {data['style_number']:12s}  {data['name']}")
            added += 1
            if not args.dry_run:
                db.session.add(Product(**data))

        print(f"\nTotal: {added} to add, {skipped} already exist.")

        if args.dry_run:
            print("[DRY RUN] No changes made. Remove --dry-run to apply.")
            return

        db.session.commit()
        print("Done! All new products added to database.")
        print("\nNext step: run populate_brand_images.py to pull images from SanMar Media Library.")


if __name__ == '__main__':
    main()
