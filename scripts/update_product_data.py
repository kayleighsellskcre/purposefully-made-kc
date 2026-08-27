"""
update_product_data.py
──────────────────────
Populates wholesale_cost, base_price, fabric_details, description,
fit_guide, and spec_sheet_url for all 48 active products.

Sources:
  - Wholesale costs: SanMar/distributor pricing (1–11 pc tier)
  - Retail prices: garment + DTF print + margin (competitive KC market)
  - Specs: brand product pages & SanMar catalog

Run from project root in Cursor terminal:
    py -3.12 scripts/update_product_data.py
"""

import os
import sys

import psycopg2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT DATA
# Keys: style_number
# Values: (wholesale_cost, base_price, fabric_details, description, fit_guide, spec_sheet_url)
# ─────────────────────────────────────────────────────────────────────────────
PRODUCTS = {

    # ── BELLA+CANVAS — Women's Micro Rib ─────────────────────────────────────
    'BC1010': (
        11.38, 28.00,
        '95% combed and ring-spun cotton, 5% spandex; 4.2 oz micro-rib knit',
        "The Micro Rib Baby Tee is a Y2K-inspired, slim-fit cropped tee with a soft micro-rib texture that stretches with you. The slightly cropped length and form-fitting silhouette make it one of the most requested styles right now.",
        "Women's slim fit; runs true to size. Crop length hits above the hip.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC1010.pdf',
    ),
    'BC1012': (
        10.18, 26.00,
        '95% combed and ring-spun cotton, 5% spandex; 4.2 oz micro-rib knit',
        "The Micro Rib Spaghetti Strap Tank features ultra-thin adjustable straps and a sleek micro-rib texture. Fitted and figure-flattering for warm-weather looks.",
        "Women's slim fit; runs true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC1012.pdf',
    ),
    'BC1019': (
        10.18, 26.00,
        '95% combed and ring-spun cotton, 5% spandex; 4.2 oz micro-rib knit',
        "The Micro Rib Racer Tank has a racerback cut and micro-rib texture that moves with you. Great for working out or layering.",
        "Women's slim fit; runs true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC1019.pdf',
    ),
    'BC1080': (
        9.98, 25.00,
        '95% combed and ring-spun cotton, 5% spandex; baby rib knit',
        "A minimal, fitted tank with a baby rib knit that's soft and stretchy. Simple and wearable every day.",
        "Women's slim fit; runs true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC1080.pdf',
    ),
    'BC1200': (
        13.58, 32.00,
        '95% combed and ring-spun cotton, 5% spandex; 4.2 oz micro-rib knit',
        "The Micro Rib 3/4 Raglan Baby Tee combines a trendy raglan sleeve with the popular micro-rib fabric. Contrast raglan sleeves add a sporty-retro vibe.",
        "Women's slim fit; runs true to size. Crop length.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC1200.pdf',
    ),
    'BC1201': (
        12.38, 30.00,
        '95% combed and ring-spun cotton, 5% spandex; 4.2 oz micro-rib knit',
        "The Micro Rib Raglan Baby Tee features contrast raglan sleeves and a micro-rib body for a retro athletic look with a modern fitted silhouette.",
        "Women's slim fit; runs true to size. Crop length.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC1201.pdf',
    ),
    'BC1501': (
        12.98, 32.00,
        '95% combed and ring-spun cotton, 5% spandex; 4.2 oz micro-rib knit',
        "The Micro Rib Long Sleeve Baby Tee brings the same fitted micro-rib look into a long sleeve. Perfect for layering in cooler months.",
        "Women's slim fit; runs true to size. Crop length.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC1501.pdf',
    ),

    # ── BELLA+CANVAS — Core Tees ──────────────────────────────────────────────
    'BC3001': (
        8.78, 24.00,
        '100% Airlume combed and ring-spun cotton; 4.2 oz',
        "The #1 custom t-shirt in the US. Bella+Canvas BC3001 is softer, better-fitting, and holds prints more vividly than any standard blank. A true essential.",
        "Unisex sizing; true to size. Slightly longer body.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001.pdf',
    ),
    'BC3001CVC': (
        10.18, 27.00,
        '52% combed and ring-spun cotton, 48% polyester; 4.2 oz CVC jersey',
        "The CVC version of the iconic BC3001. The poly-cotton blend creates a subtle heathered look that makes DTF prints pop with extra dimension.",
        "Unisex sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001CVC.pdf',
    ),
    'BC3001Y': (
        7.58, 22.00,
        '100% Airlume combed and ring-spun cotton; 4.2 oz',
        "All the softness of the adult BC3001 in a youth cut. Perfect for kids who deserve the same quality as their parents.",
        "Youth sizing; runs true to youth size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001Y.pdf',
    ),
    'BC3001YCVC': (
        9.18, 25.00,
        '52% combed and ring-spun cotton, 48% polyester; 4.2 oz CVC jersey',
        "Youth version of the CVC tee — soft, heathered, and great for DTF printing. Made for the youngest members of the crew.",
        "Youth sizing; runs true to youth size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3001YCVC.pdf',
    ),
    'BC3005': (
        9.18, 25.00,
        '100% Airlume combed and ring-spun cotton; 4.2 oz',
        "The V-Neck version of the BC3001 — same incredibly soft cotton, just with a flattering v-neck collar for a slightly more dressed-up look.",
        "Unisex sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3005.pdf',
    ),
    'BC3005CVC': (
        10.78, 27.00,
        '52% combed and ring-spun cotton, 48% polyester; 4.2 oz CVC jersey',
        "CVC V-Neck tee with a heathered look and buttery-soft feel. Great for designs with fine detail thanks to the smooth print surface.",
        "Unisex sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3005CVC.pdf',
    ),
    'BC3413': (
        12.38, 30.00,
        '50% polyester, 25% combed and ring-spun cotton, 25% rayon; 3.8 oz triblend jersey',
        "The BC3413 Triblend is feather-light, impossibly soft, and has a natural heathered look. One of the top 3 Bella+Canvas styles for a reason — this one gets complimented.",
        "Unisex sizing; runs slightly fitted. Size up if between sizes.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3413.pdf',
    ),
    'BC3413Y': (
        10.78, 27.00,
        '50% polyester, 25% combed and ring-spun cotton, 25% rayon; 3.8 oz triblend jersey',
        "The youth Triblend — same dreamy fabric as the adult version, sized for kids. Lightweight and breathable for active little ones.",
        "Youth sizing; runs slightly fitted.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3413Y.pdf',
    ),
    'BC3480': (
        8.98, 23.00,
        '100% Airlume combed and ring-spun cotton; 4.2 oz',
        "A clean, relaxed tank top with the signature BC softness. Great for summer or gym looks with a custom print.",
        "Unisex sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3480.pdf',
    ),
    'BC3480CVC': (
        10.18, 26.00,
        '52% combed and ring-spun cotton, 48% polyester; 4.2 oz CVC jersey',
        "The CVC tank with a heathered finish that makes colors look richer. Ideal for DTF printing with vibrant designs.",
        "Unisex sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3480CVC.pdf',
    ),
    'BC3501': (
        11.98, 29.00,
        '100% Airlume combed and ring-spun cotton; 4.2 oz',
        "The long sleeve version of the legendary BC3001. Same incredible softness and print quality, built for cooler weather.",
        "Unisex sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3501.pdf',
    ),
    'BC3501CVC': (
        13.38, 32.00,
        '52% combed and ring-spun cotton, 48% polyester; 4.2 oz CVC jersey',
        "Long sleeve CVC tee with the perfect amount of stretch and a heathered look. Exceptional for fall and winter custom designs.",
        "Unisex sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3501CVC.pdf',
    ),
    'BC3719': (
        26.38, 52.00,
        '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        "The #1 Bella+Canvas hoodie. The sponge fleece is thick, warm, and extraordinarily soft — the kind of hoodie people wear until it falls apart. DTF prints look stunning on it.",
        "Unisex sizing; true to size. Relaxed fit.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3719.pdf',
    ),
    'BC3719Y': (
        23.98, 48.00,
        '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        "Youth version of the iconic BC3719 hoodie. Same sponge fleece warmth, sized for kids who want to match the grown-ups.",
        "Youth sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3719Y.pdf',
    ),
    'BC3739': (
        30.38, 58.00,
        '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        "Full-zip hoodie in Bella+Canvas's legendary sponge fleece. Versatile, warm, and a perfect canvas for custom prints on the back or chest.",
        "Unisex sizing; true to size. Relaxed fit.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3739.pdf',
    ),
    'BC3787': (
        23.18, 46.00,
        '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        "The Sponge Fleece Crewneck Sweatshirt — all the warmth and softness of the BC hoodie without the hood. A wardrobe classic that looks great with any design.",
        "Unisex sizing; true to size. Relaxed fit.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3787.pdf',
    ),
    'BC3901': (
        22.38, 45.00,
        '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        "Unisex Sponge Fleece Raglan Crewneck — the classic Bella+Canvas crew with raglan sleeves. Soft, warm, and perfect for school spirit and team orders.",
        "Unisex sizing; true to size. Relaxed fit.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3901.pdf',
    ),
    'BC3901Y': (
        20.98, 42.00,
        '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        "Youth Sponge Fleece Raglan Crewneck — the same soft sponge fleece as the adult BC3901, sized for kids who want to match the grown-ups.",
        "Youth sizing; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3901Y.pdf',
    ),
    'BC3945': (
        24.98, 48.00,
        '52% combed and ring-spun cotton, 48% polyester sponge fleece; 7.2 oz',
        "The Drop Shoulder Sweatshirt is an oversized, boxy fleece with dropped shoulders for that trendy streetwear silhouette. Cozy and fashion-forward.",
        "Unisex oversized fit; size down for a more fitted look.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC3945.pdf',
    ),
    'BC6400': (
        9.58, 25.00,
        '100% Airlume combed and ring-spun cotton; 4.2 oz',
        "The Women's Relaxed Jersey Tee is slightly wider and longer than the unisex BC3001 — a more comfortable, lived-in fit that's still incredibly soft.",
        "Women's relaxed fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC6400.pdf',
    ),
    'BC6400CVC': (
        11.18, 27.00,
        '52% combed and ring-spun cotton, 48% polyester; 4.2 oz CVC jersey',
        "Women's Relaxed CVC Tee with a heathered finish and relaxed silhouette. Effortlessly comfortable with a look that pairs well with any design.",
        "Women's relaxed fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC6400CVC.pdf',
    ),
    'BC8800': (
        11.98, 28.00,
        '65% polyester, 35% viscose; 3.7 oz',
        "The Women's Flowy Racerback Tank has a flowy, drapey silhouette that moves beautifully. Lightweight and perfect for warm-weather events.",
        "Women's flowy/relaxed fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/BC8800.pdf',
    ),

    # ── COMFORT COLORS ────────────────────────────────────────────────────────
    'CC1717': (
        14.78, 34.00,
        '100% ring-spun cotton; 6.1 oz; garment-dyed',
        "The Comfort Colors 1717 is THE garment-dyed tee. Washed to perfection for a broken-in, vintage feel straight out of the bag. The heavyweight fabric and pigment-dyed finish give it a look no other blank can replicate.",
        "Unisex relaxed fit; runs slightly large. Size down for a more fitted look.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/CC1717.pdf',
    ),
    'CC1566': (
        34.98, 62.00,
        '100% ring-spun cotton; 8.5 oz; garment-dyed',
        "The Comfort Colors Garment-Dyed Pullover Hoodie. Heavyweight, pigment-washed fleece with that vintage, worn-in look. The colors are rich and unique — no two are exactly alike.",
        "Unisex relaxed fit; runs slightly large. Size down for a more fitted look.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/CC1566.pdf',
    ),
    'CC1466': (
        28.98, 54.00,
        '100% ring-spun cotton; 9.5 oz; garment-dyed',
        "The Comfort Colors Garment-Dyed Crewneck Sweatshirt. The heaviest fleece we carry — thick, warm, and with that unmistakable pigment-dyed character.",
        "Unisex relaxed fit; runs slightly large. Size down for a more fitted look.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/CC1466.pdf',
    ),

    # ── PORT & COMPANY ────────────────────────────────────────────────────────
    'PC54': (
        5.98, 22.00,
        '100% cotton; 5.4 oz',
        "Port & Company's Core Cotton Tee is a reliable, budget-friendly blank with a classic fit. Great for large group orders where price matters without sacrificing quality.",
        "Unisex classic fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC54.pdf',
    ),
    'LPC54': (
        5.98, 22.00,
        '100% cotton; 5.4 oz',
        "The ladies' cut of the Core Cotton Tee — a slightly more fitted silhouette with the same reliable, affordable quality.",
        "Women's classic fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/LPC54.pdf',
    ),
    'PC78H': (
        17.98, 40.00,
        '50% cotton, 50% polyester; 7.8 oz fleece',
        "Port & Company Core Fleece Hoodie — the go-to budget hoodie for large group orders. Solid construction, good weight, and great for DTF printing.",
        "Unisex classic fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC78H.pdf',
    ),
    'PC147': (
        12.40, 28.00,
        '100% cotton; 5.4 oz; prepared-for-dye tie-dye',
        "Port & Company Tie-Dye Tee — a prepared-for-dye cotton blank with vibrant, one-of-a-kind color. Each shirt is unique, so group orders look coordinated without being identical.",
        "Unisex classic fit; true to size. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147.pdf',
    ),
    'PC147Y': (
        11.36, 24.00,
        '100% cotton; 5.4 oz; prepared-for-dye tie-dye',
        "Youth Tie-Dye Tee — the same groovy PC147 in kids' sizes. Perfect for camps, youth sports, and family matching sets.",
        "Youth classic fit; sizes XS–XL. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147Y.pdf',
    ),
    'LPC147V': (
        12.40, 28.00,
        '100% cotton; 5.4 oz; prepared-for-dye tie-dye',
        "Women's Tie-Dye V-Neck — side-seamed and contoured, with the same vibrant prepared-for-dye color as the unisex PC147.",
        "Women's contoured fit; true to size. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/LPC147V.pdf',
    ),
    'PC147LS': (
        14.46, 32.00,
        '100% cotton; 5.4 oz; prepared-for-dye tie-dye',
        "Tie-Dye Long Sleeve Tee — the PC147 look with rib-knit cuffs for cooler weather, camps, and fall events.",
        "Unisex classic fit; true to size. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147LS.pdf',
    ),
    'PC147YLS': (
        12.80, 28.00,
        '100% cotton; 5.4 oz; prepared-for-dye tie-dye; rib knit cuffs',
        "Youth Tie-Dye Long Sleeve Tee — vibrant prepared-for-dye color with rib-knit cuffs, sized for kids. Perfect for camps and fall spirit wear.",
        "Youth classic fit; sizes XS–XL. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC147YLS.pdf',
    ),
    'PC146': (
        32.06, 51.00,
        '80% cotton, 20% polyester; 7.8 oz fleece; prepared-for-dye tie-dye',
        "Port & Company Tie-Dye Pullover Hooded Sweatshirt — the classic spiral tie-dye hoodie (not crystal). Hand-dyed fleece with a two-ply hood and pouch pocket.",
        "Unisex classic fit; true to size. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC146.pdf',
    ),
    'PC146Y': (
        24.00, 45.00,
        '80% cotton, 20% polyester; 7.8 oz fleece; prepared-for-dye tie-dye; no drawcord',
        "Youth Tie-Dye Pullover Hooded Sweatshirt — the regular (non-crystal) PC146 hoodie sized for kids. Pairs with the youth PC147Y tee.",
        "Youth classic fit; sizes XS–XL. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC146Y.pdf',
    ),
    'PC145': (
        11.60, 28.00,
        '100% cotton; 5.4 oz; crystal tie-dye',
        "Crystal Tie-Dye Tee — individually hand-dyed so the pattern is a little different on every shirt. A softer crystal wash than the classic PC147 spiral.",
        "Unisex classic fit; true to size. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC145.pdf',
    ),
    'PC144': (
        31.02, 56.00,
        '80% cotton, 20% polyester; 7.8 oz fleece; crystal tie-dye',
        "Crystal Tie-Dye Pullover Hoodie — hand-dyed 80/20 fleece with a lined hood and pouch pocket. The matching hoodie for crystal tie-dye group orders.",
        "Unisex classic fit; true to size. Slight color variation is part of the tie-dye process.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/PC144.pdf',
    ),

    # ── SPORT-TEK ─────────────────────────────────────────────────────────────
    'ST350': (
        8.98, 28.00,
        '100% polyester; 3.8 oz; PosiCharge technology',
        "The Sport-Tek PosiCharge Competitor Tee is a moisture-wicking performance top built for athletes. PosiCharge technology locks in color and keeps your logo looking sharp even after hard workouts.",
        "Unisex athletic fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/ST350.pdf',
    ),
    'LST350': (
        8.98, 28.00,
        '100% polyester; 3.8 oz; PosiCharge technology',
        "Ladies' PosiCharge Competitor Tee — the same moisture-wicking performance as the men's version in a more fitted silhouette.",
        "Women's athletic fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/LST350.pdf',
    ),
    'ST254': (
        26.98, 54.00,
        '100% polyester interlock; PosiCharge technology',
        "The PosiCharge Competitor 1/4-Zip Pullover — a sleek performance layering piece. Great for team staff, coaches, or anyone who wants a professional athletic look.",
        "Unisex athletic fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/ST254.pdf',
    ),

    # ── DISTRICT ──────────────────────────────────────────────────────────────
    'DT6000': (
        8.18, 26.00,
        '60% combed ring-spun cotton, 40% polyester; 4.3 oz',
        "The District Very Important Tee is a soft, retail-quality blank that blends cotton comfort with just enough poly for durability. A crowd-pleasing everyday tee.",
        "Unisex modern fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/DT6000.pdf',
    ),
    'DM130': (
        24.98, 50.00,
        '50% cotton, 50% polyester fleece; 7 oz',
        "The District Flex Fleece Hoodie has a smooth, flexible fleece that feels more like a fashion hoodie than a standard blank. Soft, fitted, and modern.",
        "Unisex modern fit; runs slightly fitted. Size up for a relaxed look.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/DM130.pdf',
    ),
    'DT8000': (
        9.18, 27.00,
        '50% recycled polyester, 50% recycled cotton; 4.5 oz Re-Tee® fabric',
        "The District Re-Tee® is made from 100% recycled materials without sacrificing softness or print quality. A feel-good choice for eco-conscious customers.",
        "Unisex modern fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/DT8000.pdf',
    ),

    # ── RABBIT SKINS ─────────────────────────────────────────────────────────
    'RS3321': (
        6.98, 22.00,
        '100% combed and ring-spun cotton; 4.5 oz',
        "Rabbit Skins Infant Short Sleeve Tee — a super-soft baby tee made from combed ring-spun cotton. Perfect for custom baby gifts, sibling shirts, and the tiniest fans.",
        "Infant sizing (6M–24M); runs true to infant size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/RS3321.pdf',
    ),
    'RS4400': (
        14.98, 32.00,
        '100% combed and ring-spun cotton; 4.5 oz',
        "Rabbit Skins Infant Layette Set — includes an infant bodysuit, bib, and cap, all in matching soft cotton. The cutest custom baby gift set we offer.",
        "Infant sizing (6M–18M); includes bodysuit, bib, and cap.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/RS4400.pdf',
    ),

    # ── STANLEY/STELLA ────────────────────────────────────────────────────────
    'STTU755': (
        19.98, 44.00,
        '100% organic ring-spun cotton; 5.3 oz; GOTS certified',
        "The Stanley/Stella Creator Tee is a premium organic cotton blank with a relaxed, boxy fit and a beautifully soft hand feel. GOTS certified and responsibly made in Bangladesh.",
        "Unisex relaxed/boxy fit; size down for a more fitted look.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/STTU755.pdf',
    ),
    'STTU169': (
        17.98, 40.00,
        '100% organic ring-spun cotton; 4.6 oz; GOTS certified',
        "The Stanley/Stella Rocker Tee is a lighter organic cotton option with a slightly more fitted cut than the Creator. Perfect for an everyday organic tee with a clean look.",
        "Unisex slightly fitted; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/STTU169.pdf',
    ),
    'STSW013': (
        48.98, 85.00,
        '85% organic combed cotton, 15% recycled polyester; GOTS certified zip hoodie',
        "The Stanley/Stella Cooper Zip Hoodie is a premium eco-friendly zip hoodie made from organic and recycled materials. A responsible choice that doesn't compromise on feel or style.",
        "Unisex relaxed fit; true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/STSW013.pdf',
    ),

    # ── GILDAN ────────────────────────────────────────────────────────────────
    'G64000': (
        5.78, 21.00,
        '100% ring-spun cotton; 4.5 oz Softstyle jersey',
        "Gildan Softstyle is a step above the standard Gildan — ring-spun cotton gives it a noticeably softer, smoother hand feel. Great for budget-friendly group orders where comfort still matters.",
        "Unisex classic fit; runs true to size.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/G64000.pdf',
    ),
    'G18500': (
        15.98, 36.00,
        '50% cotton, 50% polyester; 8 oz Heavy Blend™ fleece',
        "Gildan Heavy Blend Pullover Hoodie — the most popular hoodie at this price point. Thick, warm, and a great canvas for custom prints. The go-to choice for affordable group orders.",
        "Unisex classic fit; runs slightly large.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/G18500.pdf',
    ),
    'G18000': (
        13.98, 32.00,
        '50% cotton, 50% polyester; 8 oz Heavy Blend™ fleece',
        "Gildan Heavy Blend Crewneck Sweatshirt — same quality fleece as the G18500 hoodie, in a classic crewneck. Warm, durable, and budget-friendly.",
        "Unisex classic fit; runs slightly large.",
        'https://cdnm.sanmar.com/SpecSheetMeasurements/G18000.pdf',
    ),
}


def main():
    db_url = os.environ.get('DATABASE_URL') or ''
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    if not db_url or 'sqlite' in db_url.lower():
        print('Set DATABASE_URL in .env to your Postgres URL, then run again.')
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    cur  = conn.cursor()

    # ── Rename G500 → G64000 (Softstyle swap) ────────────────────────────────
    cur.execute("""
        UPDATE product SET style_number = 'G64000',
                           name = REPLACE(name, 'Heavy Cotton', 'Softstyle')
        WHERE style_number = 'G500'
    """)
    if cur.rowcount:
        print(f"  [RENAME] G500 → G64000 ({cur.rowcount} row(s))")
    # ─────────────────────────────────────────────────────────────────────────

    updated = skipped = 0

    for style, (cost, price, fabric, desc, fit, spec_url) in PRODUCTS.items():
        cur.execute("SELECT id FROM product WHERE style_number = %s AND is_active = true", (style,))
        row = cur.fetchone()
        if not row:
            print(f"  [SKIP] {style} — not found or inactive")
            skipped += 1
            continue

        cur.execute("""
            UPDATE product SET
                wholesale_cost   = %s,
                base_price       = %s,
                fabric_details   = %s,
                description      = %s,
                fit_guide        = %s,
                spec_sheet_url   = %s
            WHERE id = %s
        """, (cost, price, fabric, desc, fit, spec_url, row[0]))
        updated += 1
        print(f"  [OK] {style:15s} cost=${cost:.2f}  price=${price:.2f}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone! Updated {updated} products, skipped {skipped}.")


if __name__ == '__main__':
    main()
