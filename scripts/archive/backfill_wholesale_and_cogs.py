"""
backfill_wholesale_and_cogs.py
──────────────────────────────
Fill missing product.wholesale_cost values, then recalculate every order's
COGS as blank wholesale + DTF transfer cost.

Sources (in order):
  1. scripts/update_product_data.PRODUCTS (SanMar 1–11 pc tier)
  2. EXTRA_WHOLESALE map below (styles not in that file)
  3. S&S Activewear API customerPrice / piecePrice (when creds work)

    py -3.12 scripts/backfill_wholesale_and_cogs.py --dry-run
    py -3.12 scripts/backfill_wholesale_and_cogs.py
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

# Styles not covered (or outdated) in update_product_data.PRODUCTS
EXTRA_WHOLESALE = {
    # Bella youth / CVC variants
    'BC3501Y': 9.58,
    'BC3501YCVC': 11.18,
    'BC3945Y': 22.38,
    'BC3901Y': 22.38,
    # Bella infant / toddler (approx SanMar 1–11)
    '100B': 6.58,
    '134B': 8.58,
    '3001B': 6.98,
    '3413B': 9.18,
    '3001T': 7.18,
    '3501T': 9.18,
    '3719T': 18.98,
    '3413T': 9.58,
    '3200T': 10.58,
    # C2 Sport / MV Sport / Gildan Softstyle extras
    '5100': 5.50,
    '5104': 7.25,
    '5200': 5.00,
    '5600': 5.50,
    '17116': 18.50,
    '496': 16.00,
    'W23716': 18.00,
    'W25167': 18.00,
    'G64400': 7.50,
    'G64500': 6.50,
    # Independent Trading / Special Blend (if present)
    'IND3000': 18.00,
    'IND4000': 22.00,
    'SS3000': 16.00,
    'SS3001Y': 14.00,
    'SS4500': 20.00,
    'SS4500Z': 22.00,
    'SS4001Y': 16.00,
    'SS4001YZ': 18.00,
    'PRM30SBC': 18.50,
    'PRM33SBP': 22.50,
    'PRM15YSB': 16.50,
    'PRM15YSBC': 16.50,
    'PRM10TSB': 14.50,
    'PRM10TSBC': 14.50,
    # Rabbit Skins (prefer these over flaky S&S piece prices)
    'RS3401': 5.98,
    'RS3321': 6.98,
    'RS4400': 6.58,
}


def _norm(style: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', (style or '').upper())


def _seed_map() -> dict[str, float]:
    from scripts.update_product_data import PRODUCTS
    out: dict[str, float] = {}
    for style, row in PRODUCTS.items():
        try:
            cost = float(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if cost > 0:
            out[_norm(style)] = round(cost, 2)
    # EXTRA wins for styles we explicitly curated (e.g. bad API piece prices)
    for style, cost in EXTRA_WHOLESALE.items():
        if cost and cost > 0:
            out[_norm(style)] = round(float(cost), 2)
    return out


def _ss_wholesale(style_number: str, brand: str | None) -> float | None:
    try:
        from services.ssactivewear_api import SSActivewearAPI
        api = SSActivewearAPI()
        if not getattr(api, 'api_key', None) and not getattr(api, 'account_number', None):
            # constructor may use env; probe a lightweight call
            pass
        # Strip common brand prefixes for S&S part lookup
        raw = (style_number or '').strip()
        candidates = [raw]
        for prefix in ('BC', 'CC', 'RS', 'G', 'PC', 'LPC', 'ST', 'LST', 'DT', 'DM'):
            if raw.upper().startswith(prefix) and len(raw) > len(prefix):
                candidates.append(raw[len(prefix):])
        seen = set()
        for cand in candidates:
            key = cand.upper()
            if key in seen:
                continue
            seen.add(key)
            data = api.fetch_style_data_by_style_number(cand, brand_name=brand)
            if not data:
                continue
            price = data.get('wholesalePrice')
            if price is None:
                continue
            price = float(price)
            if price > 0:
                return round(price, 2)
    except Exception as exc:
        print(f'  [SS skip] {style_number}: {exc}')
    return None


def backfill_wholesale(dry_run: bool = False) -> int:
    from app import create_app
    from models import db, Product

    app = create_app()
    seeds = _seed_map()
    updated = 0
    still_missing = []

    with app.app_context():
        products = Product.query.order_by(Product.style_number).all()
        for product in products:
            current = product.wholesale_cost
            try:
                current_f = float(current) if current is not None else 0.0
            except (TypeError, ValueError):
                current_f = 0.0
            if current_f > 0:
                continue

            style = product.style_number or ''
            key = _norm(style)
            # Also try without BC/CC/… prefix against seed keys
            cost = seeds.get(key)
            if cost is None:
                for prefix in ('BC', 'CC', 'RS', 'G'):
                    if key.startswith(prefix):
                        cost = seeds.get(key) or seeds.get(prefix + key[len(prefix):])
                        # try with prefix added to bare key in seeds
                        bare = key[len(prefix):]
                        cost = seeds.get(key) or seeds.get(prefix + bare) or seeds.get(bare)
                        break

            source = 'seed'
            if cost is None:
                cost = _ss_wholesale(style, product.brand)
                source = 'ss'

            if cost is None or cost <= 0:
                still_missing.append(style)
                print(f'  [MISS] {style}')
                continue

            print(f'  [{"DRY" if dry_run else "SET"}] {style:16s} wholesale=${cost:.2f}  ({source})')
            if not dry_run:
                product.wholesale_cost = cost
            updated += 1

        if not dry_run and updated:
            db.session.commit()

    print(f'\nWholesale: updated {updated}, still missing {len(still_missing)}')
    return updated


def recalculate_order_cogs(dry_run: bool = False) -> int:
    from app import create_app
    from models import db, Order
    from utils.order_costs import order_cost_breakdown, apply_calculated_cogs
    from utils.print_sizes import production_from_order_item

    app = create_app()
    changed = 0
    with app.app_context():
        orders = Order.query.order_by(Order.id).all()
        for order in orders:
            item_productions = []
            for item in order.items:
                prod = production_from_order_item(item, customer_name=order.full_name)
                item_productions.append((item, prod))
            breakdown = order_cost_breakdown(order, item_productions=item_productions)
            before = order.cost_of_goods
            if dry_run:
                blanks = sum(l['blank_cost'] for l in breakdown['lines'])
                dtfs = sum(l['dtf_cost'] for l in breakdown['lines'])
                print(
                    f'  [DRY] {order.order_number} stored={before} '
                    f'→ {breakdown["total_cogs"]} (blank={blanks:.2f} + dtf={dtfs:.2f})'
                )
                if before != breakdown['total_cogs']:
                    changed += 1
                continue
            if apply_calculated_cogs(order, breakdown):
                changed += 1
                print(
                    f'  [COGS] {order.order_number} {before} → {order.cost_of_goods} '
                    f'(profit {order.profit})'
                )
        if not dry_run and changed:
            db.session.commit()
    print(f'\nOrders COGS updated: {changed}')
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--wholesale-only', action='store_true')
    parser.add_argument('--cogs-only', action='store_true')
    args = parser.parse_args()

    if not args.cogs_only:
        print('── Backfill wholesale_cost ──')
        backfill_wholesale(dry_run=args.dry_run)
    if not args.wholesale_only:
        print('\n── Recalculate order COGS (blank + DTF) ──')
        recalculate_order_cogs(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
