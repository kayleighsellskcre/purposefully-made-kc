#!/usr/bin/env python3
"""
scripts/sanmar_sync.py

Manually trigger a SanMar DIP file sync.

Run from the project root in Cursor terminal:

  python scripts/sanmar_sync.py              # curated styles only (recommended)
  python scripts/sanmar_sync.py --all        # full SanMar catalog
  python scripts/sanmar_sync.py --local PATH # skip download, use existing file
  python scripts/sanmar_sync.py --keep       # keep the downloaded file afterwards

Requires a .env file (or Railway env vars) with:
  SANMAR_FTP_HOST, SANMAR_FTP_PORT, SANMAR_FTP_USER, SANMAR_FTP_PASSWORD
  DATABASE_URL
"""

import argparse
import os
import sys

# Allow imports from project root regardless of where script is called from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import app  # noqa: E402  (needs dotenv first)


def main() -> None:
    parser = argparse.ArgumentParser(description='Sync SanMar DIP file to Railway PostgreSQL.')
    parser.add_argument(
        '--all',
        action='store_true',
        help='Sync the full SanMar catalog instead of just curated styles',
    )
    parser.add_argument(
        '--local',
        metavar='PATH',
        help='Path to an already-downloaded sanmar_dip.txt (skips SFTP download)',
    )
    parser.add_argument(
        '--keep',
        action='store_true',
        help='Keep the downloaded dip.txt file after sync completes',
    )
    args = parser.parse_args()

    from services.sanmar_ftp import run_dip_sync

    print()
    print('Starting SanMar DIP sync …')
    if args.all:
        print('Mode: FULL catalog')
    else:
        print('Mode: curated styles only')
    print()

    result = run_dip_sync(
        styles_only = not args.all,
        local_path  = args.local,
        keep_file   = args.keep,
        app         = app,
    )

    print()
    print('=' * 50)
    print('  SanMar DIP Sync Results')
    print('=' * 50)
    print(f"  Style/color groups parsed : {result['groups']:,}")
    print(f"  Products created          : {result['created']:,}")
    print(f"  Products updated          : {result['updated']:,}")
    print(f"  Errors / skipped          : {result['skipped']:,}")
    print(f"  Time elapsed              : {result['elapsed_seconds']}s")
    print('=' * 50)
    print()

    if result['skipped'] > 0:
        sys.exit(1)   # non-zero so CI/cron can detect partial failures


if __name__ == '__main__':
    main()
