"""Mockups of each shirt in an order (front and back), drawn on the server, for emailing or downloading.

One card per different shirt: the shirt photo with the logo where it will be printed, and the back with the
person's name and number. Shirts that look the same (only the size differs) share a card. The cards go on a
PDF so the customer can see exactly what they are paying for without anyone taking screenshots.
"""
from __future__ import annotations

import io

# How big the print is on the photo comes from the real print sizes. Every shirt photo shows the whole garment, so
# one inch of print is the garment's height in the photo divided by how long that garment really is.
GARMENT_LENGTH_IN = {'adult': 28.0, 'youth': 23.0, 'toddler': 19.0, 'baby': 16.0}
COLLAR_TO_PRINT_IN = 4.5           # the top of a back name sits about this far below the top of the collar
CHEST_DROP_IN = 7.5                # a chest logo's center sits about this far below the top of the collar
CHEST_SIDE_IN = 4.3                # and this far to the side of the shirt's middle
CENTER_TOP_IN = 4.0                # a center-chest print starts about this far below the top of the collar
CARDS_PER_PAGE = 8                 # a grid of two columns by four rows; each card has a front and a back
COLUMNS, ROWS = 2, 4
PAGE = (1275, 1650)                # US letter at 150 dpi
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
            bool(m.get('outline', True)), getattr(item, 'back_design_file_name', None) or '')


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


def _production(item):
    try:
        from utils.print_sizes import production_from_order_item
        return production_from_order_item(item)
    except Exception:
        return None


def _on_backdrop(shirt):
    from PIL import Image
    backdrop = tuple(shirt.convert('RGB').getpixel((2, 2)))
    base = Image.new('RGBA', shirt.size, backdrop + (255,))
    base.alpha_composite(shirt)
    return base, backdrop


def _shirt_box(base, backdrop):
    """(left, top, right, bottom) of the garment in the photo, ignoring the plain background around it."""
    from PIL import Image, ImageChops
    flat = base.convert('RGB')
    mask = ImageChops.difference(flat, Image.new('RGB', flat.size, backdrop)).convert('L').point(
        lambda p: 255 if p > 40 else 0)
    return mask.getbbox() or ((0, 0) + flat.size)


def _ppi(item, box):
    """Pixels in the photo per inch of real garment."""
    product = getattr(item, 'product', None)
    age = (getattr(product, 'age_group', None) or 'adult').strip().lower()
    return max(1.0, (box[3] - box[1]) / GARMENT_LENGTH_IN.get(age, 28.0))


def _paste_logo(base, art, width_px, max_h_px, cx, top=None, cy=None):
    """Draw the art no wider than width_px and no taller than max_h_px, centered across at cx, and either its
    top edge at `top` or its center at `cy`."""
    from PIL import Image
    aw = width_px
    ah = aw * art.height / max(art.width, 1)
    if ah > max_h_px:
        ah = max_h_px
        aw = ah * art.width / max(art.height, 1)
    art = art.resize((max(1, int(aw)), max(1, int(ah))), Image.LANCZOS)
    y = top if top is not None else cy - art.height / 2
    base.alpha_composite(art, (int(cx - art.width / 2), int(y)))


def _finish(base, backdrop):
    from utils.share_preview import _trim_margins
    return _trim_margins(base, backdrop).convert('RGB')


def render_front(item, shirt_url, design_url):
    """The front of this shirt, or None when the photo cannot be loaded."""
    shirt, art = _open(shirt_url), _open(design_url)
    if shirt is None:
        return None
    base, backdrop = _on_backdrop(shirt)
    if art is not None:
        box = _shirt_box(base, backdrop)
        ppi = _ppi(item, box)
        middle = (box[0] + box[2]) / 2.0
        front = (_production(item) or {}).get('front') or {}
        place = item.placement or 'center_chest'
        width_in = float(front.get('width') or (3.8 if place != 'center_chest' else 10.0))
        height_in = float(front.get('height') or width_in)
        if place in ('left_chest', 'right_chest'):
            side = 1 if place == 'left_chest' else -1            # the wearer's left is on the viewer's right
            _paste_logo(base, art, width_in * ppi, height_in * ppi * 1.05, middle + side * CHEST_SIDE_IN * ppi,
                        cy=box[1] + CHEST_DROP_IN * ppi)
        else:
            _paste_logo(base, art, width_in * ppi, height_in * ppi * 1.05, middle, top=box[1] + CENTER_TOP_IN * ppi)
    return _finish(base, backdrop)


def render_back(item, shirt_url, back_art_url=None):
    """The back with the name and number (or the back logo), or None when there is nothing to show."""
    from PIL import ImageDraw, ImageFont
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
    box = _shirt_box(base, backdrop)
    ppi = _ppi(item, box)
    middle = (box[0] + box[2]) / 2.0
    top = box[1] + COLLAR_TO_PRINT_IN * ppi
    if art is not None:
        _paste_logo(base, art, 12 * ppi, 14 * ppi, middle, top=top)
        return _finish(base, backdrop)

    path = font_path(name_font_name(meta.get('font') or 'Bebas Neue'))
    color = _hex(meta.get('text_color'))
    ring_color = _hex(meta.get('outline_color'), (0, 0, 0)) + (255,)
    draw = ImageDraw.Draw(base)
    back = (_production(item) or {}).get('back') or {}
    name_in, number_in = float(back.get('name_height') or 2.0), float(back.get('number_height') or 7.0)
    gap_in = max(0.0, float(back.get('combined_height') or 0) - name_in - number_in) or 3.0     # the space the print file leaves

    def text(value, cap_in, top_px, max_w_in=None):
        """Capital letters cap_in inches tall, their top edge at top_px, centered on the shirt."""
        cap_px = cap_in * ppi
        if not path:
            draw.text((middle, top_px), value, fill=color + (255,), anchor='mt')
            return
        probe = ImageFont.truetype(str(path), 200).getbbox('H')
        size = max(8, int(200 * cap_px / max(1, probe[3] - probe[1])))
        font = ImageFont.truetype(str(path), size)
        if max_w_in and font.getlength(value) > max_w_in * ppi:                    # a long name gets narrower, not taller
            size = max(8, int(size * max_w_in * ppi / font.getlength(value)))
            font = ImageFont.truetype(str(path), size)
        letter = font.getbbox('H')
        ring = max(1, int(round(size * 0.08))) if meta.get('outline', True) else 0      # the same outline the print has
        # anchor 'ms' puts the letters' bottom edge exactly on the baseline, so the top edge lands where it should
        draw.text((middle, top_px + (letter[3] - letter[1])), value, font=font, fill=color + (255,), anchor='ms',
                  stroke_width=ring, stroke_fill=ring_color)

    if name:
        text(name, name_in, top, max_w_in=14.0)
        if number:
            text(number, number_in, top + (name_in + gap_in) * ppi)
    elif number:
        text(number, number_in, top)
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
    big = ImageFont.truetype(str(path), 40) if path else ImageFont.load_default()
    mid = ImageFont.truetype(str(path), 24) if path else ImageFont.load_default()
    small = ImageFont.truetype(str(path), 19) if path else ImageFont.load_default()
    margin, gutter = 50, 40
    y0 = 40
    if first:
        d.text((margin, y0), title, font=big, fill=INK)
        y0 += 70
    col_w = (PAGE[0] - 2 * margin - gutter) // COLUMNS
    row_h = (PAGE[1] - y0 - 30) // ROWS
    box_w, box_h = (col_w - 30) // 2, row_h - 100
    for n, (line, sizes, front, back) in enumerate(cards):
        col, row = n % COLUMNS, n // COLUMNS
        x, y = margin + col * (col_w + gutter), y0 + row * row_h
        d.text((x, y), line[:48], font=mid, fill=INK)
        d.text((x, y + 30), sizes[:70], font=small, fill=(120, 120, 130))
        for m, img in enumerate((front, back)):
            if img is None:
                continue
            scale = min(box_w / img.width, box_h / img.height)
            pic = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
            px = x + m * (box_w + 30) + (box_w - pic.width) // 2
            page.paste(pic, (px, y + 62))
            d.text((x + m * (box_w + 30) + box_w // 2, y + 62 + box_h + 2), 'FRONT' if m == 0 else 'BACK',
                   font=small, fill=(120, 120, 130), anchor='mt')
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
