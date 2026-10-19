"""Spot duplicates, color versions and wording versions of a design, without ever merging anything.

Every design gets a small fingerprint:
* file hash   - the exact bytes of the upload (catches the same file twice)
* look hash   - how the artwork looks overall, colors included
* shape hash  - the layout only, with colors ignored (same design in another color matches here)
* palette     - the real ink colors, with transparent background left out, plus a color family
* wording     - the words on the artwork (when known)

Two designs are then compared and, if they are close, a *suggestion* is saved for you to confirm or dismiss.
Nothing is deleted, merged or hidden by the comparison itself.
"""
import colorsys
import hashlib
import io
import json
import re
from datetime import datetime

from models import Design, DesignRelation, db

# how close two hashes must be (number of differing bits)
LOOK_SAME = 4               # of 64: the same picture
SHAPE_SAME = 12             # of 256: the same layout
SHAPE_SIMILAR = 34          # of 256: a similar layout (wording changed)

RELATION_LABELS = {
    'exact_duplicate': 'Same artwork',
    'color_variation': 'Same design, different colors',
    'wording_variation': 'Same layout, different wording',
    'matching_set': 'Matching set',
}


# -- Fingerprints ----------------------------------------------------------------------

def file_hash(data):
    return hashlib.sha256(data).hexdigest()


def _dhash(img, cols, rows):
    """Difference hash: 1 where a pixel is brighter than the one to its right."""
    from PIL import Image
    small = img.convert('L').resize((cols + 1, rows), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for y in range(rows):
        for x in range(cols):
            bits = (bits << 1) | (1 if px[y * (cols + 1) + x] > px[y * (cols + 1) + x + 1] else 0)
    return bits


def _family(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    deg = h * 360
    if v < 0.2:
        return 'black'
    if s < 0.12:
        return 'white' if v > 0.88 else 'gray'
    if s < 0.3 and v > 0.78 and 25 <= deg <= 65:
        return 'cream'
    if deg < 15 or deg >= 345:
        return 'red'
    if deg < 40:
        return 'brown' if v < 0.6 else 'orange'
    if deg < 68:
        return 'gold' if s > 0.35 else 'cream'
    if deg < 165:
        return 'green'
    if deg < 200:
        return 'teal'
    if deg < 258:
        return 'blue'
    if deg < 292:
        return 'purple'
    return 'pink'


def analyze_image(data):
    """Fingerprint one image. Returns a dict, or None when the file is not a readable image."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    img = img.convert('RGBA')
    img.thumbnail((256, 256), Image.Resampling.LANCZOS)
    w, h = img.size
    px = list(img.getdata())
    total = max(len(px), 1)
    transparent = sum(1 for p in px if p[3] < 40)
    has_alpha = transparent / total > 0.02

    # which pixels are artwork: opaque ones when there is transparency, else those unlike the corner background
    if has_alpha:
        is_ink = [p[3] >= 40 for p in px]
    else:
        corners = [px[0], px[w - 1], px[-w], px[-1]]
        bg = tuple(sorted(c[i] for c in corners)[1] for i in range(3))
        is_ink = [sum(abs(p[i] - bg[i]) for i in range(3)) > 60 for p in px]

    mask = Image.new('L', (w, h))
    mask.putdata([255 if ink else 0 for ink in is_ink])
    shape = _dhash(mask, 16, 16)

    flat = Image.new('RGBA', (w, h), (128, 128, 128, 255))
    flat.alpha_composite(img)
    look = _dhash(flat, 8, 8)

    counts = {}
    for p, ink in zip(px, is_ink):
        if not ink:
            continue
        key = (p[0] >> 4, p[1] >> 4, p[2] >> 4)
        counts[key] = counts.get(key, 0) + 1
    ink_total = max(sum(counts.values()), 1)
    palette = []
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1])[:12]:
        r, g, b = (key[0] << 4) + 8, (key[1] << 4) + 8, (key[2] << 4) + 8
        fam = _family(r, g, b)
        share = n / ink_total
        for entry in palette:                               # fold similar shades into one family entry
            if entry['family'] == fam:
                entry['share'] += share
                break
        else:
            palette.append({'family': fam, 'hex': '#%02x%02x%02x' % (r, g, b), 'share': share})
    palette = [e for e in sorted(palette, key=lambda e: -e['share']) if e['share'] >= 0.04][:4]
    for e in palette:
        e['share'] = round(e['share'], 3)
    return {'look': f'{look:016x}', 'shape': f'{shape:064x}', 'palette': palette,
            'families': [e['family'] for e in palette], 'transparent': has_alpha}


def hamming(a_hex, b_hex):
    if not a_hex or not b_hex:
        return 999
    return bin(int(a_hex, 16) ^ int(b_hex, 16)).count('1')


def store_fingerprint(design, data):
    """Compute and save a design's fingerprint. Returns True when it worked."""
    info = analyze_image(data)
    if info is None:
        return False
    design.file_hash = design.file_hash or file_hash(data)
    design.phash = info['look']
    design.shape_hash = info['shape']
    design.palette = json.dumps(info['palette'])
    design.color_families = ','.join(info['families'])
    design.fingerprinted_at = datetime.utcnow()
    return True


# -- Comparing -------------------------------------------------------------------------

def _tokens(text):
    return set(re.sub(r'[^a-z0-9 ]+', ' ', (text or '').lower()).split())


def _families(design):
    return [f for f in (design.color_families or '').split(',') if f]


def classify_pair(a, b):
    """('type', score 0..1, reason) when two designs are clearly related, else None."""
    if a.id == b.id:
        return None
    dl, ds = hamming(a.phash, b.phash), hamming(a.shape_hash, b.shape_hash)
    fa, fb = _families(a), _families(b)
    same_colors = bool(fa) and set(fa[:2]) == set(fb[:2])
    ta, tb = _tokens(a.art_text or ''), _tokens(b.art_text or '')
    have_text = bool(ta) and bool(tb)

    if (a.file_hash and a.file_hash == b.file_hash) or (dl <= LOOK_SAME and ds <= SHAPE_SAME and same_colors):
        exact = a.file_hash and a.file_hash == b.file_hash
        return 'exact_duplicate', 1.0 if exact else round(1 - (dl + ds / 4) / 40, 2), \
            'identical file' if exact else 'looks identical'
    if ds > SHAPE_SIMILAR:
        return None
    if have_text and ta != tb:
        diff = ta ^ tb
        if len(diff) <= 4 and ta & tb or (ds <= SHAPE_SAME and len(diff) <= 4):
            score = round(max(0.5, 1 - ds / 60), 2)
            return 'wording_variation', score, 'same layout, different words (' + ', '.join(sorted(diff)[:4]) + ')'
        return None
    if ds <= SHAPE_SAME and fa and fb and not same_colors:
        score = round(max(0.55, 1 - ds / 30), 2)
        return ('color_variation', score if have_text else min(score, 0.7),
                'same layout, different colors (' + '/'.join(fa[:2]) + ' vs ' + '/'.join(fb[:2]) + ')')
    if ds <= SHAPE_SAME and not have_text and same_colors:
        return 'wording_variation', 0.5, 'very similar layout, maybe different wording'
    return None


def _ordered(a_id, b_id):
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def suggest_for(design):
    """Compare one fingerprinted design with the rest of the library and save new suggestions. Returns count."""
    if not design.phash:
        return 0
    known = {(r.design_id, r.related_design_id) for r in DesignRelation.query.filter(
        db.or_(DesignRelation.design_id == design.id, DesignRelation.related_design_id == design.id))}
    # already grouped as colors of one design: nothing to suggest
    family = {design.id, design.parent_design_id} - {None}
    added = 0
    others = Design.query.filter(Design.phash.isnot(None), Design.id != design.id,
                                 Design.hidden_from_admin.isnot(True)).all()
    for other in others:
        if _ordered(design.id, other.id) in known:
            continue
        if other.id in family or (other.parent_design_id and other.parent_design_id == design.id):
            continue
        if other.parent_design_id and other.parent_design_id == design.parent_design_id:
            continue
        found = classify_pair(design, other)
        if not found:
            continue
        kind, score, reason = found
        a, b = _ordered(design.id, other.id)
        db.session.add(DesignRelation(design_id=a, related_design_id=b, relation_type=kind, status='suggested',
                                      score=score, reason=reason[:300], source='auto'))
        added += 1
    return added


def pending_query():
    return Design.query.filter(Design.fingerprinted_at.is_(None), Design.file_path.isnot(None),
                               db.or_(Design.is_gallery == True, Design.parent_design_id.isnot(None)))  # noqa: E712


def scan_batch(limit=3):
    """Fingerprint up to ``limit`` designs and look for matches. Returns (done, new_suggestions). Never raises."""
    from utils.design_organizer import load_design_bytes
    done = suggestions = 0
    for design in pending_query().order_by(Design.id).limit(limit).all():
        try:
            data = load_design_bytes(design)
            if data and store_fingerprint(design, data):
                db.session.flush()
                suggestions += suggest_for(design)
            else:
                design.fingerprinted_at = datetime.utcnow()      # unreadable or missing: do not retry forever
            db.session.commit()
            done += 1
        except Exception:
            db.session.rollback()
    return done, suggestions


def counts():
    by_status = dict(db.session.query(DesignRelation.status, db.func.count(DesignRelation.id))
                     .group_by(DesignRelation.status).all())
    return {'pending_scan': pending_query().count(),
            'fingerprinted': Design.query.filter(Design.fingerprinted_at.isnot(None)).count(),
            'suggested': by_status.get('suggested', 0), 'confirmed': by_status.get('confirmed', 0)}


# -- Related designs (for the customer page) ---------------------------------------------

def related_designs(design, limit=8):
    """True variations and matching sets first, then designs that share tags and style. Returns Design rows."""
    from models import DesignTagLink
    ids = []
    rows = DesignRelation.query.filter(
        DesignRelation.status == 'confirmed',
        db.or_(DesignRelation.design_id == design.id, DesignRelation.related_design_id == design.id),
        DesignRelation.relation_type != 'exact_duplicate').all()
    priority = {'color_variation': 0, 'matching_set': 1, 'wording_variation': 2}
    rows.sort(key=lambda r: (priority.get(r.relation_type, 9), -(r.score or 0)))
    for r in rows:
        other = r.related_design_id if r.design_id == design.id else r.design_id
        if other not in ids:
            ids.append(other)
    mine = {l.tag_id for l in DesignTagLink.query.filter_by(design_id=design.id)}
    if mine and len(ids) < limit:
        scores = {}
        for l in DesignTagLink.query.filter(DesignTagLink.tag_id.in_(mine), DesignTagLink.design_id != design.id):
            scores[l.design_id] = scores.get(l.design_id, 0) + 1
        for other, shared in sorted(scores.items(), key=lambda kv: -kv[1]):
            if other not in ids and shared >= 2:
                ids.append(other)
    live = {d.id: d for d in Design.query.filter(Design.id.in_(ids[:limit * 2]), Design.is_gallery == True).all()}  # noqa: E712
    return [live[i] for i in ids if i in live and live[i].parent_design_id != design.id][:limit]
