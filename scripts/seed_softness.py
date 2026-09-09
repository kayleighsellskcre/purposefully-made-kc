"""
seed_softness.py
────────────────
Ensure product.softness_rating / product.fabric_summary columns exist, then
seed hardcoded softness + fabric summaries by style number.

Ratings: 1=Everyday  2=Soft  3=Super Soft  4=Ultra Soft

    py -3.12 scripts/seed_softness.py --dry-run
    py -3.12 scripts/seed_softness.py
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

# style_key → (softness_rating, fabric_summary)
# Keys are catalog style numbers; matching is case-insensitive and tolerates
# common brand prefixes (BC / CC / RS / G) present or absent in the DB.
SOFTNESS_BY_STYLE = {
    # BELLA+CANVAS
    'BC3001': (4, '100% Airlume combed ring-spun cotton, lightweight'),
    'BC3001CVC': (3, '52% combed cotton / 48% polyester CVC, heathered'),
    'BC3001Y': (4, '100% Airlume combed ring-spun cotton, lightweight'),
    'BC3001YCVC': (3, '52% combed cotton / 48% polyester CVC, heathered'),
    'BC3501': (4, '100% Airlume combed ring-spun cotton, lightweight'),
    'BC3501CVC': (3, '52% combed cotton / 48% polyester CVC, heathered'),
    'BC3501Y': (4, '100% Airlume combed ring-spun cotton, lightweight'),
    'BC3501YCVC': (3, '52% combed cotton / 48% polyester CVC, heathered'),
    'BC3719': (3, '52% cotton / 48% polyester sponge fleece'),
    'BC3719Y': (3, '52% cotton / 48% polyester sponge fleece'),
    'BC3901': (3, '52% cotton / 48% polyester sponge fleece, raglan'),
    'BC3901Y': (3, '52% cotton / 48% polyester sponge fleece, raglan'),
    'BC3945': (3, '52% cotton / 48% polyester sponge fleece'),
    'BC3945Y': (3, '52% cotton / 48% polyester sponge fleece'),
    'BC3739': (3, '52% cotton / 48% polyester sponge fleece, full-zip'),
    'BC3413': (4, '50/25/25 poly / combed cotton / rayon triblend'),
    'BC3413Y': (4, '50/25/25 poly / combed cotton / rayon triblend'),
    'BC3480': (4, '100% Airlume combed ring-spun cotton, jersey tank'),
    'BC3480CVC': (3, '52% combed cotton / 48% polyester CVC tank'),
    'BC3005': (4, '100% Airlume combed ring-spun cotton, V-neck'),
    'BC3005CVC': (3, '52% combed cotton / 48% polyester CVC, V-neck'),
    'BC6400': (4, '100% Airlume combed ring-spun cotton, relaxed fit'),
    'BC6400CVC': (3, '52% combed cotton / 48% polyester CVC, relaxed'),
    'BC8800': (3, '100% polyester, flowy racerback'),
    'BC1080': (3, '95% cotton / 5% spandex baby rib'),
    'BC1200': (3, '95% cotton / 5% spandex micro rib, 3/4 sleeve'),
    'BC1201': (3, '95% cotton / 5% spandex micro rib'),
    'BC1501': (3, '95% cotton / 5% spandex micro rib, long sleeve'),
    'BC3787': (3, '52% cotton / 48% polyester sponge fleece'),
    # BELLA+CANVAS INFANT & TODDLER
    '100B': (4, '100% Airlume combed ring-spun cotton, infant'),
    '134B': (4, '50/25/25 poly / combed cotton / rayon triblend, infant'),
    '3001B': (4, '100% Airlume combed ring-spun cotton, infant tee'),
    '3413B': (4, '50/25/25 poly / combed cotton / rayon triblend, infant'),
    '3001T': (4, '100% Airlume combed ring-spun cotton, toddler'),
    '3501T': (4, '100% Airlume combed ring-spun cotton, toddler'),
    '3719T': (3, '52% cotton / 48% polyester sponge fleece, toddler'),
    '3413T': (4, '50/25/25 poly / combed cotton / rayon triblend, toddler'),
    '3200T': (2, '50% polyester / 25% cotton / 25% rayon, baseball tee'),
    # RABBIT SKINS
    'RS3401': (3, '100% combed ring-spun cotton fine jersey, infant tee'),
    'RS3321': (3, '100% combed ring-spun cotton fine jersey, toddler'),
    'RS4400': (3, '100% combed ring-spun cotton baby rib, infant'),
    # PORT & COMPANY
    'PC146': (2, '80% cotton / 20% polyester fleece, tie-dye'),
    'PC146Y': (2, '80% cotton / 20% polyester fleece, tie-dye youth'),
    'PC144': (2, '80% cotton / 20% polyester fleece, crystal tie-dye'),
    'PC145': (2, '100% cotton, crystal tie-dye'),
    'PC147': (2, '100% cotton, tie-dye'),
    'PC147LS': (2, '100% cotton, tie-dye long sleeve'),
    'PC147Y': (2, '100% cotton, tie-dye youth'),
    'PC147YLS': (2, '100% cotton, tie-dye long sleeve youth'),
    'LPC147V': (2, '100% cotton, tie-dye V-neck'),
    'PC54': (1, '100% cotton, core cotton'),
    'LPC54': (1, '100% cotton, ladies core cotton'),
    'PC78H': (1, '50% cotton / 50% polyester core fleece'),
    # C2 SPORT
    '5100': (2, '100% polyester moisture-wicking performance'),
    '5104': (2, '100% polyester moisture-wicking performance, long sleeve'),
    '5200': (2, '100% polyester moisture-wicking performance, youth'),
    '5600': (2, "100% polyester moisture-wicking performance, women's"),
    # COMFORT COLORS
    'CC1717': (3, '100% ring-spun cotton, garment-dyed heavyweight'),
    'CC1566': (3, '80% cotton / 20% polyester fleece, garment-dyed crew'),
    'CC1466': (3, '80% cotton / 20% polyester, garment-dyed light crew'),
    # DISTRICT
    'DM130': (4, '50/25/25 poly / combed cotton / rayon Perfect Tri'),
    'DT6000': (2, '100% ring-spun cotton, Very Important Tee'),
    'DT8000': (2, '65% poly / 35% cotton, Re-Tee hoodie'),
    # GILDAN
    'G18000': (1, '50% cotton / 50% polyester Heavy Blend, heavyweight'),
    'G18500': (1, '50% cotton / 50% polyester Heavy Blend, heavyweight'),
    'G64000': (2, '100% ring-spun cotton Softstyle'),
    'G64400': (2, '100% ring-spun cotton Softstyle, long sleeve'),
    'G64500': (2, '100% ring-spun cotton Softstyle, V-neck'),
    # INDEPENDENT TRADING CO.
    'IND3000': (1, '80% cotton / 20% polyester heavyweight fleece'),
    'IND4000': (1, '80% cotton / 20% polyester heavyweight fleece, hoodie'),
    'SS3000': (2, '80% cotton / 20% polyester midweight fleece'),
    'SS3001Y': (2, '80% cotton / 20% polyester midweight fleece, youth'),
    'SS4500': (2, '80% cotton / 20% polyester midweight fleece, hoodie'),
    'SS4500Z': (2, '80% cotton / 20% polyester midweight, full-zip'),
    'SS4001Y': (2, '80% cotton / 20% polyester midweight fleece, youth'),
    'SS4001YZ': (2, '80% cotton / 20% polyester midweight full-zip, youth'),
    'PRM30SBC': (3, '70% polyester / 30% cotton Special Blend fleece'),
    'PRM33SBP': (3, '70% polyester / 30% cotton Special Blend hoodie'),
    'PRM15YSB': (3, '70% polyester / 30% cotton Special Blend, youth'),
    'PRM15YSBC': (3, '70% polyester / 30% cotton Special Blend, youth'),
    'PRM10TSB': (3, '70% polyester / 30% cotton Special Blend, toddler'),
    'PRM10TSBC': (3, '70% polyester / 30% cotton Special Blend, toddler'),
    # SPORT-TEK
    'ST350': (2, '100% polyester PosiCharge moisture-wicking'),
    'LST350': (2, "100% polyester PosiCharge moisture-wicking, women's"),
    'ST254': (2, '100% polyester PosiCharge moisture-wicking hoodie'),
    # STANLEY/STELLA
    'STTU755': (4, '100% organic ring-spun cotton, Creator 2.0'),
    'STTU169': (4, "100% organic ring-spun cotton, women's"),
    'STSW013': (4, '85% organic cotton / 15% recycled polyester hoodie'),
    # MV SPORT
    '17116': (2, '80% cotton / 20% polyester vintage fleece raglan'),
    '496': (2, '60% cotton / 40% polyester Pro-Weave fleece'),
    'W23716': (3, "83% polyester / 17% cotton sueded fleece, women's"),
    'W25167': (3, '60% cotton / 40% polyester Coastal Color fleece'),
}

SOFTNESS_LABELS = {1: 'Everyday', 2: 'Soft', 3: 'Super Soft', 4: 'Ultra Soft'}


def normalize_style(style: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', (style or '').upper())


def candidate_keys(style_key: str) -> list[str]:
    """Generate match keys for a seed style (with/without common prefixes)."""
    k = normalize_style(style_key)
    if not k:
        return []
    keys = [k]
    for prefix in ('BC', 'CC', 'RS', 'G'):
        if k.startswith(prefix) and len(k) > len(prefix):
            bare = k[len(prefix):]
            if bare and bare not in keys:
                keys.append(bare)
        else:
            prefixed = prefix + k
            if prefixed not in keys:
                keys.append(prefixed)
    # Comfort Colors sometimes stored as C1717
    if k.startswith('CC') and len(k) > 2:
        c_form = 'C' + k[2:]
        if c_form not in keys:
            keys.append(c_form)
    elif k.isdigit():
        for p in ('CC', 'C'):
            form = p + k
            if form not in keys:
                keys.append(form)
    return keys


def ensure_columns(db) -> None:
    statements = [
        'ALTER TABLE product ADD COLUMN IF NOT EXISTS softness_rating INTEGER',
        'ALTER TABLE product ADD COLUMN IF NOT EXISTS fabric_summary VARCHAR(80)',
    ]
    with db.engine.connect() as conn:
        for sql in statements:
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                # SQLite older builds may lack IF NOT EXISTS — try plain add
                try:
                    plain = sql.replace(' IF NOT EXISTS', '')
                    conn.execute(db.text(plain))
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass


def clip_summary(text: str, limit: int = 80) -> str:
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def build_product_index(products):
    by_norm = {}
    for product in products:
        key = normalize_style(product.style_number)
        if key and key not in by_norm:
            by_norm[key] = product
    return by_norm


def find_product(style_key: str, by_norm: dict):
    for candidate in candidate_keys(style_key):
        product = by_norm.get(candidate)
        if product is not None:
            return product
    return None


def seed(dry_run: bool = False) -> dict:
    from app import create_app
    from models import db, Product

    app = create_app()
    stats = {'updated': 0, 'unchanged': 0, 'missing': 0, 'skipped_invalid': 0}

    with app.app_context():
        ensure_columns(db)
        products = Product.query.all()
        by_norm = build_product_index(products)
        print(f'Loaded {len(products)} products. Seeding {len(SOFTNESS_BY_STYLE)} style mappings…\n')

        missing_styles = []
        for style_key, (rating, summary) in SOFTNESS_BY_STYLE.items():
            if rating not in SOFTNESS_LABELS:
                print(f'  [SKIP] {style_key}: invalid rating {rating}')
                stats['skipped_invalid'] += 1
                continue
            summary = clip_summary(summary, 80)
            product = find_product(style_key, by_norm)
            if product is None:
                missing_styles.append(style_key)
                stats['missing'] += 1
                continue

            changed = (
                product.softness_rating != rating
                or (product.fabric_summary or '') != summary
            )
            label = SOFTNESS_LABELS[rating]
            if dry_run:
                action = 'UPDATE' if (
                    product.softness_rating is not None or product.fabric_summary
                ) else 'SET'
                print(
                    f'  [DRY {action}] {product.style_number:12s} ← {style_key:12s}  '
                    f'{rating} ({label})  {summary}'
                )
                stats['updated'] += 1
                continue

            if not changed:
                stats['unchanged'] += 1
                continue

            product.softness_rating = rating
            product.fabric_summary = summary
            stats['updated'] += 1
            print(
                f'  [UPDATED] {product.style_number:12s}  '
                f'{rating} ({label})  {summary}'
            )

        if not dry_run:
            db.session.commit()

        print('\n' + '─' * 60)
        print(
            f"{'DRY RUN — ' if dry_run else ''}Updated: {stats['updated']}  "
            f"Unchanged: {stats['unchanged']}  "
            f"Not in DB: {stats['missing']}  "
            f"Invalid: {stats['skipped_invalid']}"
        )
        if missing_styles:
            print('Styles not found (skipped): ' + ', '.join(missing_styles))

    return stats


def main():
    parser = argparse.ArgumentParser(description='Seed product softness ratings')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    seed(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
