"""
find_ss_styles.py
─────────────────
Diagnostic tool — searches S&S API by brand name to find the correct
style numbers for brands like MV Sport and C2 Sport.

Run from project root in Cursor terminal:

    py -3.12 scripts/find_ss_styles.py --brand "MV Sport"
    py -3.12 scripts/find_ss_styles.py --brand "C2 Sport"
    py -3.12 scripts/find_ss_styles.py --brand "MV Sport" --search "raglan"
    py -3.12 scripts/find_ss_styles.py --list-brands
"""

import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--brand', default=None, help='Brand name to search (e.g. "MV Sport")')
    parser.add_argument('--search', default=None, help='Filter results by keyword in style name/title')
    parser.add_argument('--list-brands', action='store_true', help='List all available brands in your S&S catalog')
    parser.add_argument('--style', default=None, help='Look up a specific style number directly')
    args = parser.parse_args()

    from services.ssactivewear_api import SSActivewearAPI
    import requests, base64

    try:
        api = SSActivewearAPI()
    except ValueError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    # ── List brands ───────────────────────────────────────────────────────────
    if args.list_brands:
        print("\nFetching all styles to discover brand names...")
        print("(This may take a moment)\n")
        try:
            resp = requests.get(
                f"{api.api_url}/v2/styles",
                auth=(api.account_number, api.api_key),
                timeout=60
            )
            resp.raise_for_status()
            styles = resp.json()
            if isinstance(styles, list):
                brands = sorted(set(s.get('brandName', 'Unknown') for s in styles if s.get('brandName')))
                print(f"Found {len(brands)} brands in your S&S catalog:\n")
                for b in brands:
                    count = sum(1 for s in styles if s.get('brandName') == b)
                    print(f"  {b:40s} ({count} styles)")
            else:
                print(f"Unexpected response: {styles}")
        except Exception as e:
            print(f"Error: {e}")
        return

    # ── Look up specific style number ──────────────────────────────────────────
    if args.style:
        print(f"\nLooking up style number: {args.style}\n")

        # Try /v2/styles endpoint with various params
        attempts = [
            {'styleNumber': args.style},
            {'partnumber': args.style},
            {'style': args.style},
        ]
        found = False
        for params in attempts:
            try:
                resp = requests.get(
                    f"{api.api_url}/v2/styles",
                    auth=(api.account_number, api.api_key),
                    params=params,
                    timeout=30
                )
                data = resp.json()
                styles = data if isinstance(data, list) else []
                if styles:
                    print(f"  Found via params={params}:")
                    for s in styles[:5]:
                        print(f"    styleID={s.get('styleID')}  styleNumber={s.get('styleNumber') or s.get('styleName')}  brand={s.get('brandName')}  title={s.get('title','')[:60]}")
                    found = True
                    break
            except Exception as e:
                print(f"  Error with params={params}: {e}")

        # Also try /v2/products
        if not found:
            print("  Not found via /v2/styles. Trying /v2/products...")
            for params in [{'styleNumber': args.style}, {'partNumber': args.style}]:
                try:
                    resp = requests.get(
                        f"{api.api_url}/v2/products",
                        auth=(api.account_number, api.api_key),
                        params=params,
                        timeout=30
                    )
                    data = resp.json()
                    products = data if isinstance(data, list) else []
                    if products:
                        p = products[0]
                        print(f"  Found via /v2/products params={params}:")
                        print(f"    styleID={p.get('styleID')}  styleName={p.get('styleName')}  brand={p.get('brandName')}  colorName={p.get('colorName')}  sizeName={p.get('sizeName')}")
                        found = True
                        break
                except Exception as e:
                    print(f"  Error: {e}")
        if not found:
            print(f"  Style {args.style} not found in S&S API.")
        return

    # ── Search by brand ────────────────────────────────────────────────────────
    if not args.brand:
        parser.print_help()
        return

    print(f"\nFetching full S&S catalog and filtering for brand: '{args.brand}'")
    print("(This takes ~30 seconds — the API doesn't support server-side brand filtering)\n")

    try:
        resp = requests.get(
            f"{api.api_url}/v2/styles",
            auth=(api.account_number, api.api_key),
            timeout=120
        )
        resp.raise_for_status()
        all_styles = resp.json() if isinstance(resp.json(), list) else []
    except Exception as e:
        print(f"Error fetching catalog: {e}")
        return

    # Filter locally — case-insensitive substring match on brandName
    search_brand = args.brand.lower().strip()
    styles = [
        s for s in all_styles
        if search_brand in (s.get('brandName', '') or '').lower()
    ]
    print(f"Found {len(styles)} styles for '{args.brand}' (out of {len(all_styles)} total)\n")

    if not styles:
        print(f"No styles found for brand '{args.brand}'.")
        print("\nTip: run --list-brands to see all available brand names.")
        return

    # Filter by keyword if provided
    if args.search:
        keyword = args.search.lower()
        styles = [s for s in styles if keyword in (s.get('title', '') or s.get('styleName', '') or '').lower()]
        print(f"  After keyword filter '{args.search}': {len(styles)} styles\n")

    # Display results
    print(f"{'styleID':>10}  {'Style#':>10}  {'Title':<55}  {'Brand'}")
    print("-" * 100)
    for s in styles[:50]:
        sid   = str(s.get('styleID', ''))
        snum  = str(s.get('styleNumber') or s.get('styleName') or '')
        title = (s.get('title', '') or '')[:54]
        brand = s.get('brandName', '')
        print(f"{sid:>10}  {snum:>10}  {title:<55}  {brand}")

    if len(styles) > 50:
        print(f"\n... and {len(styles) - 50} more. Add --search keyword to narrow results.")

    print(f"\nTotal: {len(styles)} styles found.")
    print("\nOnce you identify the correct styleID, update PRODUCTS_TO_ADD in add_ss_products.py")
    print("and add a 'style_id' override to fetch by ID instead of style number.")


if __name__ == '__main__':
    main()
