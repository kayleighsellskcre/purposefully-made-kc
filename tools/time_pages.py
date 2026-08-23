"""Time the server's own response for the main pages.

    py -3.12 tools/time_pages.py                       # against the dev server
    py -3.12 tools/time_pages.py --base https://...    # against anything

This measures time-to-last-byte from the server only, not rendering, so it
isolates slow view code and slow queries from slow images. Each page is hit
twice and the better time is kept, so a cold import is not mistaken for a
performance problem.
"""
import argparse
import statistics
import time
import urllib.error
import urllib.request

PAGES = [
    ('/', 'home'),
    ('/shop/', 'shop — all products'),
    ('/shop/?category=tees', 'shop — filtered'),
    ('/shop/?q=hoodie', 'shop — search'),
    ('/shop/designs', 'design gallery'),
    ('/shop/group-orders', 'group orders'),
    ('/custom-design/', 'design request landing'),
    ('/cart/', 'cart (empty)'),
    ('/about', 'about'),
    ('/contact', 'contact'),
    ('/auth/login', 'sign in'),
    ('/sitemap.xml', 'sitemap'),
    ('/robots.txt', 'robots'),
]


def timed(url):
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    except Exception as exc:
        return None, 0, str(exc)
    return time.perf_counter() - start, status, len(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:5055')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()

    print(f'{"page":<28} {"status":>6} {"best":>9} {"median":>9} {"KB":>8}')
    print('-' * 66)
    slow = []
    for path, label in PAGES:
        times, status, size = [], None, 0
        for _ in range(args.runs):
            elapsed, status, size = timed(args.base + path)
            if elapsed is None:
                print(f'{label:<28} {"ERR":>6}  {size}')
                break
            times.append(elapsed)
        if not times:
            continue
        best = min(times)
        median = statistics.median(times)
        kb = size / 1024 if isinstance(size, int) else 0
        print(f'{label:<28} {status:>6} {best*1000:>8.0f}ms {median*1000:>8.0f}ms {kb:>7.0f}')
        if best > 0.8:
            slow.append((label, best))

    if slow:
        print('\nSlower than 800ms:')
        for label, best in sorted(slow, key=lambda x: -x[1]):
            print(f'  {best*1000:.0f}ms  {label}')
    else:
        print('\nEvery page responded in under 800ms.')


if __name__ == '__main__':
    main()
