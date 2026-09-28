"""
Download Comfort Colors 9360 S&S ghost flats, pad them onto the same 2:3
card as the other Comfort Colors Widen photos, and point the product at
the local files.

    py -3.12 scripts/frame_cc9360_mockups.py --dry-run
    py -3.12 scripts/frame_cc9360_mockups.py
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from datetime import datetime
from urllib.parse import urlparse

import requests
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))
os.environ['SCHEDULER_ENABLED'] = '0'

FOLDER = '9360'
STYLE_TRIES = ('CC9360', '9360', 'C9360')
TIMEOUT = 40


def _safe_color(name: str) -> str:
    cleaned = re.sub(r'[^\w]+', '_', (name or '').strip(), flags=re.UNICODE)
    return cleaned.strip('_') or 'color'


def _filename(color_name: str, side: str) -> str:
    return f'{FOLDER}_{_safe_color(color_name)}_{side}.jpg'


def _public_url(filename: str) -> str:
    return f'/static/sanmar/{FOLDER}/{filename}'


def _dest_dir() -> str:
    path = os.path.join(ROOT, 'static', 'sanmar', FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def _load_image(url: str) -> Image.Image | None:
    if not url:
        return None
    url = url.replace('{quality}', '80').replace('%7Bquality%7D', '80')
    parsed = urlparse(url)
    if parsed.scheme in ('http', 'https'):
        last_err = None
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=TIMEOUT)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content))
                img.load()
                return img
            except Exception as exc:
                last_err = exc
                if attempt < 2:
                    continue
                raise last_err
    rel = url.lstrip('/').replace('\\', '/')
    if rel.startswith('static/'):
        path = os.path.join(ROOT, *rel.split('/'))
        if os.path.isfile(path):
            img = Image.open(path)
            img.load()
            return img
    return None


def frame_and_save(img: Image.Image, dest_path: str) -> None:
    from services.image_normalize import frame_tank_image
    framed = frame_tank_image(img)
    framed.save(dest_path, format='JPEG', quality=92, optimize=True)


def run(db, Product, ProductColorVariant, dry_run: bool = False, files_only: bool = False) -> dict:
    product = None
    for style in STYLE_TRIES:
        product = Product.query.filter_by(style_number=style).first()
        if product:
            break
    if not product:
        raise SystemExit('CC9360 product not found')

    variants = ProductColorVariant.query.filter_by(product_id=product.id).all()
    dest = _dest_dir()
    saved = 0
    failed = []
    first_front = None
    first_back = None
    write_db = not dry_run and not files_only

    print(f'  product {product.style_number} id={product.id}  colors={len(variants)}')
    print(f'  dest    {dest}')

    for variant in variants:
        color = variant.color_name or ''
        if not color:
            continue
        for side, src in (
            ('front', variant.front_image_url),
            ('back', variant.back_image_url),
        ):
            filename = _filename(color, side)
            dest_path = os.path.join(dest, filename)
            public = _public_url(filename)
            try:
                dest_ready = os.path.isfile(dest_path)
                if dest_ready and not dry_run:
                    if side == 'front' and not first_front:
                        first_front = public
                    if side == 'back' and not first_back:
                        first_back = public
                    if write_db:
                        if side == 'front':
                            variant.front_image_url = public
                        else:
                            variant.back_image_url = public
                    saved += 1
                    print(f'  skip {color} {side} (already framed)')
                    continue
                img = _load_image(src or '')
                if img is None:
                    raise RuntimeError(f'no source image ({src!r})')
                if dry_run:
                    print(f'  would frame {color} {side}  {img.size} -> {public}')
                else:
                    frame_and_save(img, dest_path)
                    if write_db:
                        if side == 'front':
                            variant.front_image_url = public
                            if not first_front:
                                first_front = public
                        else:
                            variant.back_image_url = public
                            if not first_back:
                                first_back = public
                    elif side == 'front' and not first_front:
                        first_front = public
                    elif side == 'back' and not first_back:
                        first_back = public
                    saved += 1
                    print(f'  framed {color} {side}')
            except Exception as exc:
                failed.append(f'{color} {side}: {exc}')
                print(f'  FAIL {color} {side}: {exc}')

        if write_db:
            variant.last_synced = datetime.utcnow()

    if write_db:
        if first_front:
            product.front_mockup_template = first_front
        if first_back:
            product.back_mockup_template = first_back
        db.session.commit()

    return {'saved': saved, 'failed': failed, 'colors': len(variants)}


def main():
    parser = argparse.ArgumentParser(description='Frame CC9360 tank mockups')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument(
        '--files-only', action='store_true',
        help='Write framed JPEGs without changing database URLs',
    )
    args = parser.parse_args()

    mode = 'DRY RUN — ' if args.dry_run else ('FILES ONLY — ' if args.files_only else '')
    print(f"\n{mode}Frame Comfort Colors 9360 tank\n")

    from app import create_app
    from models import db, Product, ProductColorVariant

    app = create_app()
    with app.app_context():
        result = run(
            db, Product, ProductColorVariant,
            dry_run=args.dry_run, files_only=args.files_only,
        )
        print(f"\nDone. saved={result['saved']}  failed={len(result['failed'])}")
        if result['failed']:
            for row in result['failed']:
                print(f'  {row}')
            sys.exit(1)


if __name__ == '__main__':
    main()
