"""
fill_size_charts.py
───────────────────
Saves each product's own size chart (chest width laid flat, body length, sleeve) from the manufacturer's measurements
published through the S&S Activewear API, so every style shows its own correct numbers instead of one general chart.

    python scripts/fill_size_charts.py --dry-run     # shows what would be saved, changes nothing
    python scripts/fill_size_charts.py               # saves the charts

Styles S&S does not carry (Port & Company, Sport-Tek, District, Stanley/Stella and a few more) are listed at the end:
those need numbers from SanMar's spec sheets. A product that already has a chart is left alone unless --force.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))
os.environ['SCHEDULER_ENABLED'] = '0'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='replace a chart a product already has')
    args = ap.parse_args()

    from app import create_app
    from utils.size_charts import fill_size_charts

    with create_app().app_context():
        r = fill_size_charts(dry_run=args.dry_run, force=args.force, say=print)
    print(f"\n{r['saved']} charts {'would be ' if args.dry_run else ''}saved, {r['skipped']} already had one.")
    print(f"Not available from S&S ({len(r['missing'])}): {', '.join(r['missing'])}")


if __name__ == '__main__':
    main()
