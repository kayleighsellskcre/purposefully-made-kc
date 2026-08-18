"""
find_missing_images.py
──────────────────────
Searches SanMar Widen media library for RS3401 and G64500 using
multiple search term variations to find if images exist under a
different naming convention.

Run from project root in Cursor terminal:
    py -3.12 scripts/find_missing_images.py --cookie "YOUR_JSESSIONID"
"""

import requests
import sys
import argparse

API_URL   = 'https://medialibrary1.com/api/rest/asset/search'
ACCOUNT   = 'medialibrary1'

SEARCHES = [
    # RS3401 variations
    ('RS3401', 'RS3401 Flat'),
    ('RS3401', '3401 Flat'),
    ('RS3401', 'RS3401'),
    ('RS3401', '3401'),
    ('RS3401', 'RS 3401'),
    # G64500 variations
    ('G64500', '64500 Flat'),
    ('G64500', 'G64500 Flat'),
    ('G64500', '64500'),
    ('G64500', 'G64500'),
    ('G64500', 'Softstyle V-Neck Flat'),
]

def search(query, cookie, page_size=10):
    params = {
        'query':    query,
        'limit':    page_size,
        'offset':   0,
        'expand':   'file',
        'filetype': 'jpg',
        'account':  ACCOUNT,
    }
    headers = {'Cookie': f'JSESSIONID={cookie}'}
    resp = requests.get(API_URL, params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data.get('items', data) if isinstance(data, dict) else data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cookie', required=True, help='JSESSIONID cookie value')
    args = parser.parse_args()

    print(f"\nSearching Widen media library for RS3401 and G64500...\n")
    print(f"{'Style':>8}  {'Search Term':<35}  {'Results'}")
    print('-' * 65)

    found = {}
    for style, query in SEARCHES:
        items = search(query, args.cookie)
        count = len(items)
        print(f"{style:>8}  {query:<35}  {count} results")
        if count and style not in found:
            found[style] = (query, items[0])

    print()
    if found:
        print("FOUND IMAGES:\n")
        for style, (query, item) in found.items():
            filename = item.get('filename', item.get('name', 'unknown'))
            url = None
            embeds = item.get('embeds', {})
            if embeds:
                url = next(iter(embeds.values()), {}).get('url', '')
            print(f"  {style}: search='{query}'")
            print(f"    filename: {filename}")
            print(f"    url: {url}")
            print()
    else:
        print("No images found for either style in Widen media library.")
        print("These will need images from an alternative source (manufacturer CDN).")

if __name__ == '__main__':
    main()
