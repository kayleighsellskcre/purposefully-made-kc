"""
fix_product_identity.py
───────────────────────
Correct known wrong product names/categories against S&S catalog truth.

    py -3.12 scripts/fix_product_identity.py --dry-run
    py -3.12 scripts/fix_product_identity.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))
os.environ.setdefault('SCHEDULER_ENABLED', '0')

# Canonical corrections keyed by style number (case-insensitive; BC/CC/RS/G tolerant).
# Verified against S&S Activewear style metadata (2026-09).
IDENTITY_FIXES = {
    'CC1566': {
        'name': 'Comfort Colors Unisex Garment-Dyed Crewneck Sweatshirt',
        'category': 'Sweatshirt',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'description': (
            'Comfort Colors garment-dyed crewneck sweatshirt. 9.5 oz. 80/20 '
            'ring-spun cotton/polyester 3-end fleece with a 100% cotton face, '
            'relaxed fit, and lived-in pigment-dyed color.'
        ),
        'fabric_details': '9.5 oz / 80% ring-spun cotton, 20% polyester fleece, garment-dyed',
        'fabric_summary': '80% cotton / 20% polyester fleece, garment-dyed crew',
        'softness_rating': 3,
    },
    '1566': None,  # alias → CC1566 handled via candidates
    'CC1466': {
        'name': 'Comfort Colors Unisex Garment-Dyed Lightweight Crewneck Sweatshirt',
        'category': 'Sweatshirt',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'description': (
            'Comfort Colors lightweight garment-dyed crewneck sweatshirt. '
            'Softer, lighter fleece with the same pigment-washed character as '
            'the heavier 1566 crew — not a hoodie.'
        ),
        'fabric_details': '80% cotton / 20% polyester, garment-dyed lightweight fleece',
        'fabric_summary': '80% cotton / 20% polyester, garment-dyed light crew',
        'softness_rating': 3,
    },
    'RS3401': {
        'name': 'Rabbit Skins Infant Cotton Jersey Tee',
        'category': 'Tee',
        'age_group': 'baby',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'description': (
            'Rabbit Skins infant cotton jersey tee — a classic short-sleeve '
            'shirt for babies. This is not a onesie or bodysuit.'
        ),
        'fabric_details': '5.5 oz / 100% cotton jersey (Ash and Heather blends vary)',
        'fabric_summary': '100% cotton jersey, substantial infant tee',
        'softness_rating': 2,
    },
    '3401': None,
    'RS3321': {
        'name': 'Rabbit Skins Toddler Fine Jersey Tee',
        'category': 'Tee',
        'age_group': 'toddler',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'description': (
            'Rabbit Skins toddler fine jersey tee — a soft short-sleeve shirt '
            'made from combed ring-spun cotton.'
        ),
        'fabric_details': '4.5 oz / 100% combed ring-spun cotton fine jersey',
        'fabric_summary': '100% combed ring-spun cotton fine jersey, toddler',
        'softness_rating': 3,
    },
    'RS4400': {
        'name': 'Rabbit Skins Infant Baby Rib Bodysuit',
        'category': 'Onesie',
        'age_group': 'baby',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'description': (
            'Rabbit Skins infant baby rib bodysuit — a soft one-piece with lap '
            'shoulders and a reinforced three-snap closure.'
        ),
        'fabric_details': '5.5 oz / 100% combed ring-spun cotton baby rib',
        'fabric_summary': '100% combed ring-spun cotton baby rib, infant',
        'softness_rating': 3,
    },
    'DT8000': {
        'name': 'District Re-Tee',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'description': (
            'The District Re-Tee is a short-sleeve crewneck jersey tee made '
            'from 100% recycled material. Substantial yet soft, it is an '
            'easy-wearing sustainable choice.'
        ),
        'fabric_details': (
            '5.3 oz / 60% recycled cotton, 40% recycled polyester jersey '
            '(color blends vary)'
        ),
        'fabric_summary': (
            '60% recycled cotton / 40% recycled polyester jersey Re-Tee'
        ),
        'softness_rating': 2,
    },
    'DM130': {
        'name': 'District Perfect Tri Tee',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'description': (
            'The District Perfect Tri Tee is a soft short-sleeve crewneck '
            'with a heathered vintage look and lightweight tri-blend jersey.'
        ),
        'fabric_details': (
            '4.5 oz / 50% polyester, 25% combed ring-spun cotton, 25% rayon'
        ),
        'fabric_summary': '50/25/25 poly / combed cotton / rayon Perfect Tri',
        'softness_rating': 4,
    },
    'DT6000': {
        'name': 'District Very Important Tee',
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'fabric_details': (
            '4.3 oz combed ring-spun cotton jersey; heather, frost, and select '
            'colors use cotton/poly blends'
        ),
        'fabric_summary': (
            'Combed ring-spun cotton jersey; heather colors use cotton/poly blends'
        ),
        'softness_rating': 2,
    },
    'ST254': {
        'name': 'Sport-Tek PosiCharge Competitor 1/4-Zip Pullover',
        'category': 'Long Sleeve',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Quarter-Zip',
        'sleeve_length': 'Long Sleeve',
        'description': (
            'Lightweight 1/4-zip performance pullover with moisture-wicking '
            'PosiCharge color-lock technology.'
        ),
        'fabric_details': (
            '3.8 oz / 100% polyester interlock with PosiCharge technology'
        ),
        'fabric_summary': (
            '100% polyester PosiCharge 1/4-zip performance pullover'
        ),
        'softness_rating': 1,
    },
    'STTU169': {
        'name': "Stanley/Stella Stella Muser Women's Tee",
        'category': 'Tee',
        'age_group': 'adult',
        'fit_type': "Women's",
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'fabric_details': (
            '5.3 oz / 100% GOTS-certified organic ring-spun cotton'
        ),
    },
    'STSW013': {
        'name': 'Stanley/Stella Cruiser 2.0 Pullover Hoodie',
        'category': 'Hoodie',
        'age_group': 'adult',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
        'fabric_details': (
            '85% organic cotton, 15% recycled polyester fleece'
        ),
    },
    'BC8800': {
        'name': "BELLA+CANVAS Women's Flowy Racerback Tank",
        'category': 'Tank',
        'age_group': 'adult',
        'fit_type': "Women's",
        'sleeve_length': 'Sleeveless',
        'fabric_details': (
            '3.7 oz / 65% polyester, 35% viscose (color blends vary)'
        ),
        'fabric_summary': '65% polyester / 35% viscose, flowy racerback',
        'softness_rating': 4,
    },
    '3501T': {
        'category': 'Long Sleeve',
        'age_group': 'toddler',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
    },
    '3719T': {
        'category': 'Hoodie',
        'age_group': 'toddler',
        'fit_type': 'Unisex',
        'neck_style': 'Hooded',
        'sleeve_length': 'Long Sleeve',
    },
}

_INDEPENDENT_FABRICS = {
    'IND3000': ('10 oz / 70% ring-spun cotton, 30% polyester 3-end fleece',
                '70% cotton / 30% polyester heavyweight fleece', 1),
    'IND4000': ('10 oz / 70% ring-spun cotton, 30% polyester 3-end fleece',
                '70% cotton / 30% polyester heavyweight fleece, hoodie', 1),
    'PRM10TSB': ('6.5 oz / 52% ring-spun cotton, 48% polyester fleece',
                 '52% cotton / 48% polyester Special Blend, toddler', 3),
    'PRM10TSBC': ('6.5 oz / 52% ring-spun cotton, 48% polyester fleece',
                  '52% cotton / 48% polyester Special Blend, toddler', 3),
    'PRM15YSB': ('6.5 oz / 52% ring-spun cotton, 48% polyester fleece',
                 '52% cotton / 48% polyester Special Blend, youth', 3),
    'PRM15YSBC': ('6.5 oz / 52% ring-spun cotton, 48% polyester fleece',
                  '52% cotton / 48% polyester Special Blend, youth', 3),
    'PRM30SBC': ('8 oz / 52% ring-spun cotton, 48% polyester fleece',
                 '52% cotton / 48% polyester Special Blend fleece', 3),
    'PRM33SBP': ('8 oz / 52% ring-spun cotton, 48% polyester fleece',
                 '52% cotton / 48% polyester Special Blend hoodie', 3),
    'SS3000': ('8.5 oz / 80% ring-spun cotton, 20% polyester fleece',
               '80% cotton / 20% polyester midweight fleece', 2),
    'SS3001Y': ('8.5 oz / 80% ring-spun cotton, 20% polyester fleece',
                '80% cotton / 20% polyester midweight fleece, youth', 2),
    'SS4001Y': ('8.5 oz / 80% ring-spun cotton, 20% polyester fleece',
                '80% cotton / 20% polyester midweight fleece, youth', 2),
    'SS4001YZ': ('8.5 oz / 80% ring-spun cotton, 20% polyester fleece',
                 '80% cotton / 20% polyester midweight full-zip, youth', 2),
    'SS4500': ('8.5 oz / 80% ring-spun cotton, 20% polyester fleece',
               '80% cotton / 20% polyester midweight fleece, hoodie', 2),
    'SS4500Z': ('8.5 oz / 80% ring-spun cotton, 20% polyester fleece',
                '80% cotton / 20% polyester midweight, full-zip', 2),
}
_INDEPENDENT_HOODIES = {
    'IND4000', 'PRM10TSB', 'PRM15YSB', 'PRM33SBP',
    'SS4001Y', 'SS4001YZ', 'SS4500', 'SS4500Z',
}
for _style, (_details, _summary, _rating) in _INDEPENDENT_FABRICS.items():
    IDENTITY_FIXES[_style] = {
        'neck_style': 'Hooded' if _style in _INDEPENDENT_HOODIES else 'Crew Neck',
        'sleeve_length': 'Long Sleeve',
        'fabric_details': _details,
        'fabric_summary': _summary,
        'softness_rating': _rating,
    }


def normalize_style(style: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', (style or '').upper())


def candidate_keys(style_key: str) -> list[str]:
    k = normalize_style(style_key)
    keys = [k]
    for prefix in ('BC', 'CC', 'RS', 'G'):
        if k.startswith(prefix) and len(k) > len(prefix):
            bare = k[len(prefix):]
            if bare not in keys:
                keys.append(bare)
        else:
            prefixed = prefix + k
            if prefixed not in keys:
                keys.append(prefixed)
    return keys


def resolve_fix(style_number: str) -> dict | None:
    for cand in candidate_keys(style_number):
        if cand in IDENTITY_FIXES and IDENTITY_FIXES[cand]:
            return IDENTITY_FIXES[cand]
        # Prefer prefixed Comfort Colors / Rabbit Skins keys
        for prefix in ('CC', 'RS'):
            keyed = prefix + cand if not cand.startswith(prefix) else cand
            if keyed in IDENTITY_FIXES and IDENTITY_FIXES[keyed]:
                return IDENTITY_FIXES[keyed]
    return None


def apply_fixes(dry_run: bool = False) -> int:
    from app import create_app
    from models import db, Product

    app = create_app()
    updated = 0
    with app.app_context():
        # Walk the catalog so every canonical style in IDENTITY_FIXES is
        # corrected without maintaining a second, easy-to-miss target list.
        for product in Product.query.order_by(Product.style_number).all():
            fix = resolve_fix(product.style_number)
            if not fix:
                continue
            changes = []
            for field, value in fix.items():
                old = getattr(product, field, None)
                if old != value:
                    changes.append(f'{field}: {old!r} → {value!r}')
                    if not dry_run:
                        setattr(product, field, value)
            if changes:
                updated += 1
                print(f'\n{"[DRY] " if dry_run else ""}{product.style_number} (id={product.id})')
                for line in changes:
                    print(f'  {line}')

        if not dry_run and updated:
            db.session.commit()

        # Heuristic audit of remaining catalog (report only)
        print('\n── Heuristic audit (name vs category) ──')
        suspicious = []
        for p in Product.query.order_by(Product.style_number).all():
            name = (p.name or '').lower()
            cat = (p.category or '').lower()
            issues = []
            if 'ladies tee' in name and ('sweat' in name or p.style_number.upper() in ('CC1566', '1566')):
                issues.append('ladies-tee-on-sweat-style')
            if 'hoodie' in name and 'sweatshirt' in name and 'hoodie' not in cat and 'hood' not in cat:
                pass  # toddler hoodie sweatshirt naming is ok
            if 'hoodie' in cat and 'crewneck' in name and 'hood' not in name:
                issues.append('category-hoodie-but-name-crewneck')
            if 'tee' in cat and ('sweatshirt' in name or 'hoodie' in name):
                issues.append('category-tee-but-fleece-name')
            if 'onesie' in cat and 'tee' in name and 'bodysuit' not in name and 'onesie' not in name and 'one piece' not in name:
                issues.append('category-onesie-but-name-tee')
            if 'bodysuit' in name and 'tee' in cat:
                issues.append('name-bodysuit-but-category-tee')
            if issues:
                suspicious.append((p.style_number, p.category, p.name, issues))
        if not suspicious:
            print('  No remaining heuristic mismatches.')
        else:
            for style, cat, name, issues in suspicious:
                print(f'  {style:12} cat={cat:12} issues={issues} | {name}')

        print(f"\n{'DRY RUN — would update' if dry_run else 'Updated'}: {updated} products")
    return updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    apply_fixes(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
