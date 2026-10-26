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
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(load_image, urls))
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
    return list(dict.fromkeys(urls))[:3]


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
    return list(dict.fromkeys(urls))[:4]


def _shirt_picks(products, store=None, limit=4):
    """[(picture address, caption)] for up to ``limit`` shirts: one of each kind, tees and hoodies first."""
    from flask import current_app
    from utils.group_orders import allowed_colors_for_product
    from utils.mockups import get_carousel_colors_for_product
    chosen, seen = [], set()
    ranked = sorted(products, key=lambda p: (SHIRT_ORDER.index(p.category) if p.category in SHIRT_ORDER else 99, p.id))
    for product in ranked:
        if len(chosen) >= limit or not getattr(product, 'is_active', True):
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
        url = next((v.get('front_image_url') for v in variants if v.get('front_image_url')), None)
        if url:
            seen.add(key)
            chosen.append((url, product.category or 'Shirt'))
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
                    deadline=DS.school_deadline(obj), logos=_school_logo_urls(obj)[:4],
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

def build(obj, school=None):
    """The flyer as PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from utils import districts as DS

    plan = _plan(obj, school)
    images = load_images(plan['logos'] + [u for u, _ in plan['shirts']])
    logos = [images[u] for u in plan['logos'] if u in images]
    shirts = [(images[u], cap) for u, cap in plan['shirts'] if u in images]

    w, h = letter
    accent = colors.HexColor(plan['school_color'])
    ink, muted, sand, cream = colors.HexColor(INK), colors.HexColor(MUTED), colors.HexColor(SAND), colors.HexColor(CREAM)
    link = DS.short_url(obj, school)
    qr = ImageReader(io.BytesIO(DS.qr_png(link)))

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"{plan['title']} flyer")
    c.setFillColor(cream)
    c.rect(0, 0, w, h, stroke=0, fill=1)
    c.setFillColor(accent)
    c.rect(0, h - 14, w, 14, stroke=0, fill=1)
    c.setStrokeColor(sand)
    c.setLineWidth(0.8)
    c.rect(26, 26, w - 52, h - 52 - 14, stroke=1, fill=0)

    def centered(text, y, font, size, fill, x=None, max_width=None):
        max_width = max_width or (w - 110)
        c.setFont(font, size)
        c.setFillColor(fill)
        while c.stringWidth(text, font, size) > max_width and size > 11:
            size -= 1
            c.setFont(font, size)
        c.drawCentredString(w / 2 if x is None else x, y, text)

    def tile(x, y, size, png, caption=None):
        c.setFillColor(colors.white)
        c.setStrokeColor(sand)
        c.roundRect(x, y, size, size, 10, stroke=1, fill=1)
        im = ImageReader(io.BytesIO(png))
        iw, ih = im.getSize()
        pad = 9
        scale = min((size - 2 * pad) / iw, (size - 2 * pad) / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(im, x + (size - dw) / 2, y + (size - dh) / 2, dw, dh, mask='auto')
        if caption:
            centered(caption.upper(), y - 13, 'Helvetica-Bold', 7.5, muted, x=x + size / 2, max_width=size + 14)

    def row(items, y, size, caption=False, gap=16):
        n = len(items)
        total = n * size + (n - 1) * gap
        x = (w - total) / 2
        for item in items:
            png, cap = item if caption else (item, None)
            tile(x, y, size, png, cap)
            x += size + gap

    y = h - 62
    centered('PURPOSEFULLY MADE KC', y, 'Helvetica-Bold', 9.5, accent)
    y -= 30
    if plan['top'] and plan['top'] != plan['title']:
        centered(plan['top'].upper(), y, 'Helvetica', 11, muted)
        y -= 38
    else:
        y -= 14
    centered(plan['title'], y, 'Times-Roman', 40, ink)
    if plan['sub']:
        y -= 28
        centered(plan['sub'], y, 'Times-Italic', 17, muted)
    if plan['tagline']:
        y -= 25
        centered(plan['tagline'], y, 'Times-Italic', 17, accent)

    # the school's logos, then a few of the shirts people can choose
    if logos:
        size = 92 if len(logos) <= 3 else 80
        y -= size + 26
        row(logos, y, size)
    if shirts:
        y -= 28
        centered('PICK YOUR STYLE', y, 'Helvetica-Bold', 8.5, accent)
        size = 96 if len(shirts) <= 3 else 90
        y -= size + 14
        row(shirts, y, size, caption=True)
        y -= 14

    # the QR code and the words under or beside it
    floor = 70
    if logos or shirts:
        avail = y - floor - 20
        side = max(120, min(210, avail - 36))
        qx = 58
        qy = floor + (avail - side) / 2 + 6
        c.setFillColor(colors.white)
        c.setStrokeColor(sand)
        c.roundRect(qx - 14, qy - 14, side + 28, side + 28, 12, stroke=1, fill=1)
        c.drawImage(qr, qx, qy, side, side)
        tx = qx + side + 28 + 24
        tw = w - 58 - tx
        mid = qy + side / 2
        lines = [('Scan to order', 'Helvetica-Bold', 13, accent)]
        c.setFillColor(accent)
        c.setFont('Helvetica-Bold', 13)
        c.drawString(tx, mid + 58, 'SCAN TO ORDER')
        c.setFillColor(ink)
        shown = link.split('://', 1)[-1]
        size_link = 16
        c.setFont('Helvetica', size_link)
        while c.stringWidth(shown, 'Helvetica', size_link) > tw and size_link > 9:
            size_link -= 1
            c.setFont('Helvetica', size_link)
        c.drawString(tx, mid + 30, shown)
        yy = mid
        if plan['deadline']:
            d = plan['deadline']
            c.setFont('Times-Roman', 22)
            c.setFillColor(ink)
            c.drawString(tx, yy - 6, f"Order by {d.strftime('%B')} {d.day}")
            yy -= 34
        if plan['delivery']:
            c.setFont('Helvetica', 10.5)
            c.setFillColor(muted)
            c.drawString(tx, yy - 4, 'Sent home with your child.' if plan['delivery'] == 'sent' else 'Pick up at the school.')
    else:
        side = 3.9 * 72 if y > 360 else 3.2 * 72
        qx, qy = (w - side) / 2, h / 2 - side / 2 - 30
        c.setFillColor(colors.white)
        c.setStrokeColor(sand)
        c.roundRect(qx - 18, qy - 18, side + 36, side + 36, 12, stroke=1, fill=1)
        c.drawImage(qr, qx, qy, side, side)
        centered('SCAN TO ORDER', qy - 52, 'Helvetica-Bold', 11, accent)
        centered(link.split('://', 1)[-1], qy - 82, 'Helvetica', 20, ink)
        if plan['deadline']:
            d = plan['deadline']
            centered(f"Order by {d.strftime('%B')} {d.day}", qy - 118, 'Times-Roman', 22, ink)
    centered('Made with purpose, in Shawnee, Kansas', 46, 'Helvetica', 8.5, muted)
    c.showPage()
    c.save()
    return buf.getvalue()
