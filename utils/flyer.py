"""The one-page letter-size flyer for a district, school or store.

Who it is for, the school's logos, a few of the shirts people can pick, a large QR code, the short link written out
and the order deadline. Pictures are fetched when the flyer is made; one that cannot be loaded is simply left out, so
a flyer always prints.
"""
from __future__ import annotations

import io
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from models import District, Organization

CREAM, INK, MUTED, SAND, WHITE = '#FBF6EE', '#3A3D48', '#7A7C86', '#E8D0B1', '#FFFFFF'
MAX_BYTES = 4 * 1024 * 1024
FETCH_SECONDS = 5
_CACHE = {}
_CACHE_SECONDS = 600
SHIRT_ORDER = ('Tee', 'Hoodie', 'Long Sleeve', 'Sweatshirt', 'Tank', 'V-Neck', 'Onesie')


# ── pictures ───────────────────────────────────────────────────────────────────────────────

def _local_path(url):
    """The file on disk for a /static/ or /uploads/ address, or None."""
    from flask import current_app
    root = current_app.root_path
    path = url.split('?', 1)[0]
    if path.startswith('/uploads/'):
        for base in ('uploads', os.path.join('static', 'uploads')):
            candidate = os.path.normpath(os.path.join(root, base, path[len('/uploads/'):]))
            if candidate.startswith(os.path.join(root, base)) and os.path.isfile(candidate):
                return candidate
        return None
    if path.startswith('/static/'):
        candidate = os.path.normpath(os.path.join(root, 'static', path[len('/static/'):]))
        if candidate.startswith(os.path.join(root, 'static')) and os.path.isfile(candidate):
            return candidate
    return None


def _read(url):
    if not url:
        return None
    local = _local_path(url) if url.startswith('/') else None
    if local:
        with open(local, 'rb') as fh:
            return fh.read(MAX_BYTES)
    if url.startswith(('http://', 'https://')):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 PMKC-flyer', 'Referer': 'https://purposefullymadekc.com/'})
        with urllib.request.urlopen(req, timeout=FETCH_SECONDS) as resp:
            return resp.read(MAX_BYTES)
    return None


def load_image(url):
    """PNG bytes for a picture address (shrunk for the page), or None when it cannot be loaded. Cached for a few minutes."""
    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    result = None
    try:
        raw = _read(url)
        if raw:
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            im.load()
            im = im.convert('RGBA')
            im.thumbnail((520, 520))
            out = io.BytesIO()
            im.save(out, format='PNG', optimize=True)
            result = out.getvalue()
    except Exception:
        result = None
    _CACHE[url] = (time.time(), result)
    return result


def load_images(urls):
    """{url: png bytes} for the pictures that loaded, fetched side by side."""
    urls = [u for u in dict.fromkeys(urls) if u]
    if not urls:
        return {}
    from flask import current_app
    app = current_app._get_current_object()

    def fetch(url):
        with app.app_context():                           # the worker threads need the app to find files on disk
            return load_image(url)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, urls))
    return {u: r for u, r in zip(urls, results) if r}


# ── what goes on the flyer ─────────────────────────────────────────────────────────────────

def _store_logo_urls(store, school):
    from utils import districts as DS
    from utils.cloud_storage import image_url
    from utils.group_orders import load_showcase_designs
    urls = []
    try:
        urls += [d['url'] for d in load_showcase_designs(store)]
    except Exception:
        pass
    if school is not None:
        urls += [x['url'] for x in DS.school_logos(school)]
        if school.logo_url:
            urls.append(image_url(school.logo_url))
    if getattr(store, 'cover_image', None):
        urls.append(image_url(store.cover_image))
    return list(dict.fromkeys(urls))[:8]


def _school_logo_urls(school):
    from utils import districts as DS
    from utils.cloud_storage import image_url
    urls = [image_url(school.logo_url)] if school.logo_url else []
    urls += [x['url'] for x in DS.school_logos(school)]
    return list(dict.fromkeys(urls))


def _district_logo_urls(district):
    from utils.cloud_storage import image_url
    urls = [image_url(district.logo_url)] if district.logo_url else []
    for school in district.schools.all():
        first = _school_logo_urls(school)
        if first:
            urls.append(first[0])
    return list(dict.fromkeys(urls))[:8]


def _shirt_picks(products, store=None, limit=8):
    """[(picture address, caption)] for up to ``limit`` shirts: one of each kind first (tees and hoodies lead),
    then more colors of the same styles so even a small store shows what it offers."""
    from flask import current_app
    from utils.group_orders import allowed_colors_for_product
    from utils.mockups import get_carousel_colors_for_product
    ranked = sorted(products, key=lambda p: (SHIRT_ORDER.index(p.category) if p.category in SHIRT_ORDER else 99, p.id))
    pools, seen = [], set()
    for product in ranked:
        if not getattr(product, 'is_active', True):
            continue
        age = (getattr(product, 'age_group', None) or 'adult').lower()
        key = (product.category, age in ('adult', 'unisex', ''))
        if key in seen or age in ('toddler', 'baby', 'infant'):
            continue
        try:
            allowed = allowed_colors_for_product(product, store) if store is not None else None
            variants = get_carousel_colors_for_product(product, current_app, allowed_colors=allowed)
        except Exception:
            variants = []
        found = [(v.get('front_image_url'), v.get('color_name')) for v in variants if v.get('front_image_url')]
        if found:
            seen.add(key)
            pools.append((product.category or 'Shirt', found))
    chosen = [(found[0][0], cat) for cat, found in pools][:limit]
    depth = 1
    while len(chosen) < limit and any(len(found) > depth for _c, found in pools):
        for cat, found in pools:
            if len(found) > depth and len(chosen) < limit:
                chosen.append((found[depth][0], (found[depth][1] or cat)))
        depth += 1
    return chosen


def _plan(obj, school):
    """Everything the flyer says and shows: a dict of plain values."""
    from utils import districts as DS
    from utils.districts import SPIRIT_TAGLINE
    plan = {'logos': [], 'shirts': [], 'school_color': '#B87C6F', 'tagline': None, 'delivery': None}
    if isinstance(obj, District):
        plan.update(top='', title=obj.name, sub='Spirit wear for every school', deadline=obj.order_deadline,
                    logos=_district_logo_urls(obj), shirts=_shirt_picks(DS.district_styles(obj)))
    elif isinstance(obj, Organization):
        stores = DS.live_stores(obj) or DS.stores_of(obj)
        spirit = DS.spirit_store(obj)
        products = list((spirit or (stores[0] if stores else None)).products) if (spirit or stores) else []
        plan.update(top=obj.district.name, title=obj.name, sub=f'Home of the {obj.mascot}' if obj.mascot else None,
                    deadline=DS.school_deadline(obj), logos=_school_logo_urls(obj)[:8],
                    shirts=_shirt_picks(products, spirit), school_color=DS.accent(obj),
                    delivery='sent' if (obj.delivery_mode or 'send_home') == 'send_home' else 'pickup')
    else:
        school = school or DS.school_for_store(obj)
        plan.update(top=school.name if school else '', title=obj.name,
                    sub=f'Home of the {school.mascot}' if school and school.mascot else None,
                    deadline=obj.order_deadline or (DS.school_deadline(school) if school else None),
                    logos=_store_logo_urls(obj, school), shirts=_shirt_picks(list(obj.products), obj),
                    tagline=SPIRIT_TAGLINE if obj.store_kind == 'spirit' else None,
                    school_color=DS.accent(school) if school else '#B87C6F')
        if school is not None:
            plan['delivery'] = 'sent' if (school.delivery_mode or 'send_home') == 'send_home' else 'pickup'
    return plan


# ── drawing ────────────────────────────────────────────────────────────────────────────────

# Where a design sits on each garment, as fractions of the garment photo once it is trimmed to the garment:
# (top of the design, width available, tallest it may be). Hoodies start lower because of the hood.
_CHEST = {
    'tee': (.18, .44, .30), 'hoodie': (.28, .38, .28), 'sweatshirt': (.20, .40, .28), 'long sleeve': (.18, .36, .28),
    'tank': (.22, .44, .28), 'v-neck': (.20, .40, .28), 'onesie': (.22, .40, .28),
}


def trim_to_garment(shirt_png):
    """The garment photo cropped to the garment itself (the product photos are surrounded by white), so it fills its tile."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(shirt_png)).convert('RGBA')
        box = im.convert('L').point(lambda v: 255 if v < 244 else 0).getbbox()
        if not box or (box[2] - box[0]) * (box[3] - box[1]) < im.width * im.height * .2:
            return shirt_png
        pad = int(max(box[2] - box[0], box[3] - box[1]) * .03)
        im = im.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
        out = io.BytesIO()
        im.save(out, format='PNG')
        return out.getvalue()
    except Exception:
        return shirt_png


def _brightness(png, center_only=False):
    """0 (black) to 255 (white): the average of the visible pixels of a picture, or of the middle of a garment."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert('RGBA')
        if center_only:
            im = im.crop((int(im.width * .3), int(im.height * .3), int(im.width * .7), int(im.height * .6)))
        im.thumbnail((48, 48))
        total = count = 0
        for r, g, b, a in im.getdata():
            if a > 40:
                total += .299 * r + .587 * g + .114 * b
                count += 1
        return total / count if count else 128
    except Exception:
        return 128


def pick_logos(shirt_pngs, logo_pngs):
    """The index of the logo each garment wears: the one that shows best against that garment's color, taking turns so
    every logo gets used."""
    garment = [_brightness(trim_to_garment(p), True) for p in shirt_pngs]
    art = [_brightness(p) for p in logo_pngs]
    uses = [0] * len(logo_pngs)
    picks = []
    for g in garment:
        best = max(range(len(logo_pngs)), key=lambda i: abs(g - art[i]) - 45 * uses[i])
        uses[best] += 1
        picks.append(best)
    return picks


def with_chest_logo(shirt_png, logo_png, kind=None):
    """The shirt photo with a logo placed on the chest the way it would print on that kind of garment."""
    try:
        from PIL import Image
        shirt = Image.open(io.BytesIO(trim_to_garment(shirt_png))).convert('RGBA')
        art = Image.open(io.BytesIO(logo_png)).convert('RGBA')
        box = art.getbbox()
        if box:
            art = art.crop(box)
        top, wide, tall = _CHEST.get((kind or 'tee').strip().lower(), _CHEST['tee'])
        scale = min(shirt.width * wide / art.width, shirt.height * tall / art.height)
        size = (int(art.width * scale), int(art.height * scale))
        if size[0] < 12 or size[1] < 12:
            return shirt_png
        art = art.resize(size, Image.LANCZOS)
        shirt.alpha_composite(art, ((shirt.width - size[0]) // 2, int(shirt.height * top)))
        out = io.BytesIO()
        shirt.save(out, format='PNG')
        return out.getvalue()
    except Exception:
        return shirt_png


def build(obj, school=None, style=None):
    """The flyer as PDF bytes. (``style`` is accepted so older links keep working; there is one flyer.)"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from utils import districts as DS

    plan = _plan(obj, school)
    images = load_images(plan['logos'] + [u for u, _ in plan['shirts']])
    logos = [images[u] for u in plan['logos'] if u in images]
    shirts = [(images[u], cap) for u, cap in plan['shirts'] if u in images]
    if logos:                                                  # every garment wears one of the group's logos, the one that shows best
        wears = pick_logos([p for p, _ in shirts], logos)
        shirts = [(with_chest_logo(png, logos[k], cap), cap) for (png, cap), k in zip(shirts, wears)]
    else:
        shirts = [(trim_to_garment(png), cap) for png, cap in shirts]
    wordmark = load_image('/static/img/logo-wordmark.png')

    w, h = letter
    accent_hex = plan['school_color'] or '#B87C6F'
    accent = colors.HexColor(accent_hex)
    ink, muted, sand, cream = colors.HexColor(INK), colors.HexColor(MUTED), colors.HexColor(SAND), colors.HexColor(CREAM)
    link = DS.short_url(obj, school)
    qr = ImageReader(io.BytesIO(DS.qr_png(link)))
    shown_link = link.split('://', 1)[-1]

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"{plan['title']} flyer")

    def text_fit(text, font, size, max_width, floor=10):
        while c.stringWidth(text, font, size) > max_width and size > floor:
            size -= 0.5
        return size

    def centered(text, y, font, size, fill, x=None, max_width=None):
        max_width = max_width or (w - 110)
        size = text_fit(text, font, size, max_width, 9)
        c.setFont(font, size)
        c.setFillColor(fill)
        c.drawCentredString(w / 2 if x is None else x, y, text)

    def tile(x, y, tw, th, png, caption=None, fill=WHITE):
        """A rounded white card (x, y is the bottom left) with the picture fitted inside it."""
        c.setFillColor(colors.HexColor(fill))
        c.setStrokeColor(sand)
        c.setLineWidth(0.8)
        c.roundRect(x, y, tw, th, 9, stroke=1, fill=1)
        im = ImageReader(io.BytesIO(png))
        iw, ih = im.getSize()
        pad = 6 if caption else 9
        band = 19 if caption else 0
        room = th - band
        scale = min((tw - 2 * pad) / iw, (room - 2 * pad) / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(im, x + (tw - dw) / 2, y + band + (room - dh) / 2, dw, dh, mask='auto')
        if caption:
            size = text_fit(caption.upper(), 'Helvetica-Bold', 8.5, tw - 8, 6)
            c.setFont('Helvetica-Bold', size)
            c.setFillColor(ink)
            c.drawCentredString(x + tw / 2, y + 7, caption.upper())

    def row(items, y, size, with_caption=False, gap=14):
        n = len(items)
        x = (w - (n * size + (n - 1) * gap)) / 2
        for item in items:
            png, cap = item if with_caption else (item, None)
            tile(x, y, size, size, png, cap, WHITE)
            x += size + gap

    def grid_shape(n):
        cols = n if n <= 4 else 3 if n <= 6 else 4
        return cols, -(-n // cols)

    def measure(n, height, biggest=150, gap=12):
        """(tile size, total height) of n tiles laid out in as few, as large rows as fit in ``height``."""
        cols, rows = grid_shape(n)
        size = min(biggest, (w - 90 - gap * (cols - 1)) / cols, (height - gap * (rows - 1)) / rows)
        return size, rows * size + (rows - 1) * gap

    def grid(items, top, size, gap=12):
        """Tiles of ``size`` from ``top`` down; the last row is centred."""
        cols, rows = grid_shape(len(items))
        for r in range(rows):
            chunk = items[r * cols:(r + 1) * cols]
            x = (w - (len(chunk) * size + (len(chunk) - 1) * gap)) / 2
            for png, cap in chunk:
                tile(x, top - (r + 1) * size - r * gap, size, size, png, cap, WHITE)
                x += size + gap

    def qr_footer(base, on_band=False):
        """The small QR card with its words beside it, centred; base is the bottom of the block."""
        side = 82
        text_w = 250
        total = side + 16 + 20 + text_w
        x = (w - total) / 2
        c.setFillColor(colors.white)
        c.setStrokeColor(sand)
        c.roundRect(x, base, side + 16, side + 16, 9, stroke=1, fill=1)
        c.drawImage(qr, x + 8, base + 8, side, side)
        tx = x + side + 16 + 20
        mid = base + (side + 16) / 2
        c.setFillColor(accent if not on_band else ink)
        c.setFont('Helvetica-Bold', 8.5)
        c.drawString(tx, mid + 26, 'SCAN TO ORDER')
        c.setFillColor(ink)
        size = text_fit(shown_link, 'Helvetica', 9, text_w, 6)
        c.setFont('Helvetica', size)
        c.drawString(tx, mid + 11, shown_link)
        yy = mid - 12
        if plan['deadline']:
            d = plan['deadline']
            c.setFont('Times-Roman', 17)
            c.drawString(tx, yy, f"Order by {d.strftime('%B')} {d.day}, {d.year}")
            yy -= 17
        if plan['delivery']:
            c.setFont('Helvetica', 8.5)
            c.setFillColor(muted)
            c.drawString(tx, yy, 'Sent home with your child.' if plan['delivery'] == 'sent' else 'Pick up at the school.')

    def header(top, fill=ink, soft=muted, brand=None, size=34, use_wordmark=True):
        """Brand mark, school line, title and tagline; returns the y below them."""
        y = top
        if use_wordmark and wordmark:
            mark = ImageReader(io.BytesIO(wordmark))
            mw, mh = mark.getSize()
            height_pt = 56
            c.drawImage(mark, (w - height_pt * mw / mh) / 2, top - height_pt + 14, height_pt * mw / mh, height_pt, mask='auto')
            y -= 36
        else:
            centered('PURPOSEFULLY MADE KC', y, 'Helvetica-Bold', 8.5, brand or accent)
        y -= 24
        if plan['top'] and plan['top'] != plan['title']:
            centered(plan['top'].upper(), y, 'Helvetica', 10, soft)
            y -= 34
        else:
            y -= 12
        centered(plan['title'], y, 'Times-Roman', size, fill)
        for line, font, fsz, col in ((plan['sub'], 'Times-Italic', 15, soft), (plan['tagline'], 'Times-Italic', 15, brand or accent)):
            if line:
                y -= 24
                centered(line, y, font, fsz, col)
        return y

    def frame():
        c.setFillColor(cream)
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(accent)
        c.rect(0, h - 12, w, 12, stroke=0, fill=1)
        c.setStrokeColor(sand)
        c.setLineWidth(0.8)
        c.rect(22, 22, w - 44, h - 44 - 12, stroke=1, fill=0)

    def footer_line():
        centered('Made with purpose, in Shawnee, Kansas', 34, 'Helvetica', 8, muted)

    have_pictures = bool(logos or shirts)

    frame()
    y = header(h - 56, size=38)
    if have_pictures:
        top, bottom = y - 18, 172
        shown, picks = [(png, None) for png in logos[:8]], shirts[:8]
        label = 42 if shown and picks else 26 if picks else 0          # room for "PICK YOUR STYLE" and the gaps around it
        avail = top - bottom
        logo_size = logo_total = 0
        if shown:
            rows = grid_shape(len(shown))[1]
            logo_size, logo_total = measure(len(shown), avail * (0.8 if not picks else 0.4 if rows == 1 else 0.5), 170)
        shirt_size = shirt_total = 0
        if picks:
            shirt_size, shirt_total = measure(len(picks), avail - logo_total - label)
        y = top - max(0, (avail - logo_total - label - shirt_total) / 2)         # the whole block sits centred
        if shown:
            grid(shown, y, logo_size)
            y -= logo_total + 16
        if picks:
            centered('PICK YOUR STYLE', y - 8, 'Helvetica-Bold', 9, accent)
            grid(picks, y - 26, shirt_size)
        qr_footer(66)
    else:
        _big_qr(c, qr, y, w, colors, sand, accent, ink, plan, shown_link, centered)
    footer_line()

    c.showPage()
    c.save()
    return buf.getvalue()


def _big_qr(c, qr, y, w, colors, sand, accent, ink, plan, shown_link, centered):
    """A flyer with no pictures yet: one centred QR card, so the page is never empty."""
    side = 190
    qx, qy = (w - side) / 2, max(150, y - side - 70)
    c.setFillColor(colors.white)
    c.setStrokeColor(sand)
    c.roundRect(qx - 14, qy - 14, side + 28, side + 28, 12, stroke=1, fill=1)
    c.drawImage(qr, qx, qy, side, side)
    centered('SCAN TO ORDER', qy - 40, 'Helvetica-Bold', 10, accent)
    centered(shown_link, qy - 62, 'Helvetica', 14, ink)
    if plan['deadline']:
        d = plan['deadline']
        centered(f"Order by {d.strftime('%B')} {d.day}, {d.year}", qy - 92, 'Times-Roman', 20, ink)


def build_png(obj, school=None, style=None):
    """The flyer as a high-resolution PNG, or None when the renderer is not installed."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    pdf = pdfium.PdfDocument(build(obj, school, style))
    try:
        out = io.BytesIO()
        pdf[0].render(scale=3).to_pil().convert('RGB').save(out, format='PNG', optimize=True, dpi=(216, 216))
        return out.getvalue()
    finally:
        pdf.close()
