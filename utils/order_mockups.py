"""Mockups of each shirt in an order (front and back), drawn on the server, for emailing or downloading.

One card per different shirt: the shirt photo with the logo where it will be printed, and the back with the
person's name and number. Shirts that look the same (only the size differs) share a card. The cards go on a
PDF so the customer can see exactly what they are paying for without anyone taking screenshots.
"""
from __future__ import annotations

import io
import json

# Where the logo sits on the front photo, as a percent of the photo. Chest logos are drawn at a true 3.5 to 4 inches
# (the Enter an order page uses the same numbers).
FRONT_LOOK = {
    'center_chest': (38, 46, 38, 50),      # width, max height, center top, center left
    'left_chest': (9, 10, 29, 60.5),
    'right_chest': (9, 10, 29, 39.5),
}
CARD_COLUMNS = 3          # cards per page row is 1; each card holds a front and a back side by side
CARDS_PER_PAGE = 3
PAGE = (1275, 1650)       # US letter at 150 dpi
INK = (58, 61, 72)
BG = (250, 247, 242)


def _meta(item):
    meta = getattr(item, 'back_design_details', None)
    return meta if isinstance(meta, dict) else {}


def _hex(color, fallback=(255, 255, 255)):
    c = (color or '').strip().lstrip('#')
    if len(c) == 3:
        c = ''.join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return fallback


def look_key(item):
    """Two items with the same key look identical, so they share one card."""
    m = _meta(item)
    return (item.product_id, (item.color or '').lower(), item.design_id, (item.placement or 'center_chest'),
            (m.get('name') or '').upper(), str(m.get('number') or ''), m.get('font') or '', m.get('text_color') or '',
            getattr(item, 'back_design_file_name', None) or '')


def _open(url):
    from PIL import Image
    from utils.flyer import _read
    raw = _read(url) if url else None
    if not raw:
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img.convert('RGBA')
    except Exception:
        return None


def _on_backdrop(shirt):
    from PIL import Image
    backdrop = tuple(shirt.convert('RGB').getpixel((2, 2)))
    base = Image.new('RGBA', shirt.size, backdrop + (255,))
    base.alpha_composite(shirt)
    return base, backdrop


def _paste_logo(base, art, width_pct, max_h_pct, top_pct, left_pct):
    from PIL import Image
    sw, sh = base.size
    aw = sw * width_pct / 100.0
    ah = aw * art.height / max(art.width, 1)
    if ah > sh * max_h_pct / 100.0:
        ah = sh * max_h_pct / 100.0
        aw = ah * art.width / max(art.height, 1)
    art = art.resize((max(1, int(aw)), max(1, int(ah))), Image.LANCZOS)
    base.alpha_composite(art, (int(sw * left_pct / 100.0 - art.width / 2), int(sh * top_pct / 100.0 - art.height / 2)))


def _finish(base, backdrop):
    from utils.share_preview import _trim_margins
    return _trim_margins(base, backdrop).convert('RGB')


def render_front(item, shirt_url, design_url):
    """The front of this shirt, or None when the photo or the logo cannot be loaded."""
    shirt, art = _open(shirt_url), _open(design_url)
    if shirt is None:
        return None
    base, backdrop = _on_backdrop(shirt)
    if art is not None:
        w, mh, top, left = FRONT_LOOK.get((item.placement or 'center_chest'), FRONT_LOOK['center_chest'])
        _paste_logo(base, art, w, mh, top, left)
    return _finish(base, backdrop)


def render_back(item, shirt_url, back_art_url=None):
    """The back with the name and number (or the back logo), or None when there is nothing to show."""
    from PIL import ImageDraw
    from utils.personalization_layout import font_path, name_font_name
    meta = _meta(item)
    name, number = (meta.get('name') or '').strip().upper(), str(meta.get('number') or '').strip()
    art = None if (name or number) else _open(back_art_url)
    if not (name or number or art):
        return None
    shirt = _open(shirt_url)
    if shirt is None:
        return None
    base, backdrop = _on_backdrop(shirt)
    W, H = base.size
    if art is not None:
        _paste_logo(base, art, 40, 40, 34, 50)
    else:
        from PIL import ImageFont
        fname = name_font_name(meta.get('font') or 'Bebas Neue')
        path = font_path(fname)
        color = _hex(meta.get('text_color'))
        draw = ImageDraw.Draw(base)

        def text(value, size_pct_w, top_pct):
            font = ImageFont.truetype(str(path), max(8, int(W * size_pct_w / 100.0))) if path else ImageFont.load_default()
            draw.text((W / 2, H * top_pct / 100.0), value, font=font, fill=color + (255,), anchor='mt')
        if name:
            text(name, max(3.5, min(6.5, 66.0 / max(5, len(name)))), 20)         # about 2 inches tall
        if number:
            text(number, 23, 30)                                                    # about 7 inches tall
    return _finish(base, backdrop)


def _caption(items):
    m = _meta(items[0])
    who = ' '.join(x for x in [('#' + str(m['number'])) if m.get('number') else '', (m.get('name') or '').upper()] if x)
    sizes = ', '.join(f'{i.size} x{int(i.quantity or 1)}' for i in items)
    first = items[0]
    line = ' - '.join(x for x in [who, first.product_name, first.color] if x)
    return line, sizes


def build_cards(order, items=None):
    """[(caption, sizes, front_image_or_None, back_image_or_None)], one per different shirt."""
    from utils.order_artwork import back_print_url, front_print_url, items_of, mockup_urls
    groups, order_keys = {}, []
    for item in (items if items is not None else items_of(order)):
        k = look_key(item)
        if k not in groups:
            groups[k] = []
            order_keys.append(k)
        groups[k].append(item)
    cards = []
    for k in order_keys:
        its = groups[k]
        item = its[0]
        front_url, back_url = mockup_urls(getattr(item, 'product', None), item.color)
        front = render_front(item, front_url, front_print_url(item)) if front_url else None
        back = render_back(item, back_url, back_print_url(item)) if back_url else None
        if front is None and back is None:
            continue
        line, sizes = _caption(its)
        cards.append((line, sizes, front, back))
    return cards


def _page_with_cards(cards, title, first):
    from PIL import Image, ImageDraw, ImageFont
    from utils.personalization_layout import font_path
    page = Image.new('RGB', PAGE, BG)
    d = ImageDraw.Draw(page)
    path = font_path('Oswald')
    big = ImageFont.truetype(str(path), 44) if path else ImageFont.load_default()
    mid = ImageFont.truetype(str(path), 30) if path else ImageFont.load_default()
    small = ImageFont.truetype(str(path), 24) if path else ImageFont.load_default()
    y = 50
    if first:
        d.text((60, y), title, font=big, fill=INK)
        y += 70
    slot = (PAGE[1] - y - 40) // CARDS_PER_PAGE
    for line, sizes, front, back in cards:
        d.text((60, y), line[:70], font=mid, fill=INK)
        d.text((60, y + 38), sizes[:95], font=small, fill=(120, 120, 130))
        box_h, box_w = slot - 130, (PAGE[0] - 180) // 2
        for n, img in enumerate((front, back)):
            if img is None:
                continue
            scale = min(box_w / img.width, box_h / img.height)
            pic = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
            page.paste(pic, (60 + n * (box_w + 60) + (box_w - pic.width) // 2, y + 80))
            d.text((60 + n * (box_w + 60) + box_w // 2, y + 80 + box_h + 4), 'FRONT' if n == 0 else 'BACK',
                   font=small, fill=(120, 120, 130), anchor='mt')
        y += slot
    return page


def mockup_pdf(order, items=None, title=None):
    """PDF bytes with a front and back mockup of every different shirt in the order, or None if there is nothing to show."""
    cards = build_cards(order, items)
    if not cards:
        return None
    title = title or f'Your shirt mockups - order {order.order_number}'
    pages = [_page_with_cards(cards[i:i + CARDS_PER_PAGE], title, i == 0) for i in range(0, len(cards), CARDS_PER_PAGE)]
    out = io.BytesIO()
    pages[0].save(out, 'PDF', resolution=150.0, save_all=True, append_images=pages[1:])
    return out.getvalue()
