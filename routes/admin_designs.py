"""Admin Designs: the library and gallery tabs, review, organize, matches, tags and categories.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
import json
import re
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, jsonify, current_app, Response
from flask_login import current_user
from sqlalchemy import or_
from models import db, Design

from routes.admin import _next_sku, admin_bp, admin_required  # noqa: E402


# ===== DESIGNS (Library + Gallery tabs) =====

def _admin_designs_url(tab='gallery'):
    """Canonical designs page URL; tab is library|gallery."""
    tab = 'library' if tab == 'library' else 'gallery'
    return url_for('admin.designs', tab=tab)


# -- Design library: the review list --------------------------------------------

def _review_designs():
    from sqlalchemy import or_
    return Design.query.filter(or_(Design.ai_status.in_(['needs_review', 'error']), Design.ip_status == 'review'))


def _category_summary(design):
    from models import DesignCategoryLink
    from utils.design_taxonomy import label_for
    rows = DesignCategoryLink.query.filter_by(design_id=design.id).order_by(DesignCategoryLink.is_primary.desc()).all()
    return ', '.join(label_for(r.category_key, r.subcategory_key) or r.category_key for r in rows) or 'none'


def _apply_review_edits(design, form):
    """Your edits from the review page: saved as manual choices, remembered and locked. Returns notes to show."""
    from models import DesignCategoryLink
    from utils.design_ai import link_manual_folders
    from utils.design_categories import compose_extra_categories, public_extra_storage_keys, stored_music_genres
    from utils.design_tags import clean_tags, record_correction, set_manual_tags
    from utils.design_taxonomy import is_valid_pair, legacy_key_for, COLLECTION_BY_KEY
    notes = []
    uid = current_user.id

    title = re.sub(r'\s+', ' ', (form.get('title') or '')).strip()[:200]
    if title and title != (design.title or ''):
        record_correction(design, 'title', design.title, title, 'renamed', user_id=uid)
        design.title = title

    primary = (form.get('collection') or '').strip()
    sub = (form.get('sub') or '').strip() or None
    extras = [k for k in form.getlist('extra') if k in COLLECTION_BY_KEY and k != primary]
    if primary in COLLECTION_BY_KEY:
        if not is_valid_pair(primary, sub):
            sub = None
        before = _category_summary(design)
        DesignCategoryLink.query.filter_by(design_id=design.id).delete()
        db.session.add(DesignCategoryLink(design_id=design.id, category_key=primary, subcategory_key=sub,
                                          is_primary=True, source='manual', locked=True))
        for key in extras:
            db.session.add(DesignCategoryLink(design_id=design.id, category_key=key, subcategory_key=None,
                                              is_primary=False, source='manual', locked=True))
        db.session.flush()
        after = _category_summary(design)
        if before != after:
            record_correction(design, 'categories', before, after, 'categories_changed', user_id=uid)
        # keep the gallery you already have working
        legacy_primary = legacy_key_for(primary)
        design.folder = legacy_primary or 'evergreen'
        public = [legacy_key_for(k) for k in extras if legacy_key_for(k) and legacy_key_for(k) != design.folder]
        design.extra_categories = compose_extra_categories(
            public, stored_music_genres(design.extra_categories)) or None

    words = [w for w in re.split(r'[,\n]+', form.get('tags') or '') if w.strip()]
    if 'tags' in form:
        slugs = clean_tags(words)
        unknown = [w.strip() for w in words if not clean_tags([w])]
        set_manual_tags(design, slugs, user_id=uid)
        if unknown:
            notes.append('Not in the tag list, so skipped: ' + ', '.join(unknown[:6]) + '. You can add them under Design Tags.')
    return notes


@admin_bp.route('/design-library')
@admin_required
def design_library_overview():
    """One calm page: how the library is doing, what needs you, and what it has learned from you."""
    from utils.design_learning import overview
    from utils.design_organizer import checklist
    return render_template('admin/design_library.html', o=overview(), plan=checklist())


@admin_bp.route('/design-library/categories', methods=['GET', 'POST'])
@admin_required
def design_categories():
    """Add, rename and remove your own collections and categories."""
    from utils import design_category_admin as ca
    from utils.design_taxonomy import COLLECTIONS, refresh
    refresh(force=True)
    if request.method == 'POST':
        f = request.form
        action = f.get('action', '')
        if action == 'add_sub':
            ok, msg = ca.add_subcategory(f.get('coll', ''), f.get('label', ''))
        elif action == 'add_collection':
            ok, msg = ca.add_collection(f.get('label', ''))
        elif action == 'rename':
            ok, msg = ca.rename(f.get('target', ''), f.get('label', ''))
        elif action == 'remove_sub':
            ok, msg = ca.remove_subcategory(f.get('coll', ''), f.get('sub', ''))
        elif action == 'remove_collection':
            ok, msg = ca.remove_collection(f.get('key', ''))
        elif action == 'restore':
            ok, msg = ca.restore(f.get('kind', ''), f.get('key', ''))
        else:
            ok, msg = False, 'Choose what to do first.'
        flash(msg, 'success' if ok else 'info')
        db.session.commit()
        return redirect(url_for('admin.design_categories'))
    per_coll, per_sub = ca.counts()
    return render_template('admin/design_categories.html', collections=list(COLLECTIONS), per_coll=per_coll,
                           per_sub=per_sub, removed=ca.removed_items())


@admin_bp.route('/design-library/browse', methods=['GET', 'POST'])
@admin_required
def design_browse():
    """Search the whole library (hidden designs too) and change many designs at once."""
    from utils import design_browse as br
    from utils.cloud_storage import image_url
    from utils.design_tags import TAG_TYPE_LABELS, vocabulary
    from utils.design_taxonomy import COLLECTIONS
    if request.method == 'POST':
        ids = [int(i) for i in request.form.getlist('ids') if i.isdigit()]
        action = request.form.get('action', '')
        back = {k: v for k, v in request.form.items() if k.startswith('f_') and v}
        back = {k[2:]: v for k, v in back.items()}
        if not ids:
            flash('Tick the designs you want to change first.', 'info')
        elif action == 'reread':
            key = (current_app.config.get('OPENAI_API_KEY') or '').strip()
            done, failed = br.reread(ids, key)
            flash(f'Read {done} design{"" if done == 1 else "s"} again' + (f'; {failed} could not be read (see Processing errors).' if failed else '.')
                  + (' Only the first 5 are read at a time.' if len(ids) > 5 else ''), 'success' if not failed else 'info')
        else:
            value = request.form.get('collection') if action == 'add_collection' else request.form.get('tag')
            _n, note = br.bulk_apply(ids, action, value, user_id=current_user.id)
            flash(note, 'success' if _n else 'info')
        db.session.commit()
        return redirect(url_for('admin.design_browse', **back))
    rows, total, page, used = br.find(request.args)
    places, tags = br.describe(rows)
    vocab = sorted((t for t in vocabulary(active_only=False).values() if t.tag_type != 'color'),
                   key=lambda t: (t.tag_type, t.label.lower()))
    cards = [{'d': d, 'url': image_url(d.file_path) if d.file_path else '', 'places': places.get(d.id, []),
              'tags': tags.get(d.id, [])[:6]} for d in rows]
    return render_template('admin/design_browse.html', cards=cards, total=total, page=page, used=used,
                           pages=max(1, -(-total // br.PAGE_SIZE)), statuses=br.STATUSES, collections=COLLECTIONS,
                           vocab=vocab, type_labels=TAG_TYPE_LABELS,
                           colors=['black', 'white', 'gray', 'red', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'brown', 'gold', 'silver'])


@admin_bp.route('/design-library/review', methods=['GET', 'POST'])
@admin_required
def design_review():
    from models import DesignCategoryLink
    from utils.cloud_storage import image_url
    from utils.design_tags import design_tag_slugs, vocabulary
    from utils.design_taxonomy import COLLECTIONS, label_for
    if request.method == 'POST':
        design = Design.query.get_or_404(request.form.get('design_id', type=int))
        action = request.form.get('action', 'save')
        for note in _apply_review_edits(design, request.form):
            flash(note, 'info')
        if action == 'clear_ip' or request.form.get('clear_ip') == 'on':
            design.ip_status = 'cleared'
        label = design.title or design.original_filename or 'Design'
        if action == 'approve':
            has_place = DesignCategoryLink.query.filter_by(design_id=design.id).count() > 0
            if not has_place:
                db.session.rollback()
                flash(f'Pick a collection for "{label}" first, then approve it.', 'error')
                return redirect(url_for('admin.design_review'))
            design.is_gallery = True
            design.ai_status = 'done'
            if not design.sku:
                design.sku = _next_sku(design.folder)
            flash(f'"{label}" is approved and live in the gallery.', 'success')
        elif action == 'keep':
            design.is_gallery = False
            flash(f'"{label}" stays hidden for now.', 'info')
        else:
            flash(f'Saved "{label}".', 'success')
        design.modified_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for('admin.design_review'))

    vocab = vocabulary(active_only=False)
    cards = []
    for design in _review_designs().order_by(Design.uploaded_at.desc()).limit(100).all():
        try:
            sug = json.loads(design.ai_suggestions or '{}')
        except ValueError:
            sug = {}
        links = DesignCategoryLink.query.filter_by(design_id=design.id).order_by(DesignCategoryLink.is_primary.desc()).all()
        primary = next((l for l in links if l.is_primary), links[0] if links else None)
        guess = (sug.get('unsure') or [None])[0] if not primary else None
        cards.append({
            'design': design, 'url': image_url(design.file_path) if design.file_path else '',
            'primary': primary.category_key if primary else (guess or {}).get('key', ''),
            'sub': (primary.subcategory_key if primary else (guess or {}).get('sub')) or '',
            'extras': [l.category_key for l in links if not l.is_primary],
            'suggested': [{'label': label_for(p.get('key'), p.get('sub')) or label_for(p.get('key')),
                           'confidence': int(round(float(p.get('confidence') or 0) * 100))}
                          for p in (sug.get('unsure') or [])],
            'tags': ', '.join(vocab[s].label for s in design_tag_slugs(design) if s in vocab),
            'protected': sug.get('protected_words') or [],
            'held': not design.is_gallery,
        })
    return render_template(
        'admin/design_review.html', cards=cards, collections=COLLECTIONS,
        tag_labels=sorted({t.label for t in vocab.values() if t.is_active}),
        subs={c.key: [(s.key, s.label) for s in c.subcategories] for c in COLLECTIONS})


# -- Design library: duplicates and versions of the same design ------------------

MATCH_TABS = (('duplicates', 'Same artwork', 'exact_duplicate'), ('colors', 'Color versions', 'color_variation'),
              ('wording', 'Wording versions', 'wording_variation'), ('sets', 'Matching sets', 'matching_set'))


def _decide(rel, status):
    rel.status = status
    rel.decided_at = datetime.utcnow()


def _identical_groups(rows):
    """({design id: how many identical copies it belongs to}, {design id: its group}) from the open "same artwork" pairs.
    Four identical files make six pairs; they are one group of copies, and this finds the group."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in rows:
        parent[find(r.design_id)] = find(r.related_design_id)
    size = {}
    for x in list(parent):
        size[find(x)] = size.get(find(x), 0) + 1
    return {x: size[find(x)] for x in parent}, {x: find(x) for x in parent}


def _copies_of(rel):
    """Every open "same artwork" pair among the copies that rel's two designs belong to, and those design ids."""
    from models import DesignRelation
    rows = DesignRelation.query.filter_by(relation_type='exact_duplicate', status='suggested').all()
    ids = {rel.design_id, rel.related_design_id}
    grew = True
    while grew:
        grew = False
        for r in rows:
            if (r.design_id in ids) != (r.related_design_id in ids):
                ids |= {r.design_id, r.related_design_id}
                grew = True
    return [r for r in rows if r.design_id in ids and r.related_design_id in ids], ids


def _group_as_colors(rel):
    """Make one design the color option of another, using the gallery's existing color-family feature."""
    from utils.design_metadata import unique_variant_label
    from utils.design_variants import ensure_not_nested_parent
    a, b = rel.design, rel.related
    parent = ensure_not_nested_parent(a if a.id < b.id else b) or (a if a.id < b.id else b)
    child = b if parent.id == a.id else a
    if child.id == parent.id or child.color_variants.count() or child.parent_design_id:
        return False, 'One of these already belongs to a color family, so I only connected them.'
    families = [f for f in (child.color_families or '').split(',') if f]
    label = unique_variant_label(parent, (' & '.join(f.title() for f in families[:2]) or 'Color')[:80])
    if not (parent.variant_label or '').strip():
        parent.variant_label = unique_variant_label(parent, ' & '.join(f.title() for f in
                                                                       (parent.color_families or '').split(',')[:2] if f) or 'Default')
    child.parent_design_id = parent.id
    child.variant_label = label
    child.title = parent.title or child.title
    child.is_gallery = True
    rel.action = 'grouped'
    return True, f'"{child.variant_label}" is now a color option of "{parent.title or "the main design"}".'


@admin_bp.route('/design-library/matches', methods=['GET', 'POST'])
@admin_required
def design_matches():
    from models import DesignRelation
    from utils import design_fingerprint as fp
    from utils.cloud_storage import image_url
    if request.method == 'POST':
        rel = DesignRelation.query.get(request.form.get('relation_id', type=int) or 0)
        action = request.form.get('action', '')
        if rel is None:
            return redirect(url_for('admin.design_matches'))
        tab = next((k for k, _l, t in MATCH_TABS if t == rel.relation_type), 'duplicates')
        if action == 'dismiss':
            _decide(rel, 'dismissed')
            flash('Okay, I will not suggest that pair again.', 'info')
        elif action == 'connect':
            if rel.relation_type == 'exact_duplicate':           # keep every copy of the same artwork in one click
                pairs, ids = _copies_of(rel)
                for pair in pairs or [rel]:
                    _decide(pair, 'confirmed')
                flash(f'Kept all {len(ids) or 2} copies of this artwork.', 'success')
            else:
                _decide(rel, 'confirmed')
                flash('Connected. They will show as related designs.', 'success')
        elif action == 'make_set':
            rel.relation_type = 'matching_set'
            _decide(rel, 'confirmed')
            tab = 'sets'
            flash('Marked as a matching set.', 'success')
        elif action == 'group_colors':
            ok, note = _group_as_colors(rel)
            _decide(rel, 'confirmed')
            flash(note, 'success' if ok else 'info')
        elif action == 'hide_copy':
            extra = rel.related if rel.related_design_id > rel.design_id else rel.design
            extra.is_gallery = False
            rel.action = 'hidden'
            _decide(rel, 'confirmed')
            from models import DesignRelation as _DR                     # the other pairs that included the hidden copy are settled too
            for other in _DR.query.filter_by(relation_type='exact_duplicate', status='suggested').filter(
                    db.or_(_DR.design_id == extra.id, _DR.related_design_id == extra.id)).all():
                _decide(other, 'confirmed')
            flash(f'"{extra.title or "The extra copy"}" is hidden from customers. Nothing was deleted, and you can undo this.', 'success')
        elif action == 'undo':
            if rel.action == 'grouped':
                child = rel.design if rel.design.parent_design_id else rel.related
                if child.parent_design_id:
                    child.parent_design_id = None
            elif rel.action == 'hidden':
                extra = rel.related if rel.related_design_id > rel.design_id else rel.design
                extra.is_gallery = True
            rel.action = None
            rel.status, rel.decided_at = 'suggested', None
            flash('Undone.', 'success')
        db.session.commit()
        return redirect(url_for('admin.design_matches', tab=tab))

    tab = request.args.get('tab') if request.args.get('tab') in {k for k, _l, _t in MATCH_TABS} else None
    tallies = dict(db.session.query(DesignRelation.relation_type, db.func.count(DesignRelation.id))
                   .filter(DesignRelation.status == 'suggested').group_by(DesignRelation.relation_type).all())
    tabs = [{'key': k, 'label': label, 'type': t, 'count': tallies.get(t, 0)} for k, label, t in MATCH_TABS]
    if tab is None:
        tab = next((t['key'] for t in tabs if t['count']), 'duplicates')
    kind = next(t['type'] for t in tabs if t['key'] == tab)

    def card(rel):
        def side(d):
            return {'design': d, 'url': image_url(d.file_path) if d.file_path else '',
                    'colors': ', '.join(f.title() for f in (d.color_families or '').split(',') if f)}
        return {'rel': rel, 'a': side(rel.design), 'b': side(rel.related), 'score': int(round((rel.score or 0) * 100)),
                'copies': groups.get(rel.design_id, 2) if rel.relation_type == 'exact_duplicate' else 0}
    open_rows = (DesignRelation.query.filter_by(relation_type=kind, status='suggested')
                 .order_by(DesignRelation.score.desc()).limit(60).all())
    groups = {}
    if kind == 'exact_duplicate':                                       # one card for each group of copies, not one per pair
        groups, roots = _identical_groups(open_rows)
        seen_groups, kept = set(), []
        for r in open_rows:
            if roots[r.design_id] not in seen_groups:
                seen_groups.add(roots[r.design_id])
                kept.append(r)
        open_rows = kept
    done_rows = (DesignRelation.query.filter_by(status='confirmed').filter(DesignRelation.action.isnot(None))
                 .order_by(DesignRelation.decided_at.desc()).limit(15).all())
    return render_template('admin/design_matches.html', tabs=tabs, tab=tab, cards=[card(r) for r in open_rows],
                           done=[card(r) for r in done_rows], stats=fp.counts(), labels=fp.RELATION_LABELS)


@admin_bp.route('/design-library/matches/scan', methods=['POST'])
@admin_required
def design_matches_scan():
    """Fingerprint a few more designs and look for matches (the matches page calls this while it waits)."""
    from utils import design_fingerprint as fp
    done, found = fp.scan_batch(3)
    return jsonify({'processed': done, 'found': found, 'counts': fp.counts()})


# -- Design library: organize the designs you already have -----------------------

def _proposal_card(row, vocab):
    from utils.cloud_storage import image_url
    from utils.design_taxonomy import label_for
    design = row.design
    try:
        result = json.loads(row.result_json or '{}')
    except ValueError:
        result = {}
    today = []
    for key in [design.folder] + [k for k in (design.extra_categories or '').split(',') if k.strip()]:
        today.append(key)
    places = [{'label': label_for(p['key'], p.get('sub')) or label_for(p['key']),
               'confidence': int(round(p['confidence'] * 100)), 'sure': p['confidence'] >= 0.75}
              for p in result.get('collections') or []]
    from utils.design_organizer import folder_places
    have = {p['label'] for p in places}
    carried = [label_for(k) for k in folder_places(design) if label_for(k) not in have]
    return {
        'row': row, 'design': design, 'url': image_url(design.file_path) if design.file_path else '',
        'today': today, 'places': places, 'carried': carried,
        'tags': [vocab[s].label for s in (result.get('tags') or []) if s in vocab
                 and vocab[s].label.lower() not in {p['label'].lower() for p in places}
                 and vocab[s].label.lower() != (result.get('style') or '').lower()],
        'style': result.get('style') or '', 'protected': result.get('protected_words') or [],
        'new_title': result.get('title') if result.get('title') and not (design.title or '').strip() else '',
        'confidence': int(round((row.confidence or 0) * 100)), 'source': result.get('source'),
    }


@admin_bp.route('/design-library/organize', methods=['GET', 'POST'])
@admin_required
def design_organize():
    from models import DesignProposal
    from utils import design_organizer as org
    from utils.design_tags import vocabulary
    if request.method == 'POST':
        action = request.form.get('action', '')
        ids = [int(i) for i in request.form.getlist('ids') if str(i).isdigit()]
        if action == 'analyze':
            mode = 'name' if request.form.get('mode') == 'name' else 'smart'
            batch, count = org.plan_batch(request.form.get('size', type=int) or 25, mode)
            if not count:
                flash('Every design has already been looked at.', 'info')
            else:
                org.process_queue(3)
                flash(f'Looking at {count} design{"" if count == 1 else "s"}. They will appear below as they are ready. '
                      'Nothing changes until you apply it.', 'success')
        elif action == 'apply' and not ids:
            flash('Tick the designs you want to apply first.', 'info')
        elif action in ('apply', 'apply_confident'):
            org.auto_backup()                          # a copy of everything, saved right before any change
            query = DesignProposal.query.filter(DesignProposal.status == 'ready')
            if action == 'apply_confident':
                query = query.filter(DesignProposal.needs_attention == False)  # noqa: E712
            else:
                query = query.filter(DesignProposal.id.in_(ids or [0]))
            applied = 0
            for row in query.all():
                if org.apply_proposal(row, current_user.id):
                    applied += 1
                    if applied % 25 == 0:
                        db.session.commit()
            db.session.commit()
            flash(f'Applied to {applied} design{"" if applied == 1 else "s"}. A backup was saved first, and you can undo any of them below.'
                  if applied else 'Nothing needed applying for those.', 'success' if applied else 'info')
        elif action == 'skip':
            DesignProposal.query.filter(DesignProposal.id.in_(ids or [0]), DesignProposal.status == 'ready').update(
                {'status': 'skipped'}, synchronize_session=False)
            db.session.commit()
            flash('Skipped. Those designs will not be suggested again.' if ids else 'Tick the designs you want to skip first.', 'info')
        elif action == 'undo':
            row = DesignProposal.query.get(request.form.get('proposal_id', type=int) or 0)
            if row and org.undo_proposal(row):
                db.session.commit()
                flash('Undone. That design is back exactly as it was.', 'success')
        elif action == 'undo_batch':
            rows = DesignProposal.query.filter_by(batch_id=request.form.get('batch_id', ''), status='applied').all()
            count = sum(1 for r in rows if org.undo_proposal(r))
            db.session.commit()
            flash(f'Undid {count} design{"" if count == 1 else "s"}.', 'success')
        return redirect(url_for('admin.design_organize') + '#ogFlash')

    vocab = vocabulary(active_only=False)
    ready = (DesignProposal.query.filter_by(status='ready').order_by(DesignProposal.needs_attention,
                                                                     DesignProposal.confidence.desc()).limit(150).all())
    cards = [_proposal_card(r, vocab) for r in ready]
    applied = (DesignProposal.query.filter_by(status='applied').order_by(DesignProposal.applied_at.desc()).limit(40).all())
    stats = org.summary()
    return render_template(
        'admin/design_organize.html', stats=stats, confident=[c for c in cards if not c['row'].needs_attention],
        attention=[c for c in cards if c['row'].needs_attention],
        applied=[_proposal_card(r, vocab) for r in applied],
        per_design=org.COST_PER_DESIGN,
        ai_ready=bool((current_app.config.get('OPENAI_API_KEY') or '').strip()),
        confident_total=DesignProposal.query.filter_by(status='ready', needs_attention=False).count())


@admin_bp.route('/design-library/organize/process', methods=['POST'])
@admin_required
def design_organize_process():
    """Do a little more of the queued analysis (the organize page calls this while it waits)."""
    from utils import design_organizer as org
    done = org.process_queue(3)
    return jsonify({'processed': done, 'summary': org.summary()})


@admin_bp.route('/design-library/organize/backup.json')
@admin_required
def design_organize_backup():
    """A copy of everything the organizer can change, to keep before you apply anything."""
    from utils import design_organizer as org
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M')
    org.mark_backup()
    return Response(json.dumps(org.snapshot(), indent=1), mimetype='application/json',
                    headers={'Content-Disposition': f'attachment; filename=design-library-backup-{stamp}.json'})


# -- Design library: the standard tag vocabulary -------------------------------

def _words(raw, limit=25):
    """A comma or line separated field -> clean, de-duplicated list."""
    out = []
    for part in re.split(r'[,\n]+', raw or ''):
        word = re.sub(r'\s+', ' ', part).strip()[:60]
        if word and word.lower() not in [w.lower() for w in out]:
            out.append(word)
    return out[:limit]


@admin_bp.route('/design-library/tags', methods=['GET', 'POST'])
@admin_required
def design_tags():
    from models import DesignTag, DesignTagLink
    from utils.design_tags import (
        TAG_TYPES, TAG_TYPE_LABELS, canonical_for, ensure_vocabulary, slugify,
        tag_implies, tag_related, tag_synonyms,
    )
    ensure_vocabulary()
    if request.method == 'POST':
        action = request.form.get('action', '')
        tag = DesignTag.query.get(request.form.get('tag_id', type=int)) if request.form.get('tag_id') else None

        def slugs_for(raw):
            found = []
            for word in _words(raw):
                other = canonical_for(word)
                if other and other.slug not in found and (not tag or other.id != tag.id):
                    found.append(other.slug)
            return found

        if action == 'add':
            label = (request.form.get('label') or '').strip()[:80]
            tag_type = request.form.get('tag_type') if request.form.get('tag_type') in TAG_TYPE_LABELS else 'theme'
            slug = slugify(label)
            if not label or not slug:
                flash('Please give the tag a name.', 'error')
            elif DesignTag.query.filter_by(slug=slug).first() or canonical_for(label):
                flash(f'"{label}" already exists (or is a synonym of an existing tag), so I did not add a duplicate.', 'info')
            else:
                db.session.add(DesignTag(slug=slug, label=label, tag_type=tag_type,
                                         synonyms=json.dumps(_words(request.form.get('synonyms'))),
                                         implies=json.dumps(slugs_for(request.form.get('implies'))),
                                         related=json.dumps(slugs_for(request.form.get('related'))), is_active=True))
                db.session.commit()
                flash(f'Added "{label}".', 'success')
        elif tag and action == 'update':
            label = (request.form.get('label') or '').strip()[:80]
            if label:
                tag.label = label
            if request.form.get('tag_type') in TAG_TYPE_LABELS:
                tag.tag_type = request.form.get('tag_type')
            tag.synonyms = json.dumps(_words(request.form.get('synonyms')))
            tag.implies = json.dumps(slugs_for(request.form.get('implies')))
            tag.related = json.dumps(slugs_for(request.form.get('related')))
            db.session.commit()
            flash(f'Saved "{tag.label}".', 'success')
        elif tag and action == 'toggle':
            tag.is_active = not tag.is_active
            db.session.commit()
            flash(f'"{tag.label}" is now {"on" if tag.is_active else "off"}.', 'success')
        elif tag and action == 'delete':
            if DesignTagLink.query.filter_by(tag_id=tag.id).count():
                tag.is_active = False
                flash(f'"{tag.label}" is used by designs, so I turned it off instead of deleting it.', 'info')
            else:
                db.session.delete(tag)
                flash('Tag deleted.', 'success')
            db.session.commit()
        return redirect(url_for('admin.design_tags'))

    counts = dict(db.session.query(DesignTagLink.tag_id, db.func.count(DesignTagLink.id))
                  .group_by(DesignTagLink.tag_id).all())
    by_slug = {t.slug: t for t in DesignTag.query.all()}
    groups = []
    for key, label in TAG_TYPES:
        rows = sorted((t for t in by_slug.values() if t.tag_type == key), key=lambda t: t.label.lower())
        groups.append({'key': key, 'label': label, 'tags': [{
            'tag': t, 'count': counts.get(t.id, 0),
            'synonyms': ', '.join(tag_synonyms(t)),
            'implies': ', '.join(by_slug[s].label for s in tag_implies(t) if s in by_slug),
            'related': ', '.join(by_slug[s].label for s in tag_related(t) if s in by_slug),
        } for t in rows]})
    return render_template('admin/design_tags.html', groups=groups, types=TAG_TYPES)


@admin_bp.route('/designs')
@admin_required
def designs():
    """Combined Design Library (customer uploads) + Gallery (curated public designs)."""
    from utils.design_places import describe_many, unfiled_count
    from utils.design_taxonomy import COLLECTIONS

    tab = (request.args.get('tab') or 'gallery').strip().lower()
    if tab not in ('library', 'gallery'):
        tab = 'gallery'

    library_designs = []
    if tab == 'library':                      # the customer-upload pictures are only loaded when you ask for them
        library_designs = (
            Design.query
            .filter(
                Design.is_gallery == False,
                or_(Design.hidden_from_admin == False, Design.hidden_from_admin.is_(None)),
            )
            .order_by(Design.uploaded_at.desc())
            .all()
        )

    try:
        from utils.design_variants import gallery_mains_query
        gallery_designs = gallery_mains_query(Design).all()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Failed to load admin design gallery: %s', e)
        flash('We could not load the design gallery (a database issue). '
              'If this persists, a database migration may be pending.', 'error')
        gallery_designs = []

    return render_template(
        'admin/designs.html',
        active_tab=tab,
        library_designs=library_designs,
        gallery_designs=gallery_designs,
        collections=COLLECTIONS,
        ai_ready=bool((current_app.config.get('OPENAI_API_KEY') or '').strip()),
        design_places=describe_many(gallery_designs),
        unfiled_count=unfiled_count(gallery_designs),
    )
