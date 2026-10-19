"""Organize the designs you already have, safely.

Nothing here touches a design until you approve it. The steps:

1. Analyze: a batch of designs is read (artwork or just the name) and a *proposal* is saved.
2. Preview: you see every proposal next to what the design has today.
3. Apply: only the ones you pick (or the confident ones) are written. Applying only ADDS
   to the new library (collections, tags, style, keywords). It never renames a design you named,
   never changes your folders, and never touches artwork or URLs.
4. Undo: every applied proposal remembers exactly what it created, so it can be reversed.

Until the new gallery goes live, applying changes nothing customers can see.
"""
import json
import os
import re
import uuid
from datetime import datetime, timedelta

from models import Design, DesignCategoryLink, DesignProposal, DesignTagLink, db
from utils.design_ai import (
    AUTO_THRESHOLD, classify_from_text, interpret, link_manual_folders, request_classification,
)
from utils.design_metadata import is_generic_title
from utils.design_tags import apply_auto_tags, is_locked, vocabulary

ACTIVE = ('queued', 'processing', 'ready')
STALE_AFTER = timedelta(minutes=10)
COST_PER_DESIGN = 0.0005          # rough US dollars for one low-detail image read with gpt-4o-mini


def _now():
    return datetime.utcnow()


def eligible_query():
    """Published main designs not yet organized and not already in the pipeline."""
    busy = db.session.query(DesignProposal.design_id).filter(
        DesignProposal.status.in_(ACTIVE + ('applied', 'skipped', 'undone')))   # skipped or undone: never suggested again
    return (Design.query.filter(Design.is_gallery == True,  # noqa: E712
                                Design.parent_design_id.is_(None),
                                Design.ai_status.is_(None),
                                ~Design.id.in_(busy))
            .order_by(Design.uploaded_at.desc(), Design.id.desc()))


def plan_batch(limit, mode='smart'):
    """Queue the next ``limit`` designs for analysis. Returns (batch_id, queued_count)."""
    mode = mode if mode in ('smart', 'name') else 'smart'
    designs = eligible_query().limit(max(1, min(int(limit or 25), 200))).all()
    if not designs:
        return None, 0
    batch = uuid.uuid4().hex[:12]
    for design in designs:
        db.session.add(DesignProposal(design_id=design.id, batch_id=batch, mode=mode, status='queued'))
    db.session.commit()
    return batch, len(designs)


def estimate(count, mode='smart'):
    """(designs, dollars) for the message shown before anything runs."""
    return count, round(count * COST_PER_DESIGN, 2) if mode == 'smart' else 0.0


# -- Reading the artwork -------------------------------------------------------------

def load_design_bytes(design, timeout=20):
    """The artwork file as bytes (from cloud storage or this server), or None."""
    path = (design.file_path or '').strip()
    if not path:
        return None
    try:
        if path.startswith(('http://', 'https://')):
            import requests
            response = requests.get(path, timeout=timeout)
            response.raise_for_status()
            return response.content[:15_000_000]
        from flask import current_app
        clean = path.lstrip('/')
        candidates = [os.path.join(current_app.static_folder, clean[len('static/'):] if clean.startswith('static/') else clean),
                      os.path.join(current_app.root_path, clean)]
        for candidate in candidates:
            if os.path.isfile(candidate):
                with open(candidate, 'rb') as handle:
                    return handle.read(15_000_000)
    except Exception:
        return None
    return None


# -- Working through the queue ---------------------------------------------------------

def _claim(limit):
    """Take up to ``limit`` queued proposals (and any that got stuck), safely when several workers run."""
    cutoff = _now() - STALE_AFTER
    stuck = DesignProposal.query.filter(DesignProposal.status == 'processing',
                                        DesignProposal.processed_at < cutoff).all()
    for row in stuck:
        row.status = 'queued'
    db.session.commit()
    claimed = []
    for row in DesignProposal.query.filter_by(status='queued').order_by(DesignProposal.id).limit(limit).all():
        won = (DesignProposal.query.filter_by(id=row.id, status='queued')
               .update({'status': 'processing', 'processed_at': _now()}, synchronize_session=False))
        db.session.commit()
        if won:
            claimed.append(row.id)
    return claimed


def _analyze(design, mode, api_key):
    title = design.title or ''
    filename = design.original_filename or design.filename or ''
    if mode == 'smart' and (api_key or '').strip():
        data = load_design_bytes(design)
        raw = request_classification(data, api_key) if data else {}
        if raw:
            return interpret(raw, filename=filename, title_hint=title)
    return classify_from_text(title, filename)


def process_queue(max_items=5, api_key=None):
    """Analyze up to ``max_items`` queued designs. Returns how many were processed. Never raises."""
    if api_key is None:
        from flask import current_app
        api_key = current_app.config.get('OPENAI_API_KEY') or ''
    done = 0
    for pid in _claim(max_items):
        row = db.session.get(DesignProposal, pid)
        try:
            design = db.session.get(Design, row.design_id)
            if design is None:
                row.status, row.error = 'skipped', 'design was removed'
            else:
                result = _analyze(design, row.mode, api_key)
                row.result_json = json.dumps(result)
                row.confidence = result.get('confidence') or 0.0
                row.needs_attention = bool(
                    row.confidence < AUTO_THRESHOLD or result.get('protected') or not result.get('collections'))
                row.status = 'ready'
            row.processed_at = _now()
        except Exception as exc:
            db.session.rollback()
            row = db.session.get(DesignProposal, pid)
            row.status, row.error, row.processed_at = 'error', str(exc)[:500], _now()
        db.session.commit()
        done += 1
    return done


def summary():
    counts = dict(db.session.query(DesignProposal.status, db.func.count(DesignProposal.id))
                  .group_by(DesignProposal.status).all())
    total = Design.query.filter(Design.is_gallery == True, Design.parent_design_id.is_(None)).count()  # noqa: E712
    return {'total': total, 'waiting': eligible_query().count(),
            'queued': counts.get('queued', 0) + counts.get('processing', 0), 'ready': counts.get('ready', 0),
            'applied': counts.get('applied', 0), 'skipped': counts.get('skipped', 0),
            'errors': counts.get('error', 0)}


# -- Applying and undoing --------------------------------------------------------------

def _undo_record(design):
    return {'title': design.title, 'style': design.style, 'audience': design.audience, 'keywords': design.keywords,
            'ai_status': design.ai_status, 'ai_confidence': design.ai_confidence, 'ip_status': design.ip_status,
            'ai_suggestions': design.ai_suggestions, 'ai_processed_at': (design.ai_processed_at.isoformat()
                                                                           if design.ai_processed_at else None),
            'category_link_ids': [], 'tag_link_ids': []}


def apply_proposal(proposal, user_id=None):
    """Write one proposal onto its design. Only adds; remembers what it did so it can be undone."""
    if proposal.status != 'ready':
        return False
    design = db.session.get(Design, proposal.design_id)
    if design is None:
        proposal.status = 'skipped'
        return False
    result = json.loads(proposal.result_json or '{}')
    undo = _undo_record(design)

    # what you already chose stays: your folders become real links (marked 'legacy'), untouched otherwise
    before_ids = {l.id for l in DesignCategoryLink.query.filter_by(design_id=design.id)}
    folders = [design.folder] + [k for k in (design.extra_categories or '').split(',') if k.strip()]
    link_manual_folders(design, [f for f in folders if f])
    for link in DesignCategoryLink.query.filter_by(design_id=design.id):
        if link.id not in before_ids:
            link.source = 'legacy'
    db.session.flush()

    have = {(l.category_key, l.subcategory_key) for l in DesignCategoryLink.query.filter_by(design_id=design.id)}
    has_primary = any(l.is_primary for l in DesignCategoryLink.query.filter_by(design_id=design.id))
    for place in result.get('collections') or []:
        if place['confidence'] < AUTO_THRESHOLD or (place['key'], place['sub']) in have:
            continue
        link = DesignCategoryLink(design_id=design.id, category_key=place['key'], subcategory_key=place['sub'],
                                  is_primary=not has_primary, source='auto', confidence=place['confidence'])
        db.session.add(link)
        has_primary = True
        have.add((place['key'], place['sub']))
    tag_before = {l.id for l in DesignTagLink.query.filter_by(design_id=design.id)}
    apply_auto_tags(design, result.get('tags') or [], confidence=result.get('confidence') or None)
    db.session.flush()

    # fill gaps only: a name you wrote, or anything you locked, is never replaced
    if result.get('title') and is_generic_title(design.title) and not is_locked(design, 'title'):
        design.title = result['title'][:200]
    for field in ('style', 'audience'):
        if result.get(field) and not getattr(design, field) and not is_locked(design, field):
            setattr(design, field, result[field])
    if result.get('keywords') and not is_locked(design, 'keywords'):
        merged = [w for w in (design.keywords or '').split(',') if w.strip()]
        merged += [w for w in result['keywords'] if w not in merged]
        design.keywords = ','.join(merged)[:1000]

    undo['category_link_ids'] = [l.id for l in DesignCategoryLink.query.filter_by(design_id=design.id)
                                 if l.id not in before_ids]
    undo['tag_link_ids'] = [l.id for l in DesignTagLink.query.filter_by(design_id=design.id) if l.id not in tag_before]

    if result.get('visible_text') and not design.art_text:
        design.art_text = result['visible_text'][:400]
    design.ai_confidence = result.get('confidence')
    design.ai_status = 'done'
    design.ai_processed_at = _now()
    design.modified_at = _now()
    design.ai_suggestions = json.dumps({'unsure': [p for p in result.get('collections') or []
                                                   if p['confidence'] < AUTO_THRESHOLD],
                                        'protected_words': result.get('protected_words') or [],
                                        'dropped_tags': result.get('dropped_tags') or [], 'source': result.get('source')})
    if result.get('protected') and design.ip_status != 'cleared':
        design.ip_status = 'noted'                  # already live: noted for a look, never hidden

    proposal.undo_json = json.dumps(undo)
    proposal.status, proposal.applied_at = 'applied', _now()
    return True


def undo_proposal(proposal):
    """Reverse an applied proposal exactly: delete what it created, restore what it filled in."""
    if proposal.status != 'applied' or not proposal.undo_json:
        return False
    undo = json.loads(proposal.undo_json)
    design = db.session.get(Design, proposal.design_id)
    if design is not None:
        if undo.get('category_link_ids'):
            DesignCategoryLink.query.filter(DesignCategoryLink.id.in_(undo['category_link_ids'])).delete(
                synchronize_session=False)
        if undo.get('tag_link_ids'):
            DesignTagLink.query.filter(DesignTagLink.id.in_(undo['tag_link_ids'])).delete(synchronize_session=False)
        for field in ('title', 'style', 'audience', 'keywords', 'ai_status', 'ai_confidence', 'ip_status', 'ai_suggestions'):
            setattr(design, field, undo.get(field))
        design.ai_processed_at = (datetime.fromisoformat(undo['ai_processed_at'])
                                  if undo.get('ai_processed_at') else None)
        design.modified_at = _now()
    proposal.status, proposal.applied_at = 'undone', None
    return True


# -- A backup you can download before changing anything --------------------------------

def snapshot():
    """Everything the organizer can touch, as plain data. Artwork files are not included (they are never changed)."""
    rows = []
    links = {}
    for link in DesignCategoryLink.query.all():
        links.setdefault(link.design_id, []).append(
            [link.category_key, link.subcategory_key, bool(link.is_primary), link.source])
    tags = {}
    for link in DesignTagLink.query.all():
        tags.setdefault(link.design_id, []).append([link.tag.slug if link.tag else link.tag_id, link.source])
    for d in Design.query.filter(Design.is_gallery == True).order_by(Design.id):  # noqa: E712
        rows.append({'id': d.id, 'sku': d.sku, 'title': d.title, 'folder': d.folder,
                     'extra_categories': d.extra_categories, 'parent_design_id': d.parent_design_id,
                     'variant_label': d.variant_label, 'file_path': d.file_path, 'style': d.style,
                     'audience': d.audience, 'keywords': d.keywords, 'ai_status': d.ai_status,
                     'ip_status': d.ip_status, 'locked_fields': d.locked_fields,
                     'categories': links.get(d.id, []), 'tags': tags.get(d.id, [])})
    return {'created_at': _now().isoformat(), 'designs': rows}
