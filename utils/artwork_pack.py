"""Add a pack of finished artwork (a folder with design-manifest.json and the PNGs) to one group's artwork list.

Each picture is stored exactly as it arrives. A design already in the group is matched by its design ID (kept in the
SKU) or by its name, and is only tidied up (ID and heading), never replaced or duplicated.
"""
from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO

from models import Design, db
from utils import group_designs as GD
from utils.design_metadata import title_from_filename

# The pack's folders and the headings they get on the store page.
HEADINGS = {'general-spirit': 'General Spirit', 'family-fanwear': 'Family', 'red-friday': 'Red Friday'}


def _key(text):
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


def _group_designs(store):
    ids = GD._ids(store.allowed_design_ids)
    return Design.query.filter(Design.id.in_(ids)).all() if ids else []


def find_existing(store, design_id, name):
    """The design already in this group for that pack entry: by design ID first, then by name."""
    mine = _group_designs(store)
    for d in mine:
        if (d.sku or '').strip().upper() == design_id.upper():
            return d
    wanted = _key(name)
    for d in mine:
        if wanted and _key(d.title) == wanted:
            return d
    return None


def check_picture(data, expected_sha256=None):
    """None when the bytes are a real PNG (and match the pack's fingerprint), else a short reason."""
    from PIL import Image
    if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256:
        return 'the file does not match the pack list (it may be damaged)'
    try:
        img = Image.open(BytesIO(data))
        img.verify()
        if img.format != 'PNG':
            return 'it is not a PNG picture'
    except Exception:
        return 'it could not be read as a picture'
    return None


def add_entry(store, entry, file_storage, user, dry_run=False):
    """Add or match one pack entry. Returns {'status': 'added'|'matched'|'problem', 'name', 'reason'?}."""
    design_id = (entry.get('design_id') or '').strip()
    name = title_from_filename(entry.get('name') or '') or design_id
    heading = HEADINGS.get(entry.get('category'))
    if not design_id or not heading:
        return {'status': 'problem', 'name': name, 'reason': 'the pack list entry is incomplete'}
    existing = find_existing(store, design_id, name)
    if existing is not None:
        if not dry_run:
            if not (existing.sku or '').strip():
                existing.sku = design_id
            sections = GD.sections_map(store)
            if existing.id not in sections:
                sections[existing.id] = heading
                store.design_sections = json.dumps({str(k): v for k, v in sections.items()})
        return {'status': 'matched', 'name': existing.title or name}
    data = file_storage.read() if file_storage is not None else b''
    file_storage.seek(0) if file_storage is not None else None
    problem = check_picture(data, entry.get('sha256')) if data else 'the picture file is missing'
    if problem:
        return {'status': 'problem', 'name': name, 'reason': problem}
    if dry_run:
        return {'status': 'added', 'name': name}
    from routes.admin import _save_collection_design
    design = _save_collection_design(file_storage, user.id)
    if design is None:
        return {'status': 'problem', 'name': name, 'reason': 'the picture could not be saved'}
    design.title = name[:200]
    design.sku = design_id
    GD.attach(store, [design.id])
    sections = GD.sections_map(store)
    sections[design.id] = heading
    store.design_sections = json.dumps({str(k): v for k, v in sections.items()})
    store.restrict_options = True
    return {'status': 'added', 'name': name}
