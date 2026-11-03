"""Build the Bella+Canvas colors SanMar sells that the shop does not have yet.

For each color: download SanMar's garment-only FLAT front and back photos (never the on-model ones), frame them
on the same 1000 x 1250 canvas as the other flat mockups, save them under static/images/products/<STYLE>/, and
write scripts/new_bella_colors_plan.json for apply_new_bella_colors.py. Nothing in the database is touched here.

    python scripts/build_missing_bella_colors.py
"""
import io
import json
import re
import sys
import urllib.request as urlreq
from pathlib import Path

import requests
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

# Colors SanMar carries (with stock) for these styles that the shop had no entry for.
WANTED = {
    'BC3005': ['Charcoal Black Slub', 'Charcoal Marble', 'Navy Marble', 'True Royal Marble'],
    'BC3480': ['Aqua Triblend', 'Black Heather', 'Charcoal-Black Triblend', 'Grey Triblend', 'White Fleck Triblend'],
    'BC8800': ['Coral', 'Dark Grey', 'Heather Deep Teal', 'Kelly', 'Mauve Marble', 'Military Green', 'Neon Pink',
               'Peach', 'Peach Slub', 'Soft Pink', 'Solid Black Slub', 'Sunset', 'Teal', 'True Royal', 'True Royal Marble'],
}
TANKS = {'BC3480', 'BC8800'}
# SanMar has no flat photos for these; S&S has garment-only ones for the same Bella+Canvas color.
FALLBACK = {
    ('BC8800', 'True Royal'): {
        'front': 'https://cdn.ssactivewear.com/Images/Color/32835_f_fm.jpg',
        'back': 'https://cdn.ssactivewear.com/Images/Color/32835_b_fm.jpg',
        'swatch': '',
    },
}
OUT_DIR = ROOT / 'static' / 'images' / 'products'
PLAN = ROOT / 'scripts' / 'new_bella_colors_plan.json'


def product_info(style):
    from services.sanmar_api import get_credentials
    c, u, p = get_credentials()
    body = (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:impl="http://impl.webservice.integration.sanmar.com/"><soapenv:Header/><soapenv:Body>'
        f'<impl:getProductInfoByStyleColorSize><arg0><style>{style}</style></arg0><arg1>'
        f'<sanMarCustomerNumber>{c}</sanMarCustomerNumber><sanMarUserName>{u}</sanMarUserName>'
        f'<sanMarUserPassword>{p}</sanMarUserPassword></arg1></impl:getProductInfoByStyleColorSize>'
        '</soapenv:Body></soapenv:Envelope>'
    ).encode()
    req = urlreq.Request('https://ws.sanmar.com:8080/SanMarWebService/SanMarProductInfoServicePort', data=body,
                         headers={'Content-Type': 'text/xml; charset=utf-8'})
    return urlreq.urlopen(req, timeout=90).read().decode('utf-8', 'replace')


def color_blocks(xml):
    found = {}
    for block in re.findall(r'<listResponse>(.*?)</listResponse>', xml, re.S):
        m = re.search(r'<color>([^<]*)</color>', block)
        if not m or m.group(1) in found:
            continue
        def field(tag):
            f = re.search(rf'<{tag}>([^<]+)</{tag}>', block)
            return f.group(1).strip() if f else ''
        found[m.group(1)] = {'front': field('frontFlat'), 'back': field('backFlat'), 'swatch': field('colorSquareImage')}
    return found


def frame(img, tank):
    from services.image_normalize import normalize_image
    return normalize_image(img, tight_crop_fallback=tank, center_horizontally=True)


def garment_hex(img):
    """Average color of the middle of the garment, as #rrggbb."""
    w, h = img.size
    crop = img.convert('RGB').crop((int(w * .38), int(h * .32), int(w * .62), int(h * .5))).resize((1, 1), Image.LANCZOS)
    return '#%02x%02x%02x' % crop.getpixel((0, 0))


def main():
    plan = []
    for style, colors in WANTED.items():
        blocks = color_blocks(product_info(style))
        for color in colors:
            b = blocks.get(color)
            if (not b or not b['front'] or not b['back']) and (style, color) in FALLBACK:
                b = FALLBACK[(style, color)]
            if not b or not b['front'] or not b['back']:
                print(f'  SKIP {style} {color}: SanMar has no flat front and back photos for it')
                continue
            slug = re.sub(r'[^A-Za-z0-9]+', '_', color).strip('_')
            folder = OUT_DIR / style
            folder.mkdir(parents=True, exist_ok=True)
            saved = {}
            hex_value = None
            for side in ('front', 'back'):
                raw = requests.get(b[side], timeout=90)
                raw.raise_for_status()
                src = Image.open(io.BytesIO(raw.content))
                src.load()
                if side == 'front':
                    hex_value = garment_hex(src)
                framed = frame(src, style in TANKS)
                name = f'{style}_{slug}_{side}_flat.jpg'
                framed.save(folder / name, format='JPEG', quality=92, optimize=True)
                saved[side] = f'/static/images/products/{style}/{name}'
            plan.append({'style': style, 'color': color, 'hex': hex_value, 'swatch': b['swatch'],
                         'front': saved['front'], 'back': saved['back']})
            print(f'  OK   {style} {color} {hex_value}')
    PLAN.write_text(json.dumps(plan, indent=1), encoding='utf-8')
    print(f'{len(plan)} colors written to {PLAN.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
