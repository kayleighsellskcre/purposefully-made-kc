"""Immutable name/number production layout — one engine for cart, order, admin, PNG.

Admin never recalculates an old order with newer chart defaults.
If a snapshot already has heights, gap, scales, and font, those values win.
"""
from __future__ import annotations

import json
import math
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

LAYOUT_VERSION = 2
PRODUCTION_DPI = 300
PREVIEW_DPI = 72
# Visible-gap match tolerance in inches when validating a reconstructed PNG.
VALIDATE_TOLERANCE_IN = 0.08
# Hard cap so a bad snapshot cannot allocate a Railway-killing canvas.
MAX_EDGE_PX = 4500
MAX_PIXELS = 8_000_000

FONT_FILES = {
    'Jersey M54': 'JerseyM54.ttf',
    'Bebas Neue': 'BebasNeue-Regular.ttf',
    'Oswald': 'Oswald-Bold.ttf',
    'Anton': 'Anton-Regular.ttf',
    'Teko': 'Teko-Bold.ttf',
    # Alumni Sans Collegiate One (OFL), served to customers as Varsity Regular.
    'Varsity Regular': 'VarsityRegular.ttf',
}

_FONT_CACHE = {}


def fonts_dir():
    return Path(__file__).resolve().parent.parent / 'static' / 'fonts'


def font_path(font_name):
    filename = FONT_FILES.get(font_name) or FONT_FILES['Bebas Neue']
    path = fonts_dir() / filename
    return path if path.is_file() else None


def font_available(font_name):
    return font_path(font_name) is not None


def _load_font(font_name, size_px):
    path = font_path(font_name)
    if not path:
        raise FileNotFoundError(f'Production font file missing for "{font_name}"')
    key = (str(path), int(size_px))
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    font = ImageFont.truetype(str(path), size=max(8, int(size_px)))
    _FONT_CACHE[key] = font
    return font


def _as_dict(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def snapshot_from_item(item, customer_name=None):
    """Return the saved production snapshot, or a flagged reconstruction.

    Saved transfer_production.back and back_design_meta win. Live chart
    defaults are only used when an old order has no stored heights.
    """
    stored = getattr(item, 'transfer_production_details', None)
    if callable(stored):
        try:
            stored = stored()
        except Exception:
            stored = None
    stored = stored if isinstance(stored, dict) else {}
    back = dict(stored.get('back') or {})
    meta = getattr(item, 'back_design_details', None)
    if callable(meta):
        try:
            meta = meta()
        except Exception:
            meta = None
    meta = meta if isinstance(meta, dict) else {}

    reconstructed = False
    if not (back.get('name_height') or meta.get('name_height')):
        from utils.print_sizes import production_from_order_item
        prod = production_from_order_item(item, customer_name=customer_name) or {}
        back = dict(prod.get('back') or {})
        reconstructed = True

    name = (back.get('name') or meta.get('name') or '').strip()
    number = str(back.get('number') or meta.get('number') or '').strip()
    font = (back.get('font') or meta.get('font') or 'Jersey M54').strip() or 'Jersey M54'
    complete = bool(
        (name or number)
        and (back.get('name_height') or meta.get('name_height'))
        and (not number or back.get('number_height') or meta.get('number_height'))
        and (not (name and number) or back.get('gap') is not None or meta.get('gap') is not None)
        and not reconstructed
    )
    version = int(back.get('layout_version') or meta.get('layout_version') or 0)
    return {
        'layout_version': version or (LAYOUT_VERSION if complete else 0),
        'complete': complete,
        'needs_review': (
            (not complete)
            or reconstructed
            or bool(back.get('needs_review') or meta.get('needs_review'))
        ),
        'name': name,
        'number': number,
        'font': font,
        'font_file': FONT_FILES.get(font),
        'font_weight': back.get('font_weight') or 'bold',
        'font_style': back.get('font_style') or 'normal',
        'text_color': back.get('text_color') or meta.get('text_color') or '#ffffff',
        'outline': bool(back.get('outline') if back.get('outline') is not None else meta.get('outline', True)),
        'outline_color': back.get('outline_color') or meta.get('outline_color') or '#000000',
        'category': back.get('category') or meta.get('category'),
        'age_group': back.get('age_group') or meta.get('age_group'),
        'size': back.get('size') or getattr(item, 'size', None),
        'color': back.get('color') or getattr(item, 'color', None),
        'garment_style': back.get('garment_style') or getattr(item, 'product_name', None),
        'name_height': _num(back.get('name_height') or meta.get('name_height')),
        'name_width': _num(back.get('name_width') or meta.get('name_width')),
        'name_width_natural': _num(back.get('name_width_natural') or meta.get('name_width_natural')),
        'number_height': _num(back.get('number_height') or meta.get('number_height')),
        'number_width': _num(back.get('number_width') or meta.get('number_width')),
        'number_width_natural': _num(back.get('number_width_natural') or meta.get('number_width_natural')),
        'number_digits': int(back.get('number_digits') or len(number) or 0),
        'condense': _num(back.get('condense') or meta.get('condense'), 1.0),
        'number_scale': _num(back.get('number_scale') or meta.get('number_scale'), 1.0),
        'name_letter_spacing_em': _num(back.get('name_letter_spacing_em') or meta.get('name_letter_spacing_em')),
        'number_tracking_em': _num(back.get('number_tracking_em') or meta.get('number_tracking_em')),
        'gap': _num(back.get('gap') or meta.get('gap')),
        'combined_width': _num(back.get('combined_width') or meta.get('combined_width')),
        'combined_height': _num(back.get('combined_height') or meta.get('combined_height')),
        'name_x': _num(back.get('name_x')),
        'name_y': _num(back.get('name_y')),
        'number_x': _num(back.get('number_x')),
        'number_y': _num(back.get('number_y')),
        'canvas_width_in': _num(back.get('canvas_width_in')),
        'canvas_height_in': _num(back.get('canvas_height_in')),
        'pad_in': _num(back.get('pad_in'), 0.04),
        'preview_url': meta.get('file_url') or meta.get('url'),
        'production_png_url': back.get('production_png_url') or meta.get('production_png_url'),
        'customer_name': back.get('customer_name') or customer_name,
        'quantity': back.get('quantity') or getattr(item, 'quantity', 1),
        'name_height_display': back.get('name_height_display'),
        'name_width_display': back.get('name_width_display'),
        'number_height_display': back.get('number_height_display'),
        'number_width_display': back.get('number_width_display'),
        'gap_display': back.get('gap_display'),
        'combined_width_display': back.get('combined_width_display'),
        'combined_height_display': back.get('combined_height_display'),
        'condense_percent': back.get('condense_percent'),
        'number_scale_percent': back.get('number_scale_percent'),
        'number_width_natural_display': back.get('number_width_natural_display'),
        'layout_label': back.get('layout_label'),
        'kind': 'personalized',
        'placement': 'center_back',
        'placement_label': 'Center Back',
        'order_by': 'HEIGHT',
    }


def enrich_back_snapshot(back, extra=None):
    """Stamp layout_version and font file onto a production back block."""
    data = dict(back or {})
    extra = extra or {}
    data['layout_version'] = LAYOUT_VERSION
    font = (data.get('font') or extra.get('font') or 'Jersey M54').strip()
    data['font'] = font
    data['font_file'] = FONT_FILES.get(font)
    data['font_weight'] = extra.get('font_weight') or data.get('font_weight') or 'bold'
    data['font_style'] = extra.get('font_style') or data.get('font_style') or 'normal'
    for key in (
        'name_letter_spacing_em', 'number_tracking_em', 'name_x', 'name_y',
        'number_x', 'number_y', 'canvas_width_in', 'canvas_height_in', 'pad_in',
    ):
        if extra.get(key) is not None:
            data[key] = extra[key]
    return data


def _num(value, default=None):
    if value is None or value == '':
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _hex_rgba(color, fallback=(255, 255, 255, 255)):
    text = (color or '').strip()
    if text.startswith('#') and len(text) == 7:
        return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    return fallback


def _ink_bounds(image):
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    bbox = image.getbbox()
    if not bbox:
        return None
    return bbox


def _draw_line_layer(text, font, fill, stroke_fill, stroke_width, spacing_em, font_px, scale_x):
    """Rasterize one line, then optionally squeeze width. Returns RGBA image."""
    dummy = Image.new('RGBA', (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    spacing_px = (spacing_em or 0) * font_px
    # Draw the whole word whenever tracking is not tightened. Splitting
    # characters drops Jersey kerning and turns SPRINGER into SPR NGER.
    if len(text) <= 1 or (spacing_em or 0) >= -0.001:
        bbox = draw.textbbox((0, 0), text, font=font)
        pad = max(int(stroke_width) * 2, 8)
        w = max(1, bbox[2] - bbox[0] + pad * 2)
        h = max(1, bbox[3] - bbox[1] + pad * 2)
        layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(
            (pad - bbox[0], pad - bbox[1]),
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill if stroke_width else None,
        )
    else:
        widths = []
        boxes = []
        max_h = 1
        for ch in text:
            bbox = draw.textbbox((0, 0), ch, font=font)
            boxes.append(bbox)
            widths.append(max(1, bbox[2] - bbox[0]))
            max_h = max(max_h, bbox[3] - bbox[1])
        pad = max(int(stroke_width) * 2, 8)
        total_w = int(sum(widths) + spacing_px * (len(text) - 1)) + pad * 2
        layer = Image.new('RGBA', (max(1, total_w), max(1, max_h + pad * 2)), (0, 0, 0, 0))
        painter = ImageDraw.Draw(layer)
        x = pad
        for ch, bbox, w in zip(text, boxes, widths):
            painter.text(
                (x - bbox[0], pad - bbox[1]),
                ch,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill if stroke_width else None,
            )
            x += w + spacing_px
    if scale_x and 0 < scale_x < 0.999:
        layer = layer.resize(
            (max(1, int(layer.width * scale_x)), layer.height),
            Image.Resampling.LANCZOS,
        )
    return layer


def snapshot_for_piece(snapshot, piece='back'):
    """Return a snapshot for one render mode. Never reuses the combined canvas."""
    snap = dict(snapshot or {})
    if piece == 'name':
        if not (snap.get('name') or '').strip():
            raise ValueError('Snapshot has no name')
        snap['number'] = ''
        snap['gap'] = 0
        snap['combined_width'] = snap.get('name_width')
        snap['combined_height'] = snap.get('name_height')
        return snap
    if piece == 'number':
        if not str(snap.get('number') or '').strip():
            raise ValueError('Snapshot has no number')
        snap['name'] = ''
        snap['gap'] = 0
        snap['combined_width'] = snap.get('number_width')
        snap['combined_height'] = snap.get('number_height')
        return snap
    if piece in ('back', 'combined', None):
        return snap
    raise ValueError(f'Unknown render piece: {piece}')


def render_piece_png(snapshot, piece='back', dpi=PRODUCTION_DPI):
    """Render one of: name-only, number-only, or combined-back-layout."""
    return render_snapshot_png(snapshot_for_piece(snapshot, piece), dpi=dpi)


def render_snapshot_png(snapshot, dpi=PRODUCTION_DPI):
    """Render a transparent production PNG from a saved snapshot. Never uses new chart defaults."""
    name = (snapshot.get('name') or '').strip().upper()
    number = str(snapshot.get('number') or '').strip()
    font_name = snapshot.get('font') or 'Jersey M54'
    if not name and not number:
        raise ValueError('Snapshot has no name or number')
    if not font_available(font_name):
        raise FileNotFoundError(f'The production font "{font_name}" is not installed on the server.')

    name_h = _num(snapshot.get('name_height'), 0) or 0
    number_h = _num(snapshot.get('number_height'), 0) or 0
    gap = _num(snapshot.get('gap'), 0) or 0
    if name and not name_h:
        raise ValueError('Snapshot is missing the saved name height')
    if number and not number_h:
        raise ValueError('Snapshot is missing the saved number height')
    if name and number and snapshot.get('gap') is None:
        raise ValueError('Snapshot is missing the saved name-to-number gap')

    pad_in = _num(snapshot.get('pad_in'), 0.04) or 0.04
    name_px = name_h * dpi
    number_px = number_h * dpi
    gap_px = gap * dpi
    pad_px = max(4, int(round(pad_in * dpi)))

    # Probe ink ratio so font-size produces the saved VISIBLE height, not the em box.
    name_font_px = _font_px_for_ink(font_name, name_px, 'H') if name else 0
    number_font_px = _font_px_for_ink(font_name, number_px, '8') if number else 0
    name_font = _load_font(font_name, name_font_px) if name else None
    number_font = _load_font(font_name, number_font_px) if number else None

    fill = _hex_rgba(snapshot.get('text_color'))
    stroke = _hex_rgba(snapshot.get('outline_color'), (0, 0, 0, 255))
    stroke_w_name = max(1, int(round(name_font_px * 0.08))) if snapshot.get('outline') else 0
    stroke_w_num = max(1, int(round(number_font_px * 0.08))) if snapshot.get('outline') else 0

    name_spacing = _num(snapshot.get('name_letter_spacing_em'))
    if name_spacing is None:
        name_spacing = 0.05 if font_name == 'Jersey M54' else 0.06
    number_spacing = _num(snapshot.get('number_tracking_em'))
    if number_spacing is None:
        number_spacing = -0.02 if len(number) == 2 else 0.02

    condense = _num(snapshot.get('condense'), 1.0) or 1.0
    number_scale = _num(snapshot.get('number_scale'), 1.0) or 1.0

    name_layer = _draw_line_layer(
        name, name_font, fill, stroke, stroke_w_name, name_spacing, name_font_px, condense,
    ) if name else None
    number_layer = _draw_line_layer(
        number, number_font, fill, stroke, stroke_w_num, number_spacing, number_font_px, number_scale,
    ) if number else None

    # Fit each layer to the saved visible height, then stack by the saved gap
    # measured ink-bottom to ink-top — never CSS line-height.
    if name_layer:
        name_layer = _fit_visible_height(name_layer, max(1, int(round(name_px))))
    if number_layer:
        number_layer = _fit_visible_height(number_layer, max(1, int(round(number_px))))

    name_box = _ink_bounds(name_layer) if name_layer else None
    number_box = _ink_bounds(number_layer) if number_layer else None
    name_w = (name_box[2] - name_box[0]) if name_box else 0
    number_w = (number_box[2] - number_box[0]) if number_box else 0
    ink_w = max(name_w, number_w, 1)
    if name and not number:
        target_w = _num(snapshot.get('name_width') or snapshot.get('combined_width'))
    elif number and not name:
        target_w = _num(snapshot.get('number_width') or snapshot.get('combined_width'))
    else:
        target_w = _num(snapshot.get('combined_width'))
    target_w_px = int(round(target_w * dpi)) if target_w else 0
    content_w = max(ink_w, target_w_px, 1)
    if name and number:
        content_h = int(round(name_px + gap_px + number_px))
    elif name:
        content_h = int(round(name_px))
    else:
        content_h = int(round(number_px))

    canvas_w = content_w
    canvas_h = content_h
    if canvas_w > MAX_EDGE_PX or canvas_h > MAX_EDGE_PX or (canvas_w * canvas_h) > MAX_PIXELS:
        raise ValueError(
            f'Production image too large to render safely ({canvas_w}×{canvas_h}px).'
        )

    canvas = None
    try:
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        center_x = canvas_w / 2
        y = 0
        if name_layer and name_box:
            x = int(round(center_x - name_w / 2 - name_box[0]))
            canvas.paste(name_layer, (x, y - name_box[1]), name_layer)
            y += int(round(name_px))
            if number:
                y += int(round(gap_px))
        if number_layer and number_box:
            x = int(round(center_x - number_w / 2 - number_box[0]))
            canvas.paste(number_layer, (x, y - number_box[1]), number_layer)
        return _png_bytes(canvas, dpi)
    finally:
        for image in (name_layer, number_layer, canvas):
            try:
                if image is not None:
                    image.close()
            except Exception:
                pass


def _font_px_for_ink(font_name, target_ink_px, probe):
    """Find a font size whose visible probe-glyph height matches target_ink_px."""
    if target_ink_px <= 0:
        return 12
    guess = max(12, int(round(target_ink_px / 0.72)))
    font = _load_font(font_name, guess)
    dummy = Image.new('RGBA', (8, 8), (0, 0, 0, 0))
    bbox = ImageDraw.Draw(dummy).textbbox((0, 0), probe, font=font)
    ink = max(1, bbox[3] - bbox[1])
    return max(8, guess * (target_ink_px / ink))


def _fit_visible_height(layer, target_h):
    box = _ink_bounds(layer)
    if not box:
        return layer
    visible_h = box[3] - box[1]
    if visible_h <= 0 or abs(visible_h - target_h) <= 1:
        return layer
    scale = target_h / visible_h
    new_size = (max(1, int(round(layer.width * scale))), max(1, int(round(layer.height * scale))))
    return layer.resize(new_size, Image.Resampling.LANCZOS)


def _trim_exterior(image):
    box = image.getbbox()
    if not box:
        return image
    return image.crop(box)


def _png_bytes(image, dpi):
    buf = BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text('Software', 'Purposefully Made KC personalization layout')
    image.save(buf, format='PNG', dpi=(dpi, dpi), pnginfo=meta)
    return buf.getvalue()


def measure_rendered(image_bytes):
    """Visible bounds of a rendered PNG, in pixels."""
    with Image.open(BytesIO(image_bytes)) as img:
        img = img.convert('RGBA')
        box = img.getbbox()
        if not box:
            return {
                'width_px': img.width,
                'height_px': img.height,
                'has_transparency': True,
                'empty': True,
            }
        return {
            'width_px': box[2] - box[0],
            'height_px': box[3] - box[1],
            'canvas_width_px': img.width,
            'canvas_height_px': img.height,
            'has_transparency': any(px[3] < 255 for px in img.getdata()),
            'empty': False,
        }


def validate_snapshot_geometry(snapshot):
    """Check saved heights/gap without rendering a PNG."""
    failures = []
    font_name = snapshot.get('font') or 'Jersey M54'
    if not font_available(font_name):
        failures.append({
            'code': 'font_missing',
            'label': 'Font file',
            'expected': font_name,
            'actual': 'not installed',
        })
    if not snapshot.get('complete'):
        failures.append({
            'code': 'incomplete',
            'label': 'Saved layout',
            'expected': 'name/number heights and gap',
            'actual': 'missing geometry',
        })
    name_h = _num(snapshot.get('name_height')) or 0
    number_h = _num(snapshot.get('number_height')) or 0
    gap = _num(snapshot.get('gap')) or 0
    expected_h = _num(snapshot.get('combined_height'))
    if snapshot.get('name') and snapshot.get('number') and expected_h:
        if expected_h + 0.01 < (name_h + number_h):
            failures.append({
                'code': 'overlap',
                'label': 'Name/number overlap',
                'expected': f'gap {gap:.2f}" (name+number+gap)',
                'actual': f'saved combined height {expected_h:.2f}" is smaller than name+number',
            })
    return (not failures), failures


def validate_snapshot_png(snapshot, image_bytes, dpi=PRODUCTION_DPI):
    """Compare a rendered PNG to the saved snapshot. Returns (ok, failures)."""
    failures = []
    font_name = snapshot.get('font') or 'Jersey M54'
    if not font_available(font_name):
        failures.append({
            'code': 'font_missing',
            'label': 'Font file',
            'expected': font_name,
            'actual': 'not installed',
        })
        return False, failures

    metrics = measure_rendered(image_bytes)
    if metrics.get('empty'):
        failures.append({
            'code': 'empty',
            'label': 'Artwork',
            'expected': 'visible name/number',
            'actual': 'empty image',
        })
    if not metrics.get('has_transparency', True):
        failures.append({
            'code': 'no_transparency',
            'label': 'Transparency',
            'expected': 'transparent PNG',
            'actual': 'opaque',
        })

    expected_w = _num(snapshot.get('combined_width'))
    expected_h = _num(snapshot.get('combined_height'))
    if expected_w:
        actual_w = metrics.get('width_px', 0) / dpi
        if abs(actual_w - expected_w) > max(VALIDATE_TOLERANCE_IN, expected_w * 0.08):
            failures.append({
                'code': 'combined_width',
                'label': 'Combined width',
                'expected': f'{expected_w:.2f}"',
                'actual': f'{actual_w:.2f}"',
            })
    if expected_h:
        actual_h = metrics.get('height_px', 0) / dpi
        if abs(actual_h - expected_h) > max(VALIDATE_TOLERANCE_IN, expected_h * 0.08):
            failures.append({
                'code': 'combined_height',
                'label': 'Combined height',
                'expected': f'{expected_h:.2f}"',
                'actual': f'{actual_h:.2f}"',
            })

    min_px = int(dpi * 0.5)
    if metrics.get('width_px', 0) < min_px or metrics.get('height_px', 0) < min_px:
        failures.append({
            'code': 'resolution',
            'label': 'Resolution',
            'expected': f'at least {min_px}px at {dpi} DPI',
            'actual': f"{metrics.get('width_px')}×{metrics.get('height_px')}",
        })

    # Overlap / clipping: if both name and number exist, combined height must
    # be at least name + number (gap can be 0 but not negative).
    name_h = _num(snapshot.get('name_height')) or 0
    number_h = _num(snapshot.get('number_height')) or 0
    gap = _num(snapshot.get('gap')) or 0
    if snapshot.get('name') and snapshot.get('number') and expected_h:
        if expected_h + 0.01 < (name_h + number_h):
            failures.append({
                'code': 'overlap',
                'label': 'Name/number overlap',
                'expected': f'gap {gap:.2f}" (name+number+gap)',
                'actual': f'saved combined height {expected_h:.2f}" is smaller than name+number',
            })

    return (not failures), failures


def inches_from_px(px, dpi=PRODUCTION_DPI):
    return round(px / dpi, 2)


def repair_existing_personalized_items(app=None):
    """Stamp saved layout metadata only. Never renders or uploads PNGs.

    Full-resolution transfers are built when an admin clicks Save on one item.
    """
    from flask import current_app
    from models import OrderItem, db

    app = app or current_app._get_current_object()
    scanned = repaired = flagged = skipped = 0
    items = OrderItem.query.all()
    for item in items:
        meta = item.back_design_details or {}
        if not (meta.get('name') or meta.get('number')):
            continue
        scanned += 1
        if meta.get('layout_repaired') and meta.get('layout_version'):
            skipped += 1
            continue
        snap = snapshot_from_item(item)
        meta = dict(meta)
        meta['layout_repaired'] = True
        meta['layout_version'] = snap.get('layout_version') or LAYOUT_VERSION
        meta['needs_review'] = not snap.get('complete')
        item.back_design_meta = json.dumps(meta)
        if snap.get('complete'):
            stored = dict(item.transfer_production_details or {})
            back = dict(stored.get('back') or {})
            back = enrich_back_snapshot(back or {
                'name': snap.get('name'),
                'number': snap.get('number'),
                'font': snap.get('font'),
                'name_height': snap.get('name_height'),
                'number_height': snap.get('number_height'),
                'gap': snap.get('gap'),
            }, extra=meta)
            stored['back'] = back
            item.transfer_production = json.dumps(stored)
            repaired += 1
        else:
            flagged += 1
    if scanned:
        db.session.commit()
    app.logger.info(
        'personalization metadata stamp scanned=%s stamped=%s flagged=%s skipped=%s',
        scanned, repaired, flagged, skipped,
    )
    return {'scanned': scanned, 'repaired': repaired, 'flagged': flagged, 'skipped': skipped}
