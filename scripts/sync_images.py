"""
sync_images.py  —  Run from Cursor terminal (project root)

    python scripts/sync_images.py

You'll be prompted for two cookie values you can copy from Chrome DevTools.
No other setup needed.
"""

import json, re, time, sys, requests

ACCOUNT_ID = '47526418'
EMBED_BASE = f'https://embed.widencdn.net/img/{ACCOUNT_ID}'
ML_API     = 'https://medialibrary1.com/api/rest/asset/search'
FLASK_URL  = 'https://purposefullymadekc.com/admin/products/import-media-library-images'

BC_STYLES = [
    'BC100B','BC1010','BC1012','BC1019','BC1080','BC1200','BC1201','BC1501',
    'BC3001','BC3001B','BC3001CVC','BC3001T','BC3001Y','BC3001YCVC',
    'BC3005','BC3005CVC','BC3010','BC3010Y','BC3200','BC3413','BC3413T',
    'BC3413Y','BC3415','BC3480','BC3480CVC','BC3480Y','BC3480YCVC','BC3483',
    'BC3501','BC3501CVC','BC3501T','BC3501Y','BC3501YCVC','BC3511','BC3511Y',
    'BC3512','BC3513','BC3650','BC3655','BC3719','BC3719T','BC3719Y',
    'BC3725','BC3727','BC3729','BC3738','BC3738Y','BC3739','BC3739Y',
    'BC3787','BC3901','BC3901Y','BC3909','BC3911','BC3945','BC4540',
    'BC4610','BC4651','BC4711','BC4719','BC4737','BC4739','BC4740','BC4741',
    'BC4810GD','BC4851GD','BC6003','BC6004','BC6008','BC6110','BC6110GD',
    'BC6400','BC6400CVC','BC6405','BC6405CVC','BC6413','BC6482','BC6500',
    'BC6682','BC6824GD','BC6882GD','BC7502','BC7505','BC8413',
    'BC8800','BC8803','BC8804','BC8882',
]


def get_cookies():
    print("\n── Step 1: Get your Media Library cookie ──────────────────────────────")
    print("In Chrome, open the Media Library tab → press F12 → Application →")
    print("Cookies → medialibrary1.com → find JSESSIONID → copy its Value.\n")
    ml_cookie = input("Paste JSESSIONID value: ").strip()

    print("\n── Step 2: Get your admin cookie ───────────────────────────────────────")
    print("In Chrome, open the purposefullymadekc.com admin tab → press F12 →")
    print("Application → Cookies → purposefullymadekc.com → find 'session' → copy Value.\n")
    admin_cookie = input("Paste session value: ").strip()

    return ml_cookie, admin_cookie


def scrape(ml_cookie):
    sess = requests.Session()
    sess.cookies.set('JSESSIONID', ml_cookie, domain='medialibrary1.com')
    sess.headers['User-Agent'] = 'Mozilla/5.0'

    print(f"\nScraping {len(BC_STYLES)} styles from Media Library...")
    all_images = {}

    for i, style in enumerate(BC_STYLES, 1):
        colors = {}
        page = 1
        while True:
            try:
                r = sess.post(ML_API, json={'query': f'{style} Flat', 'limit': 50, 'page': page}, timeout=15)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f"  [{style}] error: {e}")
                break

            for asset in data.get('assets') or []:
                name = asset.get('name', '')
                m = re.match(r'^(BC\w+?)_(.+?)_Flat_(Front|Back)(?:\s*\(\d+\))?\.tif$', name, re.I)
                if not m or m.group(1) != style:
                    continue
                color = m.group(2)
                side  = m.group(3).lower()
                uuid  = asset.get('uuid', '')
                fn    = re.sub(r'\s*\(\d+\)$', '', name[:-4])
                url   = f"{EMBED_BASE}/{uuid}/1200px/{requests.utils.quote(fn)}.jpg"
                colors.setdefault(color, {})
                if side not in colors[color]:
                    colors[color][side] = url

            total = data.get('numResults', 0)
            if page * 50 >= total or not data.get('assets'):
                break
            page += 1

        if colors:
            all_images[style] = colors
            print(f"  [{i:2}/{len(BC_STYLES)}] {style}: {len(colors)} colors")
        else:
            print(f"  [{i:2}/{len(BC_STYLES)}] {style}: (none)")
        time.sleep(0.05)

    return all_images


def post_to_flask(all_images, admin_cookie):
    flat = []
    for style, colors in all_images.items():
        for color, sides in colors.items():
            flat.append({
                'style':     style,
                'color':     color,
                'front_url': sides.get('front', ''),
                'back_url':  sides.get('back', ''),
            })

    print(f"\nPOSTing {len(flat)} variants to purposefullymadekc.com...")
    sess = requests.Session()
    sess.cookies.set('session', admin_cookie, domain='purposefullymadekc.com')
    try:
        r = sess.post(FLASK_URL, json={'images': flat}, timeout=120)
        print(f"Status: {r.status_code}")
        print(r.text[:300])
    except Exception as e:
        print(f"POST failed: {e}")


def main():
    ml_cookie, admin_cookie = get_cookies()

    # Quick auth test
    print("\nTesting Media Library auth...")
    try:
        s = requests.Session()
        s.cookies.set('JSESSIONID', ml_cookie, domain='medialibrary1.com')
        r = s.post(ML_API, json={'query': 'BC3001 Flat', 'limit': 1, 'page': 1}, timeout=10)
        data = r.json()
        count = data.get('numResults', 0)
        if count == 0:
            print("WARNING: Got 0 results — cookie may be wrong or expired.")
        else:
            print(f"Auth OK — found {count} results for BC3001.")
    except Exception as e:
        print(f"Auth test failed: {e}")
        sys.exit(1)

    all_images = scrape(ml_cookie)
    total = sum(len(c) for c in all_images.values())
    print(f"\nTotal: {total} variants across {len(all_images)} styles.")

    post_to_flask(all_images, admin_cookie)
    print("\nDone! Check your shop — images should now appear.")


if __name__ == '__main__':
    main()
