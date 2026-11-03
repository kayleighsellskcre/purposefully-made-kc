"""
recalculate_prices.py
─────────────────────
One-time script to update base_price for all existing products using the
new pricing formula:

    base_price = ceil(wholesale_cost) + $7 (margin) + $12 (transfer) = ceil + $19

Products with wholesale_cost = 0 (or NULL) are skipped — these were
manually priced and should be updated via the admin edit page.

Run from the project root:
    python scripts/recalculate_prices.py
"""

import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


def main():
    database_url = os.getenv('DATABASE_URL', '').strip()
    if not database_url:
        print('ERROR: DATABASE_URL is not set. Add it to .env and try again.')
        sys.exit(1)
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    cur.execute("SELECT id, name, wholesale_cost, base_price FROM product ORDER BY id")
    rows = cur.fetchall()

    updated = 0
    skipped = 0

    print(f"{'ID':<6} {'Name':<50} {'Old Price':>10} {'New Price':>10} {'Status'}")
    print('-' * 90)

    for product_id, name, wholesale_cost, old_price in rows:
        if not wholesale_cost or wholesale_cost <= 0:
            print(f"{product_id:<6} {(name or '')[:50]:<50} {'$' + f'{old_price:.2f}':>10} {'—':>10}  SKIP (no wholesale cost)")
            skipped += 1
            continue

        new_price = math.ceil(wholesale_cost) + 19

        # Only update if price actually changed
        if abs((old_price or 0) - new_price) < 0.001:
            print(f"{product_id:<6} {(name or '')[:50]:<50} {'$' + f'{old_price:.2f}':>10} {'$' + f'{new_price:.2f}':>10}  (no change)")
            continue

        cur.execute(
            "UPDATE product SET base_price = %s WHERE id = %s",
            (new_price, product_id),
        )
        print(f"{product_id:<6} {(name or '')[:50]:<50} {'$' + f'{old_price:.2f}':>10} {'$' + f'{new_price:.2f}':>10}  UPDATED")
        updated += 1

    conn.commit()
    cur.close()
    conn.close()

    print()
    print(f"Done. {updated} products updated, {skipped} skipped (no wholesale cost on file).")


if __name__ == '__main__':
    main()
