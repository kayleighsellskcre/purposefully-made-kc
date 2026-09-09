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
        'name': 'Rabbit Skins Infant Fine Jersey Tee',
        'category': 'Tee',
        'age_group': 'baby',
        'fit_type': 'Unisex',
        'neck_style': 'Crew Neck',
        'sleeve_length': 'Short Sleeve',
        'description': (
            'Rabbit Skins infant fine jersey tee — soft combed ring-spun cotton '
            'for babies. This is a short-sleeve tee, not a onesie/bodysuit.'
        ),
        'fabric_details': '100% combed ring-spun cotton fine jersey',
        'fabric_summary': '100% combed ring-spun cotton fine jersey, infant tee',
        'softness_rating': 3,
    },
    '3401': None,
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
        # Explicit style targets first
        targets = ['CC1566', 'CC1466', 'RS3401', '1566', '1466', '3401']
        seen_ids = set()
        for style in targets:
            product = None
            for cand in candidate_keys(style):
                product = Product.query.filter(
                    db.func.upper(Product.style_number) == cand
                ).first()
                if product:
                    break
            if not product or product.id in seen_ids:
                continue
            fix = resolve_fix(product.style_number) or resolve_fix(style)
            if not fix:
                continue
            seen_ids.add(product.id)
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
